import numpy as np
import pandas as pd
from sklearn.cluster import HDBSCAN
from sklearn.metrics import silhouette_score

from run_baseline import ROOT
from run_dynamic_model import load_config, prepare_monthly, representations, scaled_monthly
from run_graph_model import transport_graph
from run_population_model import FEATURES_WITH_POPULATION, POPULATION


OUTPUT = ROOT / "artifacts/comparison/hdbscan_comparison.csv"
BANDWIDTH = ROOT / "artifacts/dynamic/bandwidth_sensitivity.csv"
ASSIGNMENTS = {
    "СберИндекс": ROOT / "artifacts/dynamic/monthly_clusters.csv",
    "СберИндекс + Росстат": ROOT / "artifacts/external/monthly_clusters.csv",
}


def silhouette(attributes, labels, seed):
    if not 1 < len(np.unique(labels)) < len(labels):
        return np.nan
    return silhouette_score(
        attributes, labels, sample_size=min(500, len(labels)), random_state=seed
    )


def compare(mode, base_monthly, config, bandwidth):
    monthly = base_monthly.copy()
    if mode == "СберИндекс + Росстат":
        monthly = monthly.merge(
            pd.read_csv(POPULATION), on=["territory_id", "year"],
            how="inner", validate="many_to_one"
        ).sort_values(["date", "territory_id"]).reset_index(drop=True)
        monthly["log_population"] = np.log(monthly["population"])
        monthly["urban_share"] = monthly["urban_population"] / monthly["population"]
    ids = sorted(map(int, monthly["territory_id"].unique()))
    count = len(ids)
    if len(monthly) != count * 24:
        raise SystemExit(f"Неполная панель: {mode}")
    if mode == "СберИндекс":
        attributes = scaled_monthly(monthly)
    else:
        attributes = scaled_monthly(monthly, FEATURES_WITH_POPULATION)
    highway, _ = transport_graph(ids, "highway", config["highway_neighbors"])
    railway, _ = transport_graph(ids, "railway", config["railway_neighbors"])
    transport = (highway + config["rail_weight"] * railway).tocsr()
    _, dynamic, _ = representations(
        attributes, transport, count, config["neighbor_mix"], bandwidth
    )
    assignments = pd.read_csv(ASSIGNMENTS[mode]).sort_values(["date", "territory_id"])
    if not np.array_equal(
        assignments[["date", "territory_id"]].to_numpy(),
        monthly[["date", "territory_id"]].to_numpy(),
    ):
        raise SystemExit(f"Назначения и признаки не совпадают: {mode}")

    rows = []
    for month, date in enumerate(sorted(monthly["date"].unique())):
        block = slice(month * count, (month + 1) * count)
        features = attributes[block]
        kmeans = assignments["cluster"].to_numpy()[block]
        density = HDBSCAN(
            min_cluster_size=50, min_samples=10, n_jobs=-1, copy=True
        ).fit_predict(dynamic[block])
        assigned = density >= 0
        seed = config["random_state"] + month
        for name, mask, labels in (
            ("KMeans, все", np.ones(count, dtype=bool), kmeans),
            ("KMeans, назначенные HDBSCAN", assigned, kmeans),
            ("HDBSCAN", assigned, density),
        ):
            rows.append({
                "mode": mode,
                "date": date,
                "model": name,
                "coverage": mask.mean(),
                "clusters": len(np.unique(labels[mask])),
                "silhouette": silhouette(features[mask], labels[mask], seed),
            })
    return pd.DataFrame(rows)


def main():
    config = load_config()
    bandwidths = pd.read_csv(BANDWIDTH)
    eligible = bandwidths[
        bandwidths["month_to_month_stability"].ge(0.95)
        & bandwidths["min_monthly_cluster_share"].ge(0.15)
    ]
    bandwidth = float(eligible.loc[eligible["silhouette"].idxmax(), "economic_bandwidth"])
    monthly, _ = prepare_monthly()
    result = pd.concat(
        [compare(mode, monthly, config, bandwidth) for mode in ASSIGNMENTS],
        ignore_index=True,
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(OUTPUT, index=False, float_format="%.6f")
    print(result.groupby(["mode", "model"], sort=False)[
        ["coverage", "clusters", "silhouette"]
    ].mean().round(3).to_string())


if __name__ == "__main__":
    main()
