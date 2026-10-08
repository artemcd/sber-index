import json

import pandas as pd

from build_site_data import MUNICIPALITIES, boundary_centers, compact_density, compact_histories, compact_exploration
from run_baseline import ROOT
from run_population_model import ASSIGNMENTS, MATCHED_COMPARISON, POPULATION, SELECTED_K, SENSITIVITY


OUTPUT = ROOT / "site/external-data.json"
NAMES = {
    1: ("Локальная повседневность", "Небольшие, менее урбанизированные территории с расходами ниже медианы."),
    2: ("Городские центры", "Преимущественно городские территории с расходами выше медианы."),
    3: ("Автономные территории", "Расходы выше медианы при сравнительно низкой доступности рынков."),
    4: ("Крупные центры", "Большие городские территории с высокими расходами и доступностью рынков."),
}


def main():
    municipalities = pd.read_csv(MUNICIPALITIES).merge(
        boundary_centers(), on="territory_id", how="left", validate="one_to_one"
    )
    for axis in ("lat", "lon"):
        municipalities[f"municipal_district_center_{axis}"] = municipalities[
            f"municipal_district_center_{axis}"
        ].fillna(municipalities[f"boundary_{axis}"])

    population = pd.read_csv(POPULATION).pivot(
        index="territory_id", columns="year", values=["population", "urban_population"]
    )
    population.columns = [f"{metric}_{year}" for metric, year in population.columns]
    monthly = pd.read_csv(ASSIGNMENTS).sort_values(["territory_id", "date"])
    if monthly.groupby("territory_id").size().ne(24).any():
        raise SystemExit("Внешний режим требует 24 месяца для каждой территории")
    trajectories = monthly.groupby("territory_id")["cluster"].apply(list)
    latest = monthly[monthly["date"] == "2024-12"][["territory_id", "cluster"]]
    frame = municipalities.drop(columns=["cluster", "cluster_name"]).merge(
        latest, on="territory_id", validate="one_to_one"
    ).merge(
        population, on="territory_id", validate="one_to_one"
    )
    if len(frame) != len(trajectories) or frame["cluster"].nunique() != SELECTED_K:
        raise SystemExit("Назначения внешней модели не совпадают со справочником")
    frame["urban_share"] = frame["urban_population_2024"] / frame["population_2024"]
    histories, median = compact_histories(frame.territory_id)

    records = []
    for row in frame.itertuples():
        records.append({
            "id": int(row.territory_id),
            "name": row.municipal_district_name_short,
            "fullName": row.municipal_district_name,
            "region": row.region_name,
            "lat": round(row.municipal_district_center_lat, 5),
            "lon": round(row.municipal_district_center_lon, 5),
            "cluster": int(row.cluster),
            "population": int(row.population_2024),
            "urbanShare": round(row.urban_share, 4),
            "spendIndex": round(row.spend_index, 1),
            "marketAccess": round(row.market_access, 1),
            "trajectory": [int(value) for value in trajectories[row.territory_id]],
            "history": histories[row.territory_id],
        })

    profiles = []
    for cluster, group in frame.groupby("cluster", sort=True):
        name, description = NAMES[cluster]
        profiles.append({
            "id": int(cluster),
            "name": name,
            "description": description,
            "count": len(group),
            "regions": int(group.region_name.nunique()),
            "population": int(group.population_2024.median()),
            "urbanShare": round(float(group.urban_share.median()), 3),
            "spendIndex": round(float(group.spend_index.median()), 1),
            "marketAccess": round(float(group.market_access.median()), 1),
        })

    metrics = pd.read_csv(SENSITIVITY)
    comparison = pd.read_csv(MATCHED_COMPARISON)
    if len(comparison) != 24:
        raise SystemExit("Ожидалось 24 месяца сравнения на общей панели")
    payload = {
        "meta": {"totalMunicipalities": len(municipalities), "municipalities": len(records), "months": 24, "clusters": SELECTED_K},
        "matchedAgreement": {
            "mean": round(comparison.ari_same_panel_same_k.mean(), 3),
            "december": round(comparison.ari_same_panel_same_k.iloc[-1], 3),
        },
        "clusters": profiles,
        "historyMedian": median,
        "exploration": compact_exploration(frame.territory_id),
        "densityComparison": compact_density("СберИндекс + Росстат"),
        "models": [
            {
                "name": row.model,
                "silhouette": round(row.sw_sample, 3),
                "temporalAri": round(row.temporal_ari, 3),
                "modularity": round(row.modularity, 3),
            }
            for row in metrics[metrics.clusters == SELECTED_K].itertuples()
        ],
        "clusterSensitivity": [
            {
                "clusters": int(row.clusters),
                "model": row.model,
                "silhouette": round(row.sw_sample, 4),
                "temporalAri": round(row.temporal_ari, 4),
                "modularity": round(row.modularity, 4),
                "minClusterShare": round(row.min_cluster_share, 4),
            }
            for row in metrics.itertuples()
        ],
        "municipalities": records,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Внешний лендинг: {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size / 1024:.0f} КБ)")


if __name__ == "__main__":
    main()
