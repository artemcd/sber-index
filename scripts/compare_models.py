import numpy as np
import pandas as pd
from scipy import sparse
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    silhouette_score,
)
from sklearn.mixture import GaussianMixture

from run_baseline import ROOT
from run_dynamic_model import (
    SENSITIVITY,
    fit_model,
    load_config,
    prepare_monthly,
    representations,
    scaled_monthly,
)
from run_graph_model import modularity, transport_graph


REFERENCE = ROOT / "artifacts" / "dynamic" / "monthly_clusters.csv"
MONTHLY_OUTPUT = ROOT / "artifacts" / "comparison" / "monthly_metrics.csv"
SUMMARY_OUTPUT = ROOT / "artifacts" / "comparison" / "model_summary.csv"
REPORT = ROOT / "reports" / "model_comparison.md"


def s_dbw(attributes: np.ndarray, labels: np.ndarray) -> float:
    clusters = np.unique(labels)
    variances = [np.var(attributes[labels == label], axis=0) for label in clusters]
    total_variance = np.linalg.norm(np.var(attributes, axis=0))
    if total_variance == 0:
        raise ValueError("S_Dbw не определён для выборки с нулевой дисперсией")

    scatter = np.mean(
        [np.linalg.norm(variance) / total_variance for variance in variances]
    )
    radius = np.sqrt(sum(np.linalg.norm(variance) for variance in variances)) / len(
        clusters
    )
    centers = [attributes[labels == label].mean(axis=0) for label in clusters]
    densities = [
        np.count_nonzero(
            np.linalg.norm(attributes[labels == label] - center, axis=1) <= radius
        )
        for label, center in zip(clusters, centers)
    ]

    between_density = 0.0
    for left in range(len(clusters)):
        for right in range(len(clusters)):
            if left == right:
                continue
            pair = attributes[
                (labels == clusters[left]) | (labels == clusters[right])
            ]
            midpoint = (centers[left] + centers[right]) / 2
            density = np.count_nonzero(
                np.linalg.norm(pair - midpoint, axis=1) <= radius
            )
            denominator = max(densities[left], densities[right])
            between_density += density / denominator if denominator else 0

    return float(
        scatter + between_density / (len(clusters) * (len(clusters) - 1))
    )


def network_indices(graph: sparse.csr_matrix, labels: np.ndarray) -> dict[str, float]:
    clusters = np.unique(labels)
    internal = []
    external = []
    for label in clusters:
        members = labels == label
        internal.append(float(graph[members][:, members].sum()))
        external.append(float(graph[members][:, ~members].sum()))

    isolability = [
        inside / (inside + outside) if inside + outside else 0
        for inside, outside in zip(internal, external)
    ]
    unifiability = 0.0
    for left, left_label in enumerate(clusters):
        for right, right_label in enumerate(clusters):
            if left == right:
                continue
            between = float(
                graph[labels == left_label][:, labels == right_label].sum()
            )
            denominator = external[left] + external[right] - between
            unifiability += between / denominator if denominator else 0

    avi = float(np.mean(isolability))
    avu = unifiability / len(clusters)
    return {
        "avi": avi,
        "avu": avu,
        "anui": avi / (1 + avi * avu),
        "mq": float(sum(isolability)),
        "modularity": modularity(graph, labels),
    }


def check_network_indices() -> None:
    graph = sparse.csr_matrix(
        [
            [0, 1, 0, 0],
            [1, 0, 0, 0],
            [0, 0, 0, 1],
            [0, 0, 1, 0],
        ],
        dtype=float,
    )
    result = network_indices(graph, np.array([0, 0, 1, 1]))
    assert np.isclose(result["avi"], 1)
    assert np.isclose(result["avu"], 0)
    assert np.isclose(result["anui"], 1)
    assert np.isclose(result["mq"], 2)
    assert np.isclose(result["modularity"], 0.5)
    attributes = np.array([[-1.0], [-0.8], [0.8], [1.0]])
    assert np.isfinite(s_dbw(attributes, np.array([0, 0, 1, 1])))


def fit_models(
    attributes: np.ndarray,
    static_attributes: np.ndarray,
    dynamic_attributes: np.ndarray,
    config: dict,
) -> dict[str, np.ndarray]:
    gmm = GaussianMixture(
        n_components=config["clusters"],
        covariance_type="diag",
        n_init=10,
        random_state=config["random_state"],
    )
    return {
        "KMeans, признаки": fit_model(attributes, config).labels_,
        "GMM, признаки": gmm.fit_predict(attributes),
        "KMeans, статическая сеть": fit_model(static_attributes, config).labels_,
        "KMeans, динамическая сеть": fit_model(dynamic_attributes, config).labels_,
    }


