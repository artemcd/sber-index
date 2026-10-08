import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from run_baseline import (
    CATEGORIES,
    CLUSTER_NAMES,
    FEATURES,
    ROOT,
    load_monthly_features,
)
from run_graph_model import canonical_labels, modularity, normalized, transport_graph


CONFIG = ROOT / "config" / "dynamic_model.json"
REFERENCE = ROOT / "artifacts" / "graph" / "annual_clusters.csv"
OUTPUT = ROOT / "artifacts" / "dynamic" / "monthly_clusters.csv"
METRICS = ROOT / "artifacts" / "dynamic" / "model_metrics.csv"
SENSITIVITY = ROOT / "artifacts" / "dynamic" / "bandwidth_sensitivity.csv"
REPORT = ROOT / "reports" / "dynamic_clustering.md"
ECONOMIC_FEATURES = FEATURES[:-1]


def load_config(path: Path = CONFIG) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "clusters",
        "cluster_counts",
        "highway_neighbors",
        "railway_neighbors",
        "rail_weight",
        "neighbor_mix",
        "economic_bandwidths",
        "random_state",
        "n_init",
    }
    if set(config) != required:
        raise SystemExit(f"Поля конфигурации должны быть: {sorted(required)}")
    cluster_counts = config["cluster_counts"]
    if (
        not cluster_counts
        or cluster_counts != sorted(set(cluster_counts))
        or cluster_counts[0] < 2
        or config["clusters"] not in cluster_counts
    ):
        raise SystemExit("Проверьте сетку числа кластеров")
    if config["clusters"] != len(CLUSTER_NAMES):
        raise SystemExit("Для текущих названий типов требуется три кластера")
    return config


def prepare_monthly() -> tuple[pd.DataFrame, list[int]]:
    monthly, market = load_monthly_features()
    monthly = monthly.merge(
        market, on="territory_id", how="left", validate="many_to_one"
    )
    missing_ids = sorted(
        monthly.loc[monthly["market_access"].isna(), "territory_id"].unique()
    )
    monthly["market_access"] = monthly["market_access"].fillna(
        monthly["market_access"].median()
    )
    monthly["log_market_access"] = np.log(monthly["market_access"])
    monthly = monthly.sort_values(["date", "territory_id"]).reset_index(drop=True)

    months = monthly["date"].nunique()
    territories = monthly["territory_id"].nunique()
    if months != 24 or len(monthly) != months * territories:
        raise SystemExit("Помесячная панель перестала быть сбалансированной")
    if not np.isfinite(monthly[FEATURES].to_numpy()).all():
        raise SystemExit("В признаках появились нечисловые значения")
    return monthly, list(map(int, missing_ids))


def scaled_monthly(monthly: pd.DataFrame, features: list[str] = FEATURES) -> np.ndarray:
    frame = monthly[features].copy()
    shares = list(CATEGORIES.values())
    frame[shares] -= monthly.groupby("date")[shares].transform("median")
    return StandardScaler().fit_transform(frame)


def economic_graph(
    transport: sparse.csr_matrix,
    economic_attributes: np.ndarray,
    bandwidth: float,
) -> sparse.csr_matrix:
    graph = transport.copy()
    rows = np.repeat(np.arange(graph.shape[0]), np.diff(graph.indptr))
    differences = economic_attributes[rows] - economic_attributes[graph.indices]
    graph.data *= np.exp(-np.square(differences).sum(axis=1) / (2 * bandwidth**2))
    return graph


