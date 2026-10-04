from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.metrics import (
    adjusted_rand_score,
    calinski_harabasz_score,
    davies_bouldin_score,
    silhouette_score,
)
from sklearn.preprocessing import StandardScaler


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "raw" / "hackathon" / "hackathonlicence"
OUTPUT = ROOT / "artifacts" / "baseline" / "annual_clusters.csv"
REPORT = ROOT / "reports" / "clustering_baseline.md"

CATEGORIES = {
    "Здоровье": "health_share",
    "Маркетплейсы": "marketplace_share",
    "Общественное питание": "food_service_share",
    "Продовольствие": "grocery_share",
    "Транспорт": "transport_share",
}
FEATURES = ["relative_spend", *CATEGORIES.values(), "log_market_access"]
CLUSTER_NAMES = {
    1: "Цифровая повседневность",
    2: "Автономные локальные центры",
    3: "Крупные центры",
}


def load_monthly_features() -> tuple[pd.DataFrame, pd.DataFrame]:
    consumption = pd.read_parquet(DATA / "consumption.parquet")
    market = pd.read_parquet(DATA / "market_access.parquet")

    observed_months = consumption.groupby("territory_id")["date"].nunique()
    complete_ids = observed_months[observed_months.eq(24)].index
    consumption = consumption[consumption["territory_id"].isin(complete_ids)].copy()
    consumption["year"] = consumption["date"].astype(str).str[:4].astype(int)

    wide = consumption.pivot(
        index=["date", "year", "territory_id"],
        columns="category",
        values="value",
    ).reset_index()
    monthly_median = wide.groupby("date")["Все категории"].transform("median")
    wide["relative_spend"] = np.log(wide["Все категории"] / monthly_median)
    for source, target in CATEGORIES.items():
        wide[target] = wide[source] / wide["Все категории"]
    return wide, market


def aggregate_features(
    monthly: pd.DataFrame, market: pd.DataFrame
) -> tuple[pd.DataFrame, list[int]]:
    annual = monthly.groupby(["territory_id", "year"])[
        ["relative_spend", *CATEGORIES.values()]
    ].median().reset_index()
    annual = annual.merge(market, on="territory_id", how="left", validate="many_to_one")
    annual["market_access_imputed"] = annual["market_access"].isna()
    missing_ids = sorted(annual.loc[annual["market_access"].isna(), "territory_id"].unique())
    annual["market_access"] = annual["market_access"].fillna(
        annual["market_access"].median()
    )
    annual["log_market_access"] = np.log(annual["market_access"])

    if len(annual) != 4032:
        raise SystemExit("Изменилась сбалансированная панель")
    if not np.isfinite(annual[FEATURES].to_numpy()).all():
        raise SystemExit("В признаках появились нечисловые значения")
    return annual, missing_ids


def load_features() -> tuple[pd.DataFrame, list[int]]:
    monthly, market = load_monthly_features()
    return aggregate_features(monthly, market)


def fit_baseline(
    annual: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, float, float]:
    model_frame = annual[FEATURES].copy()
    share_columns = list(CATEGORIES.values())
    model_frame[share_columns] -= annual.groupby("year")[share_columns].transform(
        "median"
    )
    scaled = StandardScaler().fit_transform(model_frame)

    metric_rows = []
    for clusters in range(2, 9):
        labels = KMeans(n_clusters=clusters, n_init=30, random_state=42).fit_predict(
            scaled
        )
        counts = np.bincount(labels)
        metric_rows.append(
            {
                "k": clusters,
                "silhouette": silhouette_score(scaled, labels),
                "calinski_harabasz": calinski_harabasz_score(scaled, labels),
                "davies_bouldin": davies_bouldin_score(scaled, labels),
                "min_cluster_share": counts.min() / len(labels),
            }
        )

    model = KMeans(n_clusters=3, n_init=30, random_state=42)
    raw_labels = model.fit_predict(scaled)
    order = (
        annual.assign(raw_cluster=raw_labels)
        .groupby("raw_cluster")["relative_spend"]
        .median()
        .sort_values()
        .index
    )
    label_map = {raw_label: position for position, raw_label in enumerate(order, 1)}
    annual = annual.copy()
    annual["cluster"] = pd.Series(raw_labels, index=annual.index).map(label_map)
    annual["cluster_name"] = annual["cluster"].map(CLUSTER_NAMES)

    seed_scores = []
    for seed in range(10):
        labels = KMeans(n_clusters=3, n_init=10, random_state=seed).fit_predict(scaled)
        seed_scores.append(adjusted_rand_score(raw_labels, labels))

    observed = ~annual["market_access_imputed"]
    observed_scaled = StandardScaler().fit_transform(model_frame[observed])
    observed_labels = KMeans(n_clusters=3, n_init=30, random_state=42).fit_predict(
        observed_scaled
    )
    access_sensitivity_ari = adjusted_rand_score(raw_labels[observed], observed_labels)
    return annual, pd.DataFrame(metric_rows), min(seed_scores), access_sensitivity_ari