def calculate_metrics(
    dates: np.ndarray,
    attributes: np.ndarray,
    graphs: list[sparse.csr_matrix],
    models: dict[str, np.ndarray],
    node_count: int,
) -> pd.DataFrame:
    rows = []
    for month, date in enumerate(dates):
        start = month * node_count
        stop = start + node_count
        month_attributes = attributes[start:stop]
        graph = graphs[month]
        for name, all_labels in models.items():
            labels = all_labels[start:stop]
            rows.append(
                {
                    "model": name,
                    "date": date,
                    "sw": silhouette_score(month_attributes, labels),
                    "ch": calinski_harabasz_score(month_attributes, labels),
                    "s_dbw": s_dbw(month_attributes, labels),
                    **network_indices(graph, labels),
                }
            )
    return pd.DataFrame(rows)


def summarize(
    monthly_metrics: pd.DataFrame,
    models: dict[str, np.ndarray],
    node_count: int,
) -> pd.DataFrame:
    summary = monthly_metrics.groupby("model", as_index=False).agg(
        sw=("sw", "mean"),
        ch=("ch", "mean"),
        s_dbw=("s_dbw", "mean"),
        avi=("avi", "mean"),
        avu=("avu", "mean"),
        anui=("anui", "mean"),
        mq=("mq", "mean"),
        modularity=("modularity", "mean"),
    )
    temporal_rows = []
    for name, labels in models.items():
        monthly_labels = labels.reshape(-1, node_count)
        temporal_rows.append(
            {
                "model": name,
                "temporal_ari": np.mean(
                    [
                        adjusted_rand_score(left, right)
                        for left, right in zip(
                            monthly_labels[:-1], monthly_labels[1:]
                        )
                    ]
                ),
                "assignment_stability": np.mean(
                    monthly_labels[:-1] == monthly_labels[1:]
                ),
            }
        )
    result = summary.merge(pd.DataFrame(temporal_rows), on="model")
    return result.set_index("model").loc[list(models)].reset_index()


def format_table(frame: pd.DataFrame) -> str:
    result = frame.copy()
    for column in ["sw", "s_dbw", "avi", "avu", "anui", "mq", "modularity"]:
        result[column] = result[column].map("{:.4f}".format)
    result["ch"] = result["ch"].map("{:.0f}".format)
    for column in ["temporal_ari", "assignment_stability"]:
        result[column] = result[column].map("{:.1%}".format)
    return result.to_string(index=False)