def representations(
    attributes: np.ndarray,
    transport: sparse.csr_matrix,
    node_count: int,
    neighbor_mix: float,
    bandwidth: float,
) -> tuple[np.ndarray, np.ndarray, list[sparse.csr_matrix]]:
    static_mean = normalized(transport)
    static_blocks = []
    dynamic_blocks = []
    dynamic_graphs = []
    connected = np.asarray(transport.sum(axis=1)).ravel() > 0

    for start in range(0, len(attributes), node_count):
        block = attributes[start : start + node_count]
        static_neighbors = static_mean @ block
        static_neighbors[~connected] = block[~connected]
        static_blocks.append(
            (1 - neighbor_mix) * block + neighbor_mix * static_neighbors
        )

        graph = economic_graph(
            transport,
            block[:, : len(ECONOMIC_FEATURES)],
            bandwidth,
        )
        dynamic_neighbors = normalized(graph) @ block
        dynamic_neighbors[~connected] = block[~connected]
        dynamic_blocks.append(
            (1 - neighbor_mix) * block + neighbor_mix * dynamic_neighbors
        )
        dynamic_graphs.append(graph)

    return np.vstack(static_blocks), np.vstack(dynamic_blocks), dynamic_graphs


def fit_model(attributes: np.ndarray, config: dict) -> KMeans:
    return KMeans(
        n_clusters=config["clusters"],
        n_init=config["n_init"],
        random_state=config["random_state"],
    ).fit(attributes)


def model_metrics(
    name: str,
    attributes: np.ndarray,
    labels: np.ndarray,
    graphs: list[sparse.csr_matrix],
    node_count: int,
    random_state: int,
) -> dict:
    monthly_labels = labels.reshape(-1, node_count)
    return {
        "model": name,
        "silhouette": silhouette_score(
            attributes,
            labels,
            sample_size=min(10_000, len(labels)),
            random_state=random_state,
        ),
        "dynamic_modularity": np.mean(
            [
                modularity(graph, month_labels)
                for graph, month_labels in zip(graphs, monthly_labels)
            ]
        ),
        "month_to_month_stability": np.mean(
            monthly_labels[1:] == monthly_labels[:-1]
        ),
        "min_monthly_cluster_share": min(
            np.bincount(month_labels, minlength=3).min() / node_count
            for month_labels in monthly_labels
        ),
    }


def annual_agreement(monthly: pd.DataFrame, labels: np.ndarray) -> float:
    reference = pd.read_csv(REFERENCE)
    assignments = monthly[["territory_id", "year"]].copy()
    assignments["cluster"] = labels
    majority = (
        assignments.groupby(["territory_id", "year"])["cluster"]
        .agg(lambda values: values.value_counts().index[0])
        .rename("monthly_majority")
        .reset_index()
    )
    comparison = reference.merge(
        majority, on=["territory_id", "year"], validate="one_to_one"
    )
    return adjusted_rand_score(
        comparison["graph_cluster"], comparison["monthly_majority"]
    )


def format_metrics(frame: pd.DataFrame) -> str:
    result = frame.copy()
    for column in ["silhouette", "dynamic_modularity", "ari_dynamic", "ari_static"]:
        if column in result:
            result[column] = result[column].map("{:.4f}".format)
    for column in [
        "month_to_month_stability",
        "min_monthly_cluster_share",
        "edge_weight_ratio",
    ]:
        if column in result:
            result[column] = result[column].map("{:.1%}".format)
    return result.to_string(index=False)