def write_results(
    annual: pd.DataFrame,
    metrics: pd.DataFrame,
    missing_ids: list[int],
    minimum_seed_ari: float,
    access_sensitivity_ari: float,
) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    annual[["territory_id", "year", "cluster", "cluster_name"]].sort_values(
        ["territory_id", "year"]
    ).to_csv(OUTPUT, index=False)

    display_metrics = metrics.copy()
    display_metrics["silhouette"] = display_metrics["silhouette"].map("{:.3f}".format)
    display_metrics["calinski_harabasz"] = display_metrics["calinski_harabasz"].map(
        "{:.0f}".format
    )
    display_metrics["davies_bouldin"] = display_metrics["davies_bouldin"].map(
        "{:.3f}".format
    )
    display_metrics["min_cluster_share"] = display_metrics[
        "min_cluster_share"
    ].map("{:.1%}".format)

    current = annual[annual["year"].eq(2024)]
    profiles = current.groupby(["cluster", "cluster_name"], as_index=False).agg(
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
    for column in CATEGORIES.values():
        profiles[column] = profiles[column].map("{:.1%}".format)

    yearly = annual.pivot(index="territory_id", columns="year", values="cluster")
    stable_share = yearly[2023].eq(yearly[2024]).mean()
    transitions = pd.crosstab(yearly[2023], yearly[2024], normalize="index").mul(100)
    transitions = transitions.reindex(index=range(1, 4), columns=range(1, 4)).fillna(0)
    transitions.index.name = "2023 → 2024"
    transitions.columns = [f"тип {column}" for column in transitions.columns]
    transitions = transitions.reset_index()
    for column in transitions.columns[1:]:
        transitions[column] = transitions[column].map("{:.1f}%".format)

    report = f"""# Baseline кластеризации

## Задача итерации

Построить простой атрибутивный ориентир до добавления транспортной сети. Он нужен,
чтобы следующую, графовую модель сравнивать не с пустым местом, а с измеримым
результатом.

## Выборка и признаки

Использована сбалансированная панель: 2016 муниципалитетов × 2 года. Для каждого
года рассчитаны медианные значения семи признаков:

- расходы относительно медианного муниципалитета того же месяца;
- доли пяти раскрытых категорий в показателе «Все категории»;
- логарифм индекса доступности рынков на 2024 год как постоянный географический
  контекст.

Перед кластеризацией доли категорий центрируются по году. Это убирает общий для
страны сдвиг, например рост маркетплейсов, но сохраняет относительное положение
муниципалитета. Для {len(missing_ids)} МО без индекса доступности использована медиана
выборки: `{', '.join(map(str, missing_ids))}`.
При исключении этих территорий и повторном обучении Adjusted Rand Index равен
**{access_sensitivity_ari:.3f}**.

## Число кластеров

```text
{display_metrics.to_string(index=False)}
```

По внутренним метрикам лучший результат даёт `k=2`, но он сводит картину к грубой
оси «крупные центры — остальные». Для рабочего baseline выбран следующий по качеству
вариант `k=3`: он отделяет территории с низкой доступностью рынков, а самый маленький
кластер содержит больше 20% наблюдений. Выбор частично содержательный и не выдаётся
за чисто статистический оптимум.

Минимальный Adjusted Rand Index относительно основной модели по десяти случайным
инициализациям: **{minimum_seed_ari:.3f}**.

## Профили 2024 года

Названия типов рабочие. Индекс расходов равен 100 для медианного муниципалитета
соответствующего месяца.

```text
{profiles.to_string(index=False)}
```

## Переходы между типами

В одном типе остались **{stable_share:.1%}** муниципалитетов.

```text
{transitions.to_string(index=False)}
```

## Ограничения

- модель пока не использует транспортные связи и не является решением задачи об
  атрибутированной сети;
- годовые медианы скрывают сезонные различия;
- индекс доступности 2024 года одинаков для обоих срезов и не объясняет переходы;
- `k=3` выбрано с учётом интерпретируемости, а не только максимума silhouette;
- назначения 12 муниципалитетов с заполненным индексом доступности нельзя
  интерпретировать наравне с остальными.

Следующая проверка — добавить разреженный транспортный граф и измерить изменение
устойчивости, связности кластеров и содержательных профилей.
"""
    REPORT.write_text(report, encoding="utf-8")


def main() -> None:
    annual, missing_ids = load_features()
    clustered, metrics, minimum_seed_ari, access_sensitivity_ari = fit_baseline(annual)
    write_results(
        clustered,
        metrics,
        missing_ids,
        minimum_seed_ari,
        access_sensitivity_ari,
    )
    print(f"Кластеры: {OUTPUT.relative_to(ROOT)}")
    print(f"Отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
