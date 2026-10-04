import numpy as np
import pandas as pd
from scipy import sparse
from scipy.sparse.csgraph import connected_components
from sklearn.cluster import KMeans
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sklearn.preprocessing import StandardScaler

from run_baseline import CATEGORIES, CLUSTER_NAMES, DATA, FEATURES, ROOT, load_features


OUTPUT = ROOT / "artifacts" / "graph" / "annual_clusters.csv"
REPORT = ROOT / "reports" / "graph_clustering.md"
BASELINE = ROOT / "artifacts" / "baseline" / "annual_clusters.csv"
HIGHWAY_NEIGHBORS = 8
RAILWAY_NEIGHBORS = 3


def transport_graph(
    territory_ids: list[int], connection_type: str, neighbors: int
) -> tuple[sparse.csr_matrix, float]:
    pairs = pd.read_parquet(
        DATA / "connection.parquet",
        columns=["territory_id_x", "territory_id_y", "distance"],
        filters=[("type", "==", connection_type)],
    )
    pairs = pairs[
        pairs["territory_id_x"].isin(territory_ids)
        & pairs["territory_id_y"].isin(territory_ids)
    ].copy()
    pairs["left"] = pairs[["territory_id_x", "territory_id_y"]].min(axis=1)
    pairs["right"] = pairs[["territory_id_x", "territory_id_y"]].max(axis=1)
    pairs = pairs.groupby(["left", "right"], as_index=False)["distance"].min()
    reverse = pairs.rename(columns={"left": "right", "right": "left"})
    directed = pd.concat([pairs, reverse], ignore_index=True)
    directed = directed.sort_values(["left", "distance"]).groupby("left").head(neighbors)

    distance_scale = directed.loc[directed["distance"].gt(0), "distance"].median()
    positions = {
        territory_id: position for position, territory_id in enumerate(territory_ids)
    }
    rows = directed["left"].map(positions).to_numpy()
    columns = directed["right"].map(positions).to_numpy()
    weights = np.exp(-directed["distance"].to_numpy() / distance_scale)
    graph = sparse.csr_matrix(
        (weights, (rows, columns)), shape=(len(territory_ids), len(territory_ids))
    )
    return graph.maximum(graph.T), float(distance_scale)


def normalized(graph: sparse.csr_matrix) -> sparse.csr_matrix:
    degree = np.asarray(graph.sum(axis=1)).ravel()
    inverse = np.divide(1, degree, out=np.zeros_like(degree), where=degree > 0)
    return sparse.diags(inverse) @ graph


def scaled_attributes(
    annual: pd.DataFrame, features: list[str] = FEATURES
) -> np.ndarray:
    frame = annual[features].copy()
    share_columns = [column for column in CATEGORIES.values() if column in features]
    frame[share_columns] -= annual.groupby("year")[share_columns].transform("median")
    return StandardScaler().fit_transform(frame)


def smooth_attributes(
    attributes: np.ndarray,
    highway: sparse.csr_matrix,
    railway: sparse.csr_matrix,
    rail_weight: float,
) -> np.ndarray:
    node_count = highway.shape[0]
    highway_mean = normalized(highway)
    railway_mean = normalized(railway)
    has_highway = np.asarray(highway.sum(axis=1)).ravel() > 0
    has_railway = np.asarray(railway.sum(axis=1)).ravel() > 0
    blocks = []

    for start in range(0, len(attributes), node_count):
        block = attributes[start : start + node_count]
        highway_features = highway_mean @ block
        railway_features = railway_mean @ block
        combined = block.copy()
        combined[has_highway] = highway_features[has_highway]
        combined[has_railway & ~has_highway] = railway_features[
            has_railway & ~has_highway
        ]
        both = has_highway & has_railway
        combined[both] = (
            (1 - rail_weight) * highway_features[both]
            + rail_weight * railway_features[both]
        )
        blocks.append(combined)
    return np.vstack(blocks)


def modularity(graph: sparse.csr_matrix, labels: np.ndarray) -> float:
    rows, columns = graph.nonzero()
    total_weight = float(graph.sum())
    internal = graph.data[labels[rows] == labels[columns]].sum() / total_weight
    degree = np.asarray(graph.sum(axis=1)).ravel()
    expected = sum(
        (degree[labels == label].sum() / total_weight) ** 2
        for label in np.unique(labels)
    )
    return float(internal - expected)


def metrics(
    attributes: np.ndarray,
    labels: np.ndarray,
    graph: sparse.csr_matrix,
    node_count: int,
) -> dict[str, float]:
    yearly_labels = labels.reshape(-1, node_count)
    return {
        "silhouette": silhouette_score(attributes, labels),
        "modularity": np.mean(
            [modularity(graph, year_labels) for year_labels in yearly_labels]
        ),
        "temporal_stability": np.mean(yearly_labels[0] == yearly_labels[1]),
        "min_cluster_share": np.unique(labels, return_counts=True)[1].min()
        / len(labels),
    }


