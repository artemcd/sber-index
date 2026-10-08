import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score

from run_baseline import (
    CLUSTER_NAMES,
    ROOT,
    aggregate_features,
    load_monthly_features,
)
from run_graph_model import (
    canonical_labels,
    metrics,
    scaled_attributes,
    smooth_attributes,
    transport_graph,
)


REFERENCE = ROOT / "artifacts" / "graph" / "annual_clusters.csv"
OUTPUT = ROOT / "artifacts" / "validation" / "bootstrap_stability.csv"
SENSITIVITY = ROOT / "artifacts" / "validation" / "parameter_sensitivity.csv"
REPORT = ROOT / "reports" / "model_validation.md"
BOOTSTRAPS = 50
ALPHA = 0.2
RAIL_WEIGHT = 0.25


def fit_model(
    annual: pd.DataFrame,
    highway,
    railway,
    seed: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    attributes = scaled_attributes(annual)
    neighbor_attributes = smooth_attributes(
        attributes, highway, railway, RAIL_WEIGHT
    )
    representation = (1 - ALPHA) * attributes + ALPHA * neighbor_attributes
    raw_labels = KMeans(n_clusters=3, n_init=30, random_state=seed).fit_predict(
        representation
    )
    return canonical_labels(annual, raw_labels), attributes


def align_labels(reference: np.ndarray, labels: np.ndarray) -> np.ndarray:
    table = pd.crosstab(reference, labels).reindex(
        index=range(1, 4), columns=range(1, 4), fill_value=0
    )
    rows, columns = linear_sum_assignment(-table.to_numpy())
    mapping = {columns[index] + 1: rows[index] + 1 for index in range(len(rows))}
    return pd.Series(labels).map(mapping).to_numpy()


def resample_months(monthly: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    parts = []
    for year in (2023, 2024):
        dates = np.sort(monthly.loc[monthly["year"].eq(year), "date"].unique())
        for date in rng.choice(dates, size=len(dates), replace=True):
            parts.append(monthly[monthly["date"].eq(date)])
    return pd.concat(parts, ignore_index=True)


def bootstrap_validation(
    monthly: pd.DataFrame,
    market: pd.DataFrame,
    reference: pd.DataFrame,
    highway,
    railway,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    rng = np.random.default_rng(42)
    reference_labels = reference["graph_cluster"].to_numpy()
    agreements = np.zeros(len(reference), dtype=int)
    rows = []

    for iteration in range(BOOTSTRAPS):
        sampled = resample_months(monthly, rng)
        annual, _ = aggregate_features(sampled, market)
        annual = annual.sort_values(["year", "territory_id"]).reset_index(drop=True)
        labels, _ = fit_model(annual, highway, railway)
        aligned = align_labels(reference_labels, labels)
        agreements += aligned == reference_labels
        rows.append(
            {
                "iteration": iteration + 1,
                "ari": adjusted_rand_score(reference_labels, labels),
                "agreement": np.mean(aligned == reference_labels),
            }
        )

    stability = reference[
        ["territory_id", "year", "graph_cluster", "graph_cluster_name"]
    ].copy()
    stability["bootstrap_agreement"] = agreements / BOOTSTRAPS
    return stability, pd.DataFrame(rows)


def parameter_validation(
    annual: pd.DataFrame,
    territory_ids: list[int],
    reference_labels: np.ndarray,
) -> pd.DataFrame:
    attributes = scaled_attributes(annual)
    rows = []
    for highway_neighbors, railway_neighbors in ((6, 2), (8, 3), (10, 4)):
        highway, _ = transport_graph(
            territory_ids, "highway", highway_neighbors
        )
        railway, _ = transport_graph(
            territory_ids, "railway", railway_neighbors
        )
        graph = highway + RAIL_WEIGHT * railway
        neighbor_attributes = smooth_attributes(
            attributes, highway, railway, RAIL_WEIGHT
        )
        for alpha in (0.1, 0.2, 0.3):
            representation = (1 - alpha) * attributes + alpha * neighbor_attributes
            labels = KMeans(
                n_clusters=3, n_init=30, random_state=42
            ).fit_predict(representation)
            rows.append(
                {
                    "highway_neighbors": highway_neighbors,
                    "railway_neighbors": railway_neighbors,
                    "alpha": alpha,
                    "ari_reference": adjusted_rand_score(reference_labels, labels),
                    **metrics(attributes, labels, graph, len(territory_ids)),
                }
            )
    return pd.DataFrame(rows)


def yearly_validation(
    annual: pd.DataFrame,
    reference: pd.DataFrame,
    highway,
    railway,
) -> tuple[pd.DataFrame, float]:
    rows = []
    labels_by_year = {}
    for year in (2023, 2024):
        frame = annual[annual["year"].eq(year)].reset_index(drop=True)
        labels, attributes = fit_model(frame, highway, railway)
        labels_by_year[year] = labels
        reference_labels = reference.loc[
            reference["year"].eq(year), "graph_cluster"
        ].to_numpy()
        graph = highway + RAIL_WEIGHT * railway
        score = metrics(attributes, labels, graph, len(frame))
        rows.append(
            {
                "year": year,
                "ari_pooled_model": adjusted_rand_score(reference_labels, labels),
                "silhouette": score["silhouette"],
                "modularity": score["modularity"],
                "min_cluster_share": score["min_cluster_share"],
            }
        )
    cross_year_ari = adjusted_rand_score(labels_by_year[2023], labels_by_year[2024])
    return pd.DataFrame(rows), cross_year_ari


def format_table(frame: pd.DataFrame) -> str:
    result = frame.copy()
    for column in [
        "ari_reference",
        "ari_pooled_model",
        "silhouette",
        "modularity",
    ]:
        if column in result:
            result[column] = result[column].map("{:.3f}".format)
    for column in ["temporal_stability", "min_cluster_share"]:
        if column in result:
            result[column] = result[column].map("{:.1%}".format)
    return result.to_string(index=False)


def main() -> None:
    monthly, market = load_monthly_features()
    annual, _ = aggregate_features(monthly, market)
    annual = annual.sort_values(["year", "territory_id"]).reset_index(drop=True)
    territory_ids = sorted(map(int, annual["territory_id"].unique()))
    reference = pd.read_csv(REFERENCE).sort_values(
        ["year", "territory_id"]
    ).reset_index(drop=True)
    if not np.array_equal(
        annual[["territory_id", "year"]].to_numpy(),
        reference[["territory_id", "year"]].to_numpy(),
    ):
        raise SystemExit("Результат графовой модели не соответствует текущей выборке")

    highway, _ = transport_graph(territory_ids, "highway", 8)
    railway, _ = transport_graph(territory_ids, "railway", 3)
    reference_labels = reference["graph_cluster"].to_numpy()
    reproduced, _ = fit_model(annual, highway, railway)
    if not np.array_equal(reproduced, reference_labels):
        raise SystemExit("Не удалось воспроизвести графовую модель")

    stability, bootstrap_runs = bootstrap_validation(
        monthly, market, reference, highway, railway
    )
    sensitivity = parameter_validation(annual, territory_ids, reference_labels)
    yearly, cross_year_ari = yearly_validation(
        annual, reference, highway, railway
    )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    stability.sort_values(["bootstrap_agreement", "territory_id", "year"]).to_csv(
        OUTPUT, index=False
    )
    sensitivity.to_csv(SENSITIVITY, index=False)

    municipal = stability.groupby("territory_id").agg(
        minimum_agreement=("bootstrap_agreement", "min"),
        mean_agreement=("bootstrap_agreement", "mean"),
    )
    unstable_ids = municipal[municipal["minimum_agreement"].lt(0.8)].index.tolist()
    cluster_stability = stability.groupby(
        ["graph_cluster", "graph_cluster_name"], as_index=False
    )["bootstrap_agreement"].agg(
        median="median",
        p10=lambda values: values.quantile(0.1),
        minimum="min",
        unstable_share=lambda values: values.lt(0.8).mean(),
    )
    for column in ["median", "p10", "minimum", "unstable_share"]:
        cluster_stability[column] = cluster_stability[column].map("{:.1%}".format)

    ari_quantiles = bootstrap_runs["ari"].quantile([0.1, 0.5, 0.9])
    agreement_quantiles = bootstrap_runs["agreement"].quantile([0.1, 0.5, 0.9])
    reference_row = sensitivity[
        sensitivity["highway_neighbors"].eq(8)
        & sensitivity["railway_neighbors"].eq(3)
        & sensitivity["alpha"].eq(0.2)
    ].iloc[0]

    report = f"""# Проверка устойчивости годовой сетевой модели

Здесь проверяется годовая модель из `artifacts/graph`, предшествующая финальной
помесячной модели. Эти bootstrap-оценки нельзя переносить на динамическую модель.
Её проверка ширины экономического ядра описана в
[отчёте о динамической кластеризации](dynamic_clustering.md).

## Критерии

Основная модель считается пригодной для интерпретации, если:

- медианный ARI при повторной выборке месяцев не ниже 0.8;
- не менее 90% назначений совпадают с основной моделью в медианном прогоне;
- ARI всех соседних настроек графа не ниже 0.85;
- ARI независимо обученных годовых моделей не ниже 0.8;
- пограничные муниципалитеты отмечены отдельно, а не выдаются за надёжные случаи.

## Bootstrap по месяцам

Для каждого из {BOOTSTRAPS} прогонов месяцы отдельно внутри 2023 и 2024 года
выбирались с возвращением. Транспортный граф и гиперпараметры оставались
фиксированными.

- ARI: 10-й перцентиль **{ari_quantiles.loc[0.1]:.3f}**, медиана
  **{ari_quantiles.loc[0.5]:.3f}**, 90-й перцентиль **{ari_quantiles.loc[0.9]:.3f}**;
- доля совпавших назначений: 10-й перцентиль **{agreement_quantiles.loc[0.1]:.1%}**,
  медиана **{agreement_quantiles.loc[0.5]:.1%}**, 90-й перцентиль
  **{agreement_quantiles.loc[0.9]:.1%}**;
- муниципалитетов с соглашением ниже 80% хотя бы в одном году: **{len(unstable_ids)}**
  ({len(unstable_ids) / municipal.shape[0]:.1%}).

Устойчивость по типам:

```text
{cluster_stability.to_string(index=False)}
```

## Чувствительность к параметрам графа

Основная конфигурация — восемь автодорожных соседей, три железнодорожных и
`alpha=0.2`. Для неё ARI относительно сохранённого результата равен
**{reference_row['ari_reference']:.3f}**.

```text
{format_table(sensitivity)}
```

## Независимое обучение по годам

```text
{format_table(yearly)}
```

ARI между двумя независимо обученными годовыми разбиениями: **{cross_year_ari:.3f}**.
Это более строгая проверка, чем доля переходов в совместно обученной модели.

## Решение

{{decision}}

Полный список назначений и их bootstrap-соглашение сохранён в
`artifacts/validation/bootstrap_stability.csv`. Порог 80% относится к годовым
назначениям. Карта показывает пограничность помесячной модели по доле доминирующего
типа и относительному отрыву; это отдельное правило, описанное в
[интерпретации типов](cluster_interpretation.md).
"""
    passes = (
        ari_quantiles.loc[0.5] >= 0.8
        and agreement_quantiles.loc[0.5] >= 0.9
        and sensitivity["ari_reference"].min() >= 0.85
        and cross_year_ari >= 0.8
    )
    decision = (
        "Модель проходит заданные проверки и может переходить к содержательной\n"
        "интерпретации. Это не внешняя валидация: устойчивость подтверждает\n"
        "повторяемость структуры, но не экономическую истинность названий типов."
        if passes
        else "Модель не проходит хотя бы один критерий. До интерпретации нужно\n"
        "пересмотреть признаки или параметры графа."
    )
    REPORT.write_text(report.format(decision=decision), encoding="utf-8")
    print(f"Стабильность: {OUTPUT.relative_to(ROOT)}")
    print(f"Параметры: {SENSITIVITY.relative_to(ROOT)}")
    print(f"Отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
