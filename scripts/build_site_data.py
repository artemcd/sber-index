import json
import sqlite3
from pathlib import Path

import pandas as pd

from run_baseline import CLUSTER_NAMES, ROOT


MUNICIPALITIES = ROOT / "artifacts" / "interpretation" / "municipalities.csv"
COMPARABLES = ROOT / "artifacts" / "interpretation" / "comparables.csv"
MONTHLY = ROOT / "artifacts" / "dynamic" / "monthly_clusters.csv"
COMPARISON = ROOT / "artifacts" / "comparison" / "model_summary.csv"
K_SENSITIVITY = ROOT / "artifacts" / "comparison" / "cluster_count_sensitivity.csv"
DENSITY = ROOT / "artifacts" / "comparison" / "hdbscan_comparison.csv"
TRANSITIONS = ROOT / "artifacts" / "interpretation" / "persistent_transitions.csv"
BOUNDARIES = ROOT / "data" / "raw" / "boundaries" / "t_dict_municipal_districts_poly.gpkg"
OUTPUT = ROOT / "site" / "data.json"


def boundary_centers() -> pd.DataFrame:
    query = """
        SELECT
            CAST(p.territory_id AS INTEGER) AS territory_id,
            p.year_from,
            (r.minx + r.maxx) / 2 AS boundary_lon,
            (r.miny + r.maxy) / 2 AS boundary_lat
        FROM t_dict_municipal_districts_poly p
        JOIN rtree_t_dict_municipal_districts_poly_geom r ON p.fid = r.id
        WHERE p.year_from <= 2024 AND p.year_to >= 2024
    """
    with sqlite3.connect(BOUNDARIES) as connection:
        frame = pd.read_sql_query(query, connection)
    return (
        frame.sort_values(["territory_id", "year_from"])
        .drop_duplicates("territory_id", keep="last")
        .drop(columns="year_from")
    )


def cluster_profiles(frame: pd.DataFrame) -> list[dict]:
    profiles = []
    for cluster, group in frame.groupby("cluster", sort=True):
        profiles.append(
            {
                "id": int(cluster),
                "name": CLUSTER_NAMES[cluster],
                "count": len(group),
                "regions": int(group["region_name"].nunique()),
                "spendIndex": round(group["spend_index"].median(), 1),
                "marketAccess": round(group["market_access"].median(), 1),
            }
        )
    return profiles


def compact_models(frame: pd.DataFrame) -> list[dict]:
    return [
        {
            "name": row["model"],
            "silhouette": round(row["sw"], 3),
            "modularity": round(row["modularity"], 3),
            "temporalAri": round(row["temporal_ari"], 3),
        }
        for _, row in frame.iterrows()
    ]


def compact_density(mode: str) -> list[dict]:
    frame = pd.read_csv(DENSITY)
    frame = frame[frame["mode"] == mode]
    if frame.groupby("model").size().ne(24).any() or frame["model"].nunique() != 3:
        raise SystemExit(f"Неполное сравнение HDBSCAN: {mode}")
    return [
        {
            "name": name,
            "coverage": round(group["coverage"].mean(), 3),
            "clusters": round(group["clusters"].mean(), 2),
            "silhouette": round(group["silhouette"].mean(), 3),
        }
        for name, group in frame.groupby("model", sort=False)
    ]


def compact_cluster_sensitivity(frame: pd.DataFrame) -> list[dict]:
    return [
        {
            "clusters": int(row["clusters"]),
            "model": row["model"],
            "silhouette": round(row["sw"], 4),
            "temporalAri": round(row["temporal_ari"], 4),
            "modularity": round(row["modularity"], 4),
            "minClusterShare": round(row["min_cluster_share"], 4),
        }
        for _, row in frame.iterrows()
    ]