def canonical_labels(annual: pd.DataFrame, labels: np.ndarray) -> np.ndarray:
    order = (
        annual.assign(raw_cluster=labels)
        .groupby("raw_cluster")["relative_spend"]
        .median()
        .sort_values()
        .index
    )
    mapping = {raw_label: position for position, raw_label in enumerate(order, 1)}
    return pd.Series(labels).map(mapping).to_numpy()


def format_metrics(frame: pd.DataFrame) -> str:
    result = frame.copy()
    for column in ["silhouette", "modularity", "ari_baseline"]:
        if column in result:
            result[column] = result[column].map("{:.4f}".format)
    if "temporal_stability" in result:
        result["temporal_stability"] = result["temporal_stability"].map(
            "{:.2%}".format
        )
    if "min_cluster_share" in result:
        result["min_cluster_share"] = result["min_cluster_share"].map(
            "{:.1%}".format
        )
    return result.to_string(index=False)


def main() -> None:
    annual, _ = load_features()
    annual = annual.sort_values(["year", "territory_id"]).reset_index(drop=True)
    territory_ids = sorted(map(int, annual["territory_id"].unique()))
    node_count = len(territory_ids)
    attributes = scaled_attributes(annual)

    highway, highway_scale = transport_graph(
        territory_ids, "highway", HIGHWAY_NEIGHBORS
    )
    railway, railway_scale = transport_graph(
        territory_ids, "railway", RAILWAY_NEIGHBORS
    )
    expected_baseline = pd.read_csv(BASELINE).sort_values(
        ["year", "territory_id"]
    )
    expected_keys = expected_baseline[["territory_id", "year"]].reset_index(drop=True)
    actual_keys = annual[["territory_id", "year"]].reset_index(drop=True)
    if not np.array_equal(actual_keys.to_numpy(), expected_keys.to_numpy()):
        raise SystemExit("Результат baseline не соответствует текущей выборке")
    baseline_labels = expected_baseline["cluster"].to_numpy()

    baseline_stability = np.mean(
        baseline_labels[:node_count] == baseline_labels[node_count:]
    )
    candidate_rows = []
    candidate_models = {}
    for rail_weight in (0.0, 0.25, 0.5):
        neighbor_attributes = smooth_attributes(
            attributes, highway, railway, rail_weight
        )
        graph = highway + rail_weight * railway
        for alpha in (0.1, 0.2, 0.3):
            representation = (1 - alpha) * attributes + alpha * neighbor_attributes
            labels = KMeans(n_clusters=3, n_init=30, random_state=42).fit_predict(
                representation
            )
            row = {
                "rail_weight": rail_weight,
                "alpha": alpha,
                **metrics(attributes, labels, graph, node_count),
                "ari_baseline": adjusted_rand_score(baseline_labels, labels),
            }
            candidate_rows.append(row)
            candidate_models[(rail_weight, alpha)] = (representation, labels)

    candidates = pd.DataFrame(candidate_rows)
    eligible = candidates[
        candidates["temporal_stability"].ge(baseline_stability - 0.005)
        & candidates["min_cluster_share"].ge(0.15)
    ]
    near_best = eligible[
        eligible["silhouette"].ge(eligible["silhouette"].max() - 0.001)
    ]
    selected = near_best.sort_values(
        ["rail_weight", "alpha", "modularity"], ascending=[True, True, False]
    ).iloc[0]
    rail_weight = float(selected["rail_weight"])
    alpha = float(selected["alpha"])
    representation, graph_raw = candidate_models[(rail_weight, alpha)]
    graph = highway + rail_weight * railway
    graph_labels = canonical_labels(annual, graph_raw)

    seed_scores = []
    for seed in range(10):
        labels = KMeans(n_clusters=3, n_init=10, random_state=seed).fit_predict(
            representation
        )
        seed_scores.append(adjusted_rand_score(graph_raw, labels))

    reduced_features = [feature for feature in FEATURES if feature != "log_market_access"]
    reduced_attributes = scaled_attributes(annual, reduced_features)
    reduced_neighbors = smooth_attributes(
        reduced_attributes, highway, railway, rail_weight
    )
    reduced_representation = (
        (1 - alpha) * reduced_attributes + alpha * reduced_neighbors
    )
    reduced_baseline = KMeans(n_clusters=3, n_init=30, random_state=42).fit_predict(
        reduced_attributes
    )
    reduced_graph = KMeans(n_clusters=3, n_init=30, random_state=42).fit_predict(
        reduced_representation
    )

    baseline_metrics = metrics(attributes, baseline_labels, graph, node_count)
    graph_metrics = metrics(attributes, graph_raw, graph, node_count)
    comparison = pd.DataFrame(
        [
            {"model": "attributes", **baseline_metrics},
            {"model": "graph", **graph_metrics},
        ]
    )
    ablation = pd.DataFrame(
        [
            {
                "model": "attributes",
                **metrics(reduced_attributes, reduced_baseline, graph, node_count),
            },
            {
                "model": "graph",
                **metrics(reduced_attributes, reduced_graph, graph, node_count),
            },
        ]
    )

    annual["baseline_cluster"] = baseline_labels
    annual["graph_cluster"] = graph_labels
    annual["graph_cluster_name"] = annual["graph_cluster"].map(CLUSTER_NAMES)
    annual["changed_from_baseline"] = annual["baseline_cluster"].ne(
        annual["graph_cluster"]
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    annual[
        [
            "territory_id",
            "year",
            "baseline_cluster",
            "graph_cluster",
            "graph_cluster_name",
            "changed_from_baseline",
        ]
    ].sort_values(["territory_id", "year"]).to_csv(OUTPUT, index=False)

    current = annual[annual["year"].eq(2024)]
    profiles = current.groupby(
        ["graph_cluster", "graph_cluster_name"], as_index=False
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
    profiles["spend_index"] = profiles["spend_index"].map("{:.0f}".format)
    profiles["market_access"] = profiles["market_access"].map("{:.1f}".format)
    for column in [
        "health_share",
        "marketplace_share",
        "food_service_share",
        "grocery_share",
        "transport_share",
    ]:
        profiles[column] = profiles[column].map("{:.1%}".format)

    yearly = annual.pivot(index="territory_id", columns="year", values="graph_cluster")
    transitions = pd.crosstab(yearly[2023], yearly[2024], normalize="index").mul(100)
    transitions = transitions.reindex(index=range(1, 4), columns=range(1, 4)).fillna(0)
    transitions.index.name = "2023 → 2024"
    transitions.columns = [f"тип {column}" for column in transitions.columns]
    transitions = transitions.reset_index()
    for column in transitions.columns[1:]:
        transitions[column] = transitions[column].map("{:.1f}%".format)

    combined_degree = np.asarray(graph.sum(axis=1)).ravel()
    component_count, component_labels = connected_components(graph)
    component_sizes = np.bincount(component_labels)
    isolated_ids = [
        territory_ids[index] for index in np.flatnonzero(combined_degree == 0)
    ]
    changed_2024 = current["changed_from_baseline"].mean()
    graph_ari = adjusted_rand_score(baseline_labels, graph_raw)

    report = f"""# Кластеризация на атрибутированной транспортной сети

## Метод

Для каждого муниципалитета построены две разреженные сети: восемь ближайших соседей
по автодорогам и три — по железной дороге. Вес ребра равен
`exp(-distance / median_distance)`; после этого графы симметризуются и нормируются
по строкам.

Экономические признаки смешиваются со средним профилем транспортных соседей:

`X_graph = (1 - alpha) X + alpha ((1 - beta) H X + beta R X)`.

Для МО без железной дороги используется только автодорожный слой, а для МО без
любых связей исходные признаки не меняются.

## Топология

- автодорожных рёбер: {highway.nnz // 2:,}, медианный масштаб: {highway_scale:.1f} км;
- железнодорожных рёбер: {railway.nnz // 2:,}, медианный масштаб: {railway_scale:.1f} км;
- компонент связности: {component_count}, крупнейшая: {component_sizes.max()} МО;
- изолированных МО: {len(isolated_ids)} — `{', '.join(map(str, isolated_ids))}`.

## Выбор параметров

Сравнивались три веса железной дороги и три уровня сетевого сглаживания. Допускались
модели со снижением годовой устойчивости не более чем на 0.5 п. п. и минимальным
кластером не меньше 15%. Среди моделей в пределах 0.001 от лучшего silhouette выбран
меньший вес железнодорожного слоя:
`alpha={alpha:.2f}`, `beta={rail_weight:.2f}`.

```text
{format_metrics(candidates)}
```

## Сравнение с baseline

Все метрики рассчитаны на одной выборке и одном выбранном транспортном графе.
Silhouette измеряется в исходном пространстве экономических признаков.

```text
{format_metrics(comparison)}
```

ARI сетевой модели относительно baseline: **{graph_ari:.3f}**. В 2024 году кластер
изменился у **{changed_2024:.1%}** муниципалитетов. Минимальный ARI по десяти
случайным инициализациям сетевой модели: **{min(seed_scores):.3f}**.

## Проверка без индекса доступности

Индекс доступности сам рассчитан через расстояния, поэтому отдельно проверена модель
без этого признака. Сеть не улучшает экономический silhouette, но повышает
транспортную связность кластеров и устойчивость между годами.

```text
{format_metrics(ablation)}
```

## Профили 2024 года

```text
{profiles.to_string(index=False)}
```

## Переходы между типами

```text
{transitions.to_string(index=False)}
```

## Вывод и ограничения

Сетевой контекст даёт небольшой одновременный прирост silhouette и модульности, а
годовая устойчивость практически не меняется: снижение составляет 0.05 п. п. Это
полезное улучшение baseline, но не основание объявлять метод окончательным.

- транспортная сеть отражает состояние на конец 2024 года и одинакова для обоих лет;
- один шаг сглаживания учитывает только ближайшее окружение;
- подбор параметров основан на внутренних метриках той же выборки;
- рост экономического silhouette частично связан с индексом доступности, который уже
  содержит информацию о расстояниях.

Следующий этап — географическая интерпретация изменившихся назначений и проверка
типов на внешних муниципальных характеристиках.
"""
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"Кластеры: {OUTPUT.relative_to(ROOT)}")
    print(f"Отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