def main() -> None:
    check_network_indices()
    config = load_config()
    monthly, _ = prepare_monthly()
    attributes = scaled_monthly(monthly)
    territory_ids = sorted(map(int, monthly["territory_id"].unique()))
    node_count = len(territory_ids)

    highway, _ = transport_graph(
        territory_ids, "highway", config["highway_neighbors"]
    )
    railway, _ = transport_graph(
        territory_ids, "railway", config["railway_neighbors"]
    )
    transport = (highway + config["rail_weight"] * railway).tocsr()
    sensitivity = pd.read_csv(SENSITIVITY)
    eligible = sensitivity[
        sensitivity["month_to_month_stability"].ge(0.95)
        & sensitivity["min_monthly_cluster_share"].ge(0.15)
    ]
    bandwidth = float(
        eligible.loc[eligible["silhouette"].idxmax(), "economic_bandwidth"]
    )
    static_attributes, dynamic_attributes, graphs = representations(
        attributes,
        transport,
        node_count,
        config["neighbor_mix"],
        bandwidth,
    )
    models = fit_models(attributes, static_attributes, dynamic_attributes, config)

    reference = pd.read_csv(REFERENCE).sort_values(["date", "territory_id"])
    expected_keys = reference[["date", "territory_id"]].to_numpy()
    actual_keys = monthly[["date", "territory_id"]].to_numpy()
    if not np.array_equal(expected_keys, actual_keys):
        raise SystemExit("Динамический результат не соответствует текущей выборке")
    dynamic_ari = adjusted_rand_score(
        reference["cluster"], models["KMeans, динамическая сеть"]
    )
    if not np.isclose(dynamic_ari, 1):
        raise SystemExit("Не удалось воспроизвести динамическую модель")

    metrics = calculate_metrics(
        monthly["date"].unique(), attributes, graphs, models, node_count
    )
    summary = summarize(metrics, models, node_count)
    MONTHLY_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    metrics.to_csv(MONTHLY_OUTPUT, index=False, float_format="%.6f")
    summary.to_csv(SUMMARY_OUTPUT, index=False, float_format="%.6f")

    best = {
        "SW": summary.loc[summary["sw"].idxmax(), "model"],
        "CH": summary.loc[summary["ch"].idxmax(), "model"],
        "S_Dbw": summary.loc[summary["s_dbw"].idxmin(), "model"],
        "AVI": summary.loc[summary["avi"].idxmax(), "model"],
        "AVU": "ничья: 2/3 при K=3",
        "ANUI": summary.loc[summary["anui"].idxmax(), "model"],
        "MQ": summary.loc[summary["mq"].idxmax(), "model"],
        "модульность": summary.loc[summary["modularity"].idxmax(), "model"],
        "временной ARI": summary.loc[summary["temporal_ari"].idxmax(), "model"],
    }
    winners = pd.Series(best, name="model").rename_axis("metric").reset_index()

    report = f"""# Сравнение методов кластеризации

## Что сравниваем

- KMeans только на экономических признаках;
- диагональную Gaussian Mixture Model как вероятностный baseline;
- KMeans после сглаживания по постоянной транспортной сети;
- KMeans на сети с помесячными весами экономического сходства.

Все методы обучены на одной панели из 24 месяцев, с тремя кластерами и общими во
времени параметрами. Метрики считаются отдельно для каждого месяца и затем
усредняются. Сетевые показатели для всех методов рассчитаны на одном и том же
динамическом графе, поэтому сравнение не даёт сетевой модели собственного более
выгодного графа.

## Результаты

`SW`, `CH`, `AVI`, `ANUI`, `MQ`, модульность и временной ARI нужно максимизировать;
`S_Dbw` и `AVU` — минимизировать.

```text
{format_table(summary)}
```

Лучший метод по каждому показателю:

```text
{winners.to_string(index=False)}
```

Динамическая сеть имеет лучшие `SW` и временной ARI. Статическая сеть лидирует по
изолируемости, `ANUI` и `MQ`. GMM показывает минимальный `S_Dbw` и максимальную
модульность, но заметно уступает по silhouette. Атрибутивный KMeans имеет лучший
`CH`. Таким образом, ни один метод не доминирует во всех пространствах.

## Выбор финальной модели

Единого среднего балла не рассчитываем: `ANUI` уже объединяет `AVI` и `AVU`, а при
фиксированном K показатель `MQ` пропорционален `AVI`. При `K=3` на неориентированном
графе `AVU` равен `2/3` для любой трёхчастной разбивки с ненулевыми внешними
связями. Их повторный учёт создал бы искусственный перевес сетевых метрик.

Финальным остаётся KMeans на динамической экономической сети. Он имеет лучшие
silhouette и временной ARI, остаётся близок к статической модели по сетевым метрикам
и напрямую решает конкурсную задачу последовательности атрибутированных графов.
Выбор не означает победу по каждой метрике: расхождения между пространством
признаков, сетью и временной устойчивостью нужно показывать, а не скрывать
агрегированным рейтингом.

## Определения и ограничения

- `S_Dbw` складывает относительный разброс кластеров и плотность между их центрами;
- `AVI` усредняет долю внутреннего веса среди рёбер, инцидентных кластеру;
- `AVU` измеряет склонность пар кластеров к объединению через общий внешний вес;
- `ANUI = AVI / (1 + AVI × AVU)`;
- `MQ` — сумма кластерных факторов Mancoridis, для трёх кластеров `MQ = 3 × AVI`;
- модульность — взвешенный показатель Ньюмана относительно конфигурационной модели;
- все индексы внутренние: они оценивают геометрию и сеть, но не доказывают
  экономическую истинность названий типов.

Формулы сверены с обзором индексов для атрибутированных сетей:
https://doi.org/10.1134/S1064562425700589 и исходной работой по AVI/AVU:
https://doi.org/10.1016/j.eswa.2016.11.011.

Следующий этап — содержательная и географическая интерпретация финальных типов,
переходов и пограничных муниципалитетов.
"""
    REPORT.write_text(report, encoding="utf-8")
    print(f"Помесячные метрики: {MONTHLY_OUTPUT.relative_to(ROOT)}")
    print(f"Сводка: {SUMMARY_OUTPUT.relative_to(ROOT)}")
    print(f"Отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