def main() -> None:
    config = load_config()
    monthly, missing_ids = prepare_monthly()
    territory_ids = sorted(map(int, monthly["territory_id"].unique()))
    node_count = len(territory_ids)
    attributes = scaled_monthly(monthly)

    highway, highway_scale = transport_graph(
        territory_ids, "highway", config["highway_neighbors"]
    )
    railway, railway_scale = transport_graph(
        territory_ids, "railway", config["railway_neighbors"]
    )
    transport = (highway + config["rail_weight"] * railway).tocsr()
    static_attributes, _, _ = representations(
        attributes,
        transport,
        node_count,
        config["neighbor_mix"],
        config["economic_bandwidths"][0],
    )

    attribute_labels = fit_model(attributes, config).labels_
    static_labels = fit_model(static_attributes, config).labels_
    sensitivity_rows = []
    for bandwidth in config["economic_bandwidths"]:
        _, candidate_attributes, candidate_graphs = representations(
            attributes,
            transport,
            node_count,
            config["neighbor_mix"],
            bandwidth,
        )
        candidate_labels = fit_model(candidate_attributes, config).labels_
        row = model_metrics(
            "dynamic_economic_network",
            attributes,
            candidate_labels,
            candidate_graphs,
            node_count,
            config["random_state"],
        )
        row["economic_bandwidth"] = bandwidth
        row["edge_weight_ratio"] = np.mean(
            [graph.sum() / transport.sum() for graph in candidate_graphs]
        )
        row["ari_static"] = adjusted_rand_score(static_labels, candidate_labels)
        sensitivity_rows.append(row)

    sensitivity = pd.DataFrame(sensitivity_rows)
    eligible = sensitivity[
        sensitivity["month_to_month_stability"].ge(0.95)
        & sensitivity["min_monthly_cluster_share"].ge(0.15)
    ]
    if eligible.empty:
        raise SystemExit("Ни одна ширина ядра не прошла ограничения")
    bandwidth = float(
        eligible.loc[eligible["silhouette"].idxmax(), "economic_bandwidth"]
    )
    _, dynamic_attributes, dynamic_graphs = representations(
        attributes,
        transport,
        node_count,
        config["neighbor_mix"],
        bandwidth,
    )
    dynamic_model = fit_model(dynamic_attributes, config)
    raw_dynamic_labels = dynamic_model.labels_
    dynamic_labels = canonical_labels(monthly, raw_dynamic_labels)

    rows = []
    for name, labels in [
        ("attributes", attribute_labels),
        ("static_transport", static_labels),
        ("dynamic_economic_network", raw_dynamic_labels),
    ]:
        row = model_metrics(
            name,
            attributes,
            labels,
            dynamic_graphs,
            node_count,
            config["random_state"],
        )
        row["ari_dynamic"] = adjusted_rand_score(raw_dynamic_labels, labels)
        rows.append(row)
    metrics = pd.DataFrame(rows)

    distances = dynamic_model.transform(dynamic_attributes)
    ordered_distances = np.sort(distances, axis=1)
    relative_margin = (
        ordered_distances[:, 1] - ordered_distances[:, 0]
    ) / ordered_distances[:, 1]

    monthly["cluster"] = dynamic_labels
    monthly["cluster_name"] = monthly["cluster"].map(CLUSTER_NAMES)
    monthly["relative_margin"] = relative_margin.round(6)
    monthly["changed_from_previous_month"] = (
        monthly.groupby("territory_id")["cluster"].diff().ne(0)
    )
    first_month = monthly["date"].eq(monthly["date"].min())
    monthly.loc[first_month, "changed_from_previous_month"] = False

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    monthly[
        [
            "territory_id",
            "date",
            "cluster",
            "cluster_name",
            "relative_margin",
            "changed_from_previous_month",
        ]
    ].sort_values(["territory_id", "date"]).to_csv(OUTPUT, index=False)
    metrics.to_csv(METRICS, index=False)
    sensitivity.to_csv(SENSITIVITY, index=False)

    profiles = monthly[monthly["date"].eq(monthly["date"].max())].groupby(
        ["cluster", "cluster_name"], as_index=False
    ).agg(
        municipalities=("territory_id", "size"),
        relative_spend=("relative_spend", "median"),
        market_access=("market_access", "median"),
        health_share=("health_share", "median"),
        marketplace_share=("marketplace_share", "median"),
        food_service_share=("food_service_share", "median"),
        grocery_share=("grocery_share", "median"),
        transport_share=("transport_share", "median"),
    )
    profiles["spend_index"] = np.exp(profiles.pop("relative_spend")) * 100
    for column in ["spend_index", "market_access"]:
        profiles[column] = profiles[column].map("{:.1f}".format)
    for column in CATEGORIES.values():
        profiles[column] = profiles[column].map("{:.1%}".format)

    monthly_labels = dynamic_labels.reshape(-1, node_count)
    transition_rates = pd.DataFrame(
        {
            "period": [
                f"{left} → {right}"
                for left, right in zip(
                    monthly["date"].unique()[:-1], monthly["date"].unique()[1:]
                )
            ],
            "changed_share": np.mean(
                monthly_labels[1:] != monthly_labels[:-1], axis=1
            ),
        }
    )
    yearly_ari = annual_agreement(monthly, dynamic_labels)
    low_margin = monthly["relative_margin"].lt(0.1).mean()
    average_edge_ratio = np.mean(
        [graph.sum() / transport.sum() for graph in dynamic_graphs]
    )
    comparison = metrics.set_index("model")
    static_result = comparison.loc["static_transport"]
    dynamic_result = comparison.loc["dynamic_economic_network"]

    report = f"""# Методологический отчёт: динамическая кластеризация

Проект «Локальный код», трек «Кластеризация» конкурса СберИндекса.
Задача — описать типы локальных экономик и их изменения за 2023–2024 годы.

## Выборка и признаки

Использована сбалансированная панель из {node_count} муниципалитетов и 24 месяцев:
в каждом наблюдении есть все шесть категорий расходов. Неполные ряды исключены,
поэтому смена состава выборки не создаёт ложных переходов.

Атрибуты узла — семь признаков:

- `log(расходы / медиана расходов того же месяца)` — относительный уровень;
- пять долей расходов: здоровье, маркетплейсы, общепит, продовольствие, транспорт;
- логарифм индекса доступности рынков — постоянный транспортно-географический контекст.

Доли считаются относительно показателя «Все категории»: их сумма не равна единице,
поскольку часть категорий не раскрыта. Из каждой доли вычитается медиана месяца,
чтобы убрать общий сдвиг потребительской корзины. Семь признаков стандартизируются
на всей панели. Индекс доступности для {len(missing_ids)} МО заполнен медианой.
Три типа выбраны с учётом [годового baseline](clustering_baseline.md) и
интерпретируемости. Дополнительное сравнение K = 2–8 на одинаковых подвыборках
помесячной панели описано в [проверке числа типов](decision_checks.md).
K = 3 остаётся выбранным уровнем детализации, не единственным оптимумом.

## Постановка

Транспортный граф строится отдельно для автодорог и железных дорог. Дубли пар
объединяются, для каждого узла берутся ближайшие соседи, а связь сохраняется,
если хотя бы один из двух узлов выбрал другой. В каждом слое
`T_ij = exp(-d_ij / s)`, где `s` — медиана положительных расстояний выбранных связей.
Итоговый транспортный вес: `T = T_highway + beta × T_railway`.

Построено 24 среза для {node_count} муниципалитетов с января 2023 по декабрь
2024 года. Кандидатные рёбра задаются транспортной близостью, но их вес меняется
каждый месяц вместе с экономическим профилем территорий:

`w_ij(t) = w_transport_ij × exp(-||z_i(t) - z_j(t)||² / (2h²))`.

Здесь `z(t)` содержит относительный уровень расходов и доли пяти категорий,
стандартизированные на всей панели; индекс доступности рынка в динамический вес
не входит. Это разделяет собственно экономическое сходство и постоянный
географический контекст.

Затем признаки смешиваются с профилем соседей:

`X_dynamic(t) = (1 - alpha) X(t) + alpha D(t)^(-1) W(t) X(t)`.

KMeans обучается один раз на всех месяцах, поэтому центры и номера трёх типов общие
для всей последовательности. Изменение типа — это переход муниципалитета между
областями одних и тех же центров, а не результат переименования независимых
кластеров.
Для узлов без транспортных связей сохраняются собственные признаки. Транспортная
топология ограничивает круг соседей: экономически похожие, но транспортно далёкие
территории могут попасть в один тип, не имея прямого ребра.

Номера типов упорядочены по медиане относительных расходов. Для устойчивого
перехода предыдущий и новый режим должны продолжаться минимум по три месяца.
Для примеров на лендинге новый режим должен держаться не менее шести месяцев.

## Параметры

- ближайших автодорожных соседей: {config['highway_neighbors']};
- ближайших железнодорожных соседей: {config['railway_neighbors']};
- вес железнодорожного слоя: {config['rail_weight']};
- доля профиля соседей `alpha`: {config['neighbor_mix']};
- выбранная ширина ядра экономического сходства `h`: {bandwidth};
- транспортный масштаб: {highway_scale:.1f} км для автодорог и {railway_scale:.1f} км для железной дороги.

Все гиперпараметры и сетка `h` вынесены в `config/dynamic_model.json`. Допускались
варианты со стабильностью не ниже 95% и минимальным месячным кластером не меньше
15%; среди них выбран максимум silhouette. Проверенная сетка:

```text
{format_metrics(sensitivity.drop(columns='model'))}
```

Средняя сумма динамических весов составляет {average_edge_ratio:.1%} от
транспортных весов.

## Сравнение моделей

Silhouette измеряется в исходном пространстве признаков на фиксированной выборке
10 000 наблюдений. Модульность всех вариантов рассчитана на одних и тех же
динамических графах. Стабильность — доля муниципалитетов, сохранивших тип в
следующем месяце.

```text
{format_metrics(metrics)}
```

По сравнению со статической сетью silhouette вырос на
**{dynamic_result['silhouette'] - static_result['silhouette']:+.4f}**, а
стабильность — на **{100 * (dynamic_result['month_to_month_stability'] - static_result['month_to_month_stability']):+.2f} п. п.**
Модульность снизилась на
**{dynamic_result['dynamic_modularity'] - static_result['dynamic_modularity']:+.4f}**.
Динамическая модель не доминирует по всем метрикам: её преимущество умеренное, а
выбор дополнительно опирается на соответствие постановке о меняющихся во времени
экономических связях.

ARI годовых модальных назначений относительно прежней годовой графовой модели:
**{yearly_ari:.3f}**. Это проверка преемственности, а не критерий выбора модели.

## Профили за декабрь 2024 года

```text
{profiles.to_string(index=False)}
```

## Динамика

В среднем тип от месяца к месяцу сохраняют
**{np.mean(monthly_labels[1:] == monthly_labels[:-1]):.1%}** муниципалитетов.
Минимальная доля переходов — **{transition_rates['changed_share'].min():.1%}**,
максимальная — **{transition_rates['changed_share'].max():.1%}**.
У **{low_margin:.1%}** назначений относительный отрыв до второго центра меньше 0.1;
их следует считать пограничными, а не уверенными переходами.

```text
{transition_rates.assign(changed_share=transition_rates['changed_share'].map('{:.1%}'.format)).to_string(index=False)}
```

## Ограничения

- это ретроспективная типология: стандартизация, центры и выбор параметров используют
  все 24 месяца; она не проверена как система мониторинга новых данных;
- топология транспорта и индекс доступности известны только на конец 2024 года и
  считаются постоянными;
- параметры транспорта перенесены из годовой модели, а ширина ядра выбрана по
  внутренней метрике той же выборки;
- bootstrap в [отчёте об устойчивости](model_validation.md) проверяет годовую
  сетевую модель; для финальной динамической модели он отдельно не выполнен;
- названия типов описательные; без населения, доходов и отраслевой структуры
  они не измеряют благополучие, а экономические причины переходов не установлены;
- месячный переход описывает смену экономического профиля, но сам по себе не
  доказывает структурное изменение территории;
- для {len(missing_ids)} муниципалитетов индекс доступности заполнен медианой:
  `{', '.join(map(str, missing_ids))}`.

Полный набор конкурсных метрик `SW`, `CH`, `S_Dbw`, `AVI`, `AVU`, `MQ` рассчитан
для четырёх методов в [сравнении моделей](model_comparison.md). Там SW усреднён
по 24 отдельным месячным выборкам, поэтому его значение отличается от SW на
объединённой выборке 10 000 наблюдений в этом отчёте.

Экономические профили и переходы приведены в
[интерпретации типов](cluster_interpretation.md), итоговая презентация —
[интерактивный лендинг](https://artemcd.github.io/sber-index/).
"""
    REPORT.write_text(report, encoding="utf-8")
    print(f"Кластеры: {OUTPUT.relative_to(ROOT)}")
    print(f"Метрики: {METRICS.relative_to(ROOT)}")
    print(f"Чувствительность: {SENSITIVITY.relative_to(ROOT)}")
    print(f"Отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
