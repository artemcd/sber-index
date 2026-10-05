import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score, silhouette_score

from compare_models import fit_models
from run_baseline import FEATURES, ROOT
from run_dynamic_model import fit_model, load_config, prepare_monthly, representations, scaled_monthly
from run_graph_model import canonical_labels, modularity, transport_graph


POPULATION = ROOT / "artifacts/external/population_annual.csv"
SENSITIVITY = ROOT / "artifacts/external/cluster_count_sensitivity.csv"
ASSIGNMENTS = ROOT / "artifacts/external/monthly_clusters.csv"
MATCHED_COMPARISON = ROOT / "artifacts/external/matched_panel_comparison.csv"
BASE_SENSITIVITY = ROOT / "artifacts/dynamic/bandwidth_sensitivity.csv"
FEATURES_WITH_POPULATION = [*FEATURES, "log_population", "urban_share"]
SELECTED_K = 4


def main():
    config = load_config()
    monthly, _ = prepare_monthly()
    population = pd.read_csv(POPULATION)
    monthly = monthly.merge(
        population, on=["territory_id", "year"], how="inner", validate="many_to_one"
    ).sort_values(["date", "territory_id"]).reset_index(drop=True)
    territory_ids = sorted(map(int, monthly["territory_id"].unique()))
    node_count = len(territory_ids)
    if len(monthly) != node_count * 24 or node_count != len(population) // 2:
        raise SystemExit("Внешняя панель должна содержать 24 месяца для каждой территории")
    monthly["log_population"] = np.log(monthly["population"])
    monthly["urban_share"] = monthly["urban_population"] / monthly["population"]
    attributes = scaled_monthly(monthly, FEATURES_WITH_POPULATION)

    highway, _ = transport_graph(territory_ids, "highway", config["highway_neighbors"])
    railway, _ = transport_graph(territory_ids, "railway", config["railway_neighbors"])
    transport = (highway + config["rail_weight"] * railway).tocsr()
    bandwidth_rows = pd.read_csv(BASE_SENSITIVITY)
    eligible = bandwidth_rows[
        bandwidth_rows["month_to_month_stability"].ge(0.95)
        & bandwidth_rows["min_monthly_cluster_share"].ge(0.15)
    ]
    bandwidth = float(eligible.loc[eligible["silhouette"].idxmax(), "economic_bandwidth"])
    static, dynamic, graphs = representations(
        attributes, transport, node_count, config["neighbor_mix"], bandwidth
    )

    rows = []
    selected_labels = None
    for clusters in config["cluster_counts"]:
        models = fit_models(attributes, static, dynamic, config, clusters)
        for name, labels in models.items():
            monthly_labels = labels.reshape(24, node_count)
            silhouettes = []
            for month, block_labels in enumerate(monthly_labels):
                start = month * node_count
                try:
                    score = silhouette_score(
                        attributes[start : start + node_count],
                        block_labels,
                        sample_size=min(500, node_count),
                        random_state=config["random_state"] + month,
                    )
                except ValueError:
                    score = np.nan
                silhouettes.append(score)
            rows.append({
                "clusters": clusters,
                "model": name,
                "sw_sample": float(np.nanmean(silhouettes)),
                "valid_months": int(np.isfinite(silhouettes).sum()),
                "temporal_ari": float(np.mean([
                    adjusted_rand_score(left, right)
                    for left, right in zip(monthly_labels[:-1], monthly_labels[1:])
                ])),
                "modularity": float(np.mean([
                    modularity(graph, block_labels)
                    for graph, block_labels in zip(graphs, monthly_labels)
                ])),
                "min_cluster_share": min(
                    np.bincount(block_labels, minlength=clusters).min() / node_count
                    for block_labels in monthly_labels
                ),
            })
        if clusters == SELECTED_K:
            selected_labels = models["KMeans, динамическая сеть"]

    SENSITIVITY.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(SENSITIVITY, index=False, float_format="%.6f")

    sber_attributes = scaled_monthly(monthly)
    _, sber_dynamic, _ = representations(
        sber_attributes, transport, node_count, config["neighbor_mix"], bandwidth
    )
    sber_labels = fit_model(
        sber_dynamic, {**config, "clusters": SELECTED_K}
    ).labels_.reshape(24, node_count)
    population_labels = selected_labels.reshape(24, node_count)
    comparison = pd.DataFrame({
        "date": sorted(monthly["date"].unique()),
        "ari_same_panel_same_k": [
            adjusted_rand_score(left, right)
            for left, right in zip(sber_labels, population_labels)
        ],
    })
    comparison.to_csv(MATCHED_COMPARISON, index=False, float_format="%.6f")

    monthly["cluster"] = canonical_labels(monthly, selected_labels)
    monthly[["territory_id", "date", "cluster"]].sort_values(
        ["territory_id", "date"]
    ).to_csv(ASSIGNMENTS, index=False)
    print(f"Внешняя модель: {node_count} территорий, K={SELECTED_K}")
    print(f"Метрики: {SENSITIVITY.relative_to(ROOT)}; назначения: {ASSIGNMENTS.relative_to(ROOT)}")
    print(f"Сопоставимая панель: ARI={comparison['ari_same_panel_same_k'].mean():.3f}")


if __name__ == "__main__":
    main()