def featured_signals(frame: pd.DataFrame) -> list[dict]:
    selected = (
        frame[frame["new_run_months"] >= 6]
        .sort_values(["new_run_margin", "new_run_months"], ascending=False)
        .drop_duplicates("to_cluster")
        .sort_values("to_cluster")
    )
    if len(selected) != 3:
        raise SystemExit("Не найдено по одному устойчивому переходу в каждый тип")

    return [
        {
            "id": int(row["territory_id"]),
            "name": row["municipal_district_name_short"],
            "region": row["region_name"],
            "date": row["date"],
            "fromCluster": int(row["from_cluster"]),
            "fromName": row["from_cluster_name"],
            "toCluster": int(row["to_cluster"]),
            "toName": row["to_cluster_name"],
            "months": int(row["new_run_months"]),
            "margin": round(row["new_run_margin"], 3),
        }
        for _, row in selected.iterrows()
    ]


def main() -> None:
    municipalities = pd.read_csv(MUNICIPALITIES)
    comparables = pd.read_csv(COMPARABLES)
    monthly = pd.read_csv(MONTHLY).sort_values(["territory_id", "date"])
    models = pd.read_csv(COMPARISON)
    cluster_sensitivity = pd.read_csv(K_SENSITIVITY)
    transitions = pd.read_csv(TRANSITIONS)

    municipalities = municipalities.merge(
        boundary_centers(), on="territory_id", how="left", validate="one_to_one"
    )
    municipalities["municipal_district_center_lon"] = municipalities[
        "municipal_district_center_lon"
    ].fillna(municipalities["boundary_lon"])
    municipalities["municipal_district_center_lat"] = municipalities[
        "municipal_district_center_lat"
    ].fillna(municipalities["boundary_lat"])

    if municipalities["territory_id"].nunique() != 2016:
        raise SystemExit("Ожидалось 2016 муниципалитетов")
    if municipalities[
        ["municipal_district_center_lon", "municipal_district_center_lat"]
    ].isna().any(axis=None):
        raise SystemExit("Не для всех муниципалитетов найдены координаты")
    if not monthly.groupby("territory_id").size().eq(24).all():
        raise SystemExit("Ожидалось 24 месяца для каждого муниципалитета")
    if not comparables.groupby("territory_id").size().eq(3).all():
        raise SystemExit("Ожидалось три аналога для каждого муниципалитета")

    trajectories = monthly.groupby("territory_id")["cluster"].apply(list).to_dict()
    peers = {
        territory_id: [
            {
                "id": int(row["comparable_territory_id"]),
                "name": row["comparable_name"],
                "region": row["comparable_region"],
            }
            for _, row in group.sort_values("rank").iterrows()
        ]
        for territory_id, group in comparables.groupby("territory_id")
    }

    records = []
    for _, row in municipalities.sort_values("territory_id").iterrows():
        territory_id = int(row["territory_id"])
        records.append(
            {
                "id": territory_id,
                "name": row["municipal_district_name_short"],
                "fullName": row["municipal_district_name"],
                "region": row["region_name"],
                "lat": round(row["municipal_district_center_lat"], 5),
                "lon": round(row["municipal_district_center_lon"], 5),
                "cluster": int(row["cluster"]),
                "clusterName": row["cluster_name"],
                "stability": row["stability"],
                "monthsCurrent": int(row["months_in_current_cluster"]),
                "spendIndex": round(row["spend_index"], 1),
                "marketAccess": round(row["market_access"], 1),
                "trajectory": [int(value) for value in trajectories[territory_id]],
                "comparables": peers[territory_id],
            }
        )

    dates = sorted(monthly["date"].unique())
    payload = {
        "meta": {
            "municipalities": len(records),
            "months": len(dates),
            "period": [dates[0], dates[-1]],
            "coreShare": round(
                municipalities["stability"].eq("ядро типа").mean(), 3
            ),
            "persistentTransitions": int(
                municipalities["persistent_transition_count"].sum()
            ),
        },
        "clusters": cluster_profiles(municipalities),
        "signals": featured_signals(transitions),
        "models": compact_models(models),
        "densityComparison": compact_density("СберИндекс"),
        "clusterSensitivity": compact_cluster_sensitivity(cluster_sensitivity),
        "municipalities": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Лендинг: {OUTPUT.relative_to(ROOT)} ({OUTPUT.stat().st_size / 1024:.0f} КБ)")


if __name__ == "__main__":
    main()
