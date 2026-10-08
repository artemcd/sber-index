import re
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZipFile

import numpy as np
import pandas as pd
from sklearn.neighbors import NearestNeighbors

from run_baseline import CATEGORIES, CLUSTER_NAMES, ROOT
from run_dynamic_model import prepare_monthly, scaled_monthly


ASSIGNMENTS = ROOT / "artifacts" / "dynamic" / "monthly_clusters.csv"
METADATA = ROOT / "data" / "raw" / "boundaries" / "t_dict_municipal_districts.xlsx"
OUTPUT = ROOT / "artifacts" / "interpretation" / "municipalities.csv"
COMPARABLES = ROOT / "artifacts" / "interpretation" / "comparables.csv"
TRANSITIONS = ROOT / "artifacts" / "interpretation" / "persistent_transitions.csv"
REPORT = ROOT / "reports" / "cluster_interpretation.md"
XML_NAMESPACE = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_metadata(path: Path = METADATA) -> pd.DataFrame:
    with ZipFile(path) as archive:
        shared_root = ElementTree.fromstring(
            archive.read("xl/sharedStrings.xml")
        )
        shared = [
            "".join(item.itertext())
            for item in shared_root.findall("m:si", XML_NAMESPACE)
        ]
        sheet = ElementTree.fromstring(
            archive.read("xl/worksheets/sheet1.xml")
        )

    rows = []
    for row in sheet.findall(".//m:row", XML_NAMESPACE):
        values = {}
        for cell in row.findall("m:c", XML_NAMESPACE):
            value = cell.find("m:v", XML_NAMESPACE)
            if value is None:
                continue
            column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
            raw = value.text
            values[column] = shared[int(raw)] if cell.get("t") == "s" else raw
        rows.append(values)

    headers = rows[0]
    frame = pd.DataFrame(
        [
            {headers[column]: row.get(column) for column in headers}
            for row in rows[1:]
        ]
    )
    numeric = [
        "territory_id",
        "year_from",
        "year_to",
        "municipal_district_center_lat",
        "municipal_district_center_lon",
    ]
    frame[numeric] = frame[numeric].apply(pd.to_numeric, errors="coerce")
    frame = frame.dropna(subset=["territory_id"]).copy()
    frame["territory_id"] = frame["territory_id"].astype(int)
    frame["metadata_active_2024"] = frame["year_from"].le(2024) & frame[
        "year_to"
    ].ge(2024)
    return (
        frame[frame["year_from"].le(2024)]
        .sort_values(["territory_id", "year_from"])
        .drop_duplicates("territory_id", keep="last")
    )


def trailing_run(values: pd.Series) -> int:
    array = values.to_numpy()
    changes = np.flatnonzero(array[::-1] != array[-1])
    return int(changes[0]) if changes.size else len(array)


def check_trailing_run() -> None:
    assert trailing_run(pd.Series([1, 1, 1])) == 3
    assert trailing_run(pd.Series([1, 2, 2])) == 2
    assert trailing_run(pd.Series([1, 2, 1])) == 1


def stability_summary(assignments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for territory_id, frame in assignments.groupby("territory_id", sort=True):
        counts = frame["cluster"].value_counts()
        dominant_cluster = int(counts.index[0])
        dominant_share = counts.iloc[0] / len(frame)
        mean_margin = frame["relative_margin"].mean()
        if dominant_share >= 22 / 24 and mean_margin >= 0.15:
            stability = "ядро типа"
        elif dominant_share < 0.75 or mean_margin < 0.10:
            stability = "пограничный"
        else:
            stability = "устойчивый"
        rows.append(
            {
                "territory_id": territory_id,
                "dominant_cluster": dominant_cluster,
                "dominant_share": dominant_share,
                "mean_margin": mean_margin,
                "minimum_margin": frame["relative_margin"].min(),
                "transition_count": int(frame["cluster"].diff().ne(0).sum() - 1),
                "months_in_current_cluster": trailing_run(frame["cluster"]),
                "stability": stability,
            }
        )
    return pd.DataFrame(rows)


def persistent_transitions(assignments: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for territory_id, frame in assignments.groupby("territory_id", sort=True):
        frame = frame.reset_index(drop=True)
        changes = np.flatnonzero(frame["cluster"].diff().fillna(0).ne(0))
        starts = np.r_[0, changes]
        stops = np.r_[changes, len(frame)]
        runs = [
            {
                "cluster": int(frame.loc[start, "cluster"]),
                "start": int(start),
                "stop": int(stop),
                "months": int(stop - start),
            }
            for start, stop in zip(starts, stops)
        ]
        for previous, current in zip(runs[:-1], runs[1:]):
            if previous["months"] < 3 or current["months"] < 3:
                continue
            first = current["start"]
            rows.append(
                {
                    "territory_id": territory_id,
                    "date": frame.loc[first, "date"],
                    "from_cluster": previous["cluster"],
                    "to_cluster": current["cluster"],
                    "previous_run_months": previous["months"],
                    "new_run_months": current["months"],
                    "new_run_margin": frame.loc[
                        first : min(first + 2, current["stop"] - 1),
                        "relative_margin",
                    ].mean(),
                }
            )
    return pd.DataFrame(rows)


def comparable_municipalities(
    current: pd.DataFrame, attributes: np.ndarray
) -> pd.DataFrame:
    rows = []
    for cluster, frame in current.groupby("cluster"):
        positions = frame.index.to_numpy()
        model = NearestNeighbors(n_neighbors=len(frame)).fit(attributes[positions])
        distances, neighbors = model.kneighbors(attributes[positions])
        for source_position, source_neighbors, source_distances in zip(
            positions, neighbors, distances
        ):
            source = current.loc[source_position]
            selected = []
            fallback = []
            for neighbor, distance in zip(source_neighbors, source_distances):
                peer = current.loc[positions[neighbor]]
                if peer["territory_id"] == source["territory_id"]:
                    continue
                item = (peer, distance)
                if len(fallback) < 3:
                    fallback.append(item)
                if peer["region_name"] != source["region_name"]:
                    selected.append(item)
                    if len(selected) == 3:
                        break
            selected_ids = {peer["territory_id"] for peer, _ in selected}
            for peer, distance in fallback:
                if len(selected) == 3:
                    break
                if peer["territory_id"] not in selected_ids:
                    selected.append((peer, distance))
                    selected_ids.add(peer["territory_id"])
            for rank, (peer, distance) in enumerate(selected, 1):
                rows.append(
                    {
                        "territory_id": source["territory_id"],
                        "comparable_territory_id": peer["territory_id"],
                        "rank": rank,
                        "distance": distance,
                        "comparable_name": peer["municipal_district_name_short"],
                        "comparable_region": peer["region_name"],
                        "cluster": cluster,
                    }
                )
    return pd.DataFrame(rows)


def cluster_profiles(current: pd.DataFrame) -> pd.DataFrame:
    profiles = current.groupby(["cluster", "cluster_name"], as_index=False).agg(
        municipalities=("territory_id", "size"),
        regions=("region_name", "nunique"),
        relative_spend=("relative_spend", "median"),
        market_access=("market_access", "median"),
        health_share=("health_share", "median"),
        marketplace_share=("marketplace_share", "median"),
        food_service_share=("food_service_share", "median"),
        grocery_share=("grocery_share", "median"),
        transport_share=("transport_share", "median"),
    )
    profiles["spend_index"] = np.exp(profiles.pop("relative_spend")) * 100
    national = current[list(CATEGORIES.values())].median()
    for column in CATEGORIES.values():
        profiles[f"{column}_delta_pp"] = 100 * (profiles[column] - national[column])
    return profiles


def regional_concentration(current: pd.DataFrame) -> pd.DataFrame:
    counts = pd.crosstab(current["region_name"], current["cluster"])
    counts = counts.reindex(columns=sorted(CLUSTER_NAMES), fill_value=0)
    totals = counts.sum(axis=1)
    national_share = counts.sum() / counts.to_numpy().sum()
    rows = []
    for cluster in counts:
        concentration = (counts[cluster] / totals) / national_share[cluster]
        for region in concentration[totals.ge(10)].nlargest(3).index:
            rows.append(
                {
                    "cluster": cluster,
                    "cluster_name": CLUSTER_NAMES[cluster],
                    "region_name": region,
                    "municipalities": int(totals[region]),
                    "cluster_municipalities": int(counts.loc[region, cluster]),
                    "location_quotient": concentration[region],
                }
            )
    return pd.DataFrame(rows)


def format_profiles(profiles: pd.DataFrame) -> str:
    result = profiles[
        [
            "cluster",
            "cluster_name",
            "municipalities",
            "regions",
            "spend_index",
            "market_access",
            *[f"{column}_delta_pp" for column in CATEGORIES.values()],
        ]
    ].copy()
    result["spend_index"] = result["spend_index"].map("{:.1f}".format)
    result["market_access"] = result["market_access"].map("{:.1f}".format)
    for column in [f"{name}_delta_pp" for name in CATEGORIES.values()]:
        result[column] = result[column].map("{:+.1f}".format)
    return result.to_string(index=False)


def main() -> None:
    check_trailing_run()
    monthly, missing_market_ids = prepare_monthly()
    attributes = scaled_monthly(monthly)
    assignments = pd.read_csv(ASSIGNMENTS).sort_values(
        ["date", "territory_id"]
    ).reset_index(drop=True)
    keys = ["territory_id", "date"]
    if not np.array_equal(monthly[keys].to_numpy(), assignments[keys].to_numpy()):
        raise SystemExit("Динамические назначения не соответствуют исходной панели")

    metadata = read_metadata()
    metadata_columns = [
        "territory_id",
        "municipal_district_name_short",
        "municipal_district_name",
        "municipal_district_type",
        "municipal_district_center",
        "region_name",
        "municipal_district_center_lat",
        "municipal_district_center_lon",
        "metadata_active_2024",
    ]
    assignments = assignments.merge(
        metadata[metadata_columns], on="territory_id", how="left"
    )
    if assignments["municipal_district_name_short"].isna().any():
        raise SystemExit("Для части панели не найдено название муниципалитета")

    data = monthly.merge(assignments[keys + ["cluster", "cluster_name"]], on=keys)
    summary = stability_summary(assignments)
    current_date = assignments["date"].max()
    current = assignments[assignments["date"].eq(current_date)].copy()
    current = current.merge(summary, on="territory_id", validate="one_to_one")
    current_features = data[data["date"].eq(current_date)][
        ["territory_id", "relative_spend", "market_access", *CATEGORIES.values()]
    ]
    current = current.merge(current_features, on="territory_id", validate="one_to_one")
    current["spend_index"] = np.exp(current["relative_spend"]) * 100
    current["market_access_imputed"] = current["territory_id"].isin(missing_market_ids)

    events = persistent_transitions(assignments)
    event_metadata = current[
        ["territory_id", "municipal_district_name_short", "region_name"]
    ]
    events = events.merge(event_metadata, on="territory_id", how="left")
    events["from_cluster_name"] = events["from_cluster"].map(CLUSTER_NAMES)
    events["to_cluster_name"] = events["to_cluster"].map(CLUSTER_NAMES)
    event_counts = events.groupby("territory_id").size()
    current["persistent_transition_count"] = (
        current["territory_id"].map(event_counts).fillna(0).astype(int)
    )

    current = current.sort_values("territory_id").reset_index(drop=True)
    current_attributes = attributes[monthly["date"].eq(current_date).to_numpy()]
    comparables = comparable_municipalities(current, current_attributes)
    profiles = cluster_profiles(current)
    regions = regional_concentration(current)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    current.to_csv(OUTPUT, index=False, float_format="%.6f")
    comparables.to_csv(COMPARABLES, index=False, float_format="%.6f")
    events.to_csv(TRANSITIONS, index=False, float_format="%.6f")

    stability = current["stability"].value_counts().reindex(
        ["ядро типа", "устойчивый", "пограничный"], fill_value=0
    )
    transition_directions = (
        events.groupby(["from_cluster_name", "to_cluster_name"])
        .size()
        .rename("transitions")
        .sort_values(ascending=False)
        .reset_index()
    )
    examples = events[events["new_run_months"].ge(6)].sort_values(
        ["new_run_margin", "new_run_months"], ascending=False
    ).head(12)[
        [
            "municipal_district_name_short",
            "region_name",
            "date",
            "from_cluster_name",
            "to_cluster_name",
            "new_run_months",
            "new_run_margin",
        ]
    ].copy()
    examples["new_run_margin"] = examples["new_run_margin"].map("{:.3f}".format)
    regions_display = regions.copy()
    regions_display["location_quotient"] = regions_display[
        "location_quotient"
    ].map("{:.2f}".format)

    report = f"""# Интерпретация экономических типов

## Данные для интерпретации

Для всех {len(current)} муниципалитетов добавлены официальные названия, регионы и
типы из справочника границ. Действующая запись 2024 года найдена для
{int(current['metadata_active_2024'].sum())} МО, координаты центров — для
{int(current['municipal_district_center_lat'].notna().sum())}. Срез профилей —
{current_date}.

Названия кластеров описывают структуру безналичных расходов и транспортный контекст,
а не административный статус или уровень развития территории.

## Экономические профили

Индекс расходов равен 100 для медианного муниципалитета соответствующего месяца,
доступность рынков показана исходным индексом. Пять показателей с суффиксом
`delta_pp` — отклонения долей категорий от медианы по стране в процентных пунктах.

```text
{format_profiles(profiles)}
```

**Цифровая повседневность.** Ниже медианы по общему уровню расходов, выше доля
маркетплейсов и продовольствия, ниже доли общепита и транспорта. Название отражает
не «цифровую зрелость», а заметную роль дистанционных покупок в повседневной корзине.

**Автономные локальные центры.** Расходы выше медианы, при этом значение индекса
доступности рынков самое низкое среди трёх типов. Категориальный профиль занимает
промежуточное положение между первым и третьим типами.

**Крупные центры.** Самый высокий уровень расходов и индекс доступности рынков,
повышенные доли общепита, транспорта и здоровья, сниженная доля продовольствия.
Это потребительский профиль центра притяжения, а не формальная категория города.

## География

Коэффициент локализации больше единицы означает, что тип встречается в регионе
чаще, чем в стране. Показаны только регионы минимум с десятью МО из панели.

```text
{regions_display.to_string(index=False)}
```

## Устойчивость и переходы

- ядро типа: {stability['ядро типа']} МО ({stability['ядро типа'] / len(current):.1%});
- устойчивые: {stability['устойчивый']} МО ({stability['устойчивый'] / len(current):.1%});
- пограничные: {stability['пограничный']} МО ({stability['пограничный'] / len(current):.1%}).

Ядро проводит в одном типе не менее 22 из 24 месяцев и имеет средний относительный
отрыв от второго центра не меньше 0.15. Пограничным считается МО с доминирующим
типом менее чем в 75% месяцев или средним отрывом меньше 0.10.
Показатель `months_in_current_cluster` считает только непрерывную серию в конце
наблюдений; более ранние пребывания в том же типе в него не входят.

Помесячных смен типа: {int(current['transition_count'].sum())}. Из них выделено
{len(events)} устойчивых переходов назначений, где предыдущий и новый режим держались
минимум по три месяца. Остальные смены нельзя уверенно отличить от колебаний около
границы кластеров. Фильтр не доказывает экономическое событие; его ложные
сигналы и пропуски проверены на синтетике в [отдельном отчёте](decision_checks.md).

```text
{transition_directions.to_string(index=False)}
```

Примеры переходов с новым режимом не менее шести месяцев и наибольшим отрывом от
второго кластера в первые три месяца:

```text
{examples.to_string(index=False)}
```

## Сопоставимые территории

Для каждого МО подобраны три ближайших экономических профиля того же типа. Сначала
берутся территории из других регионов, затем при необходимости — из своего. Это
не рейтинг и не причинный аналог, а отправная точка для сопоставления практик.

## Ограничения

- типология основана на расходах, доступности рынков и транспортных связях; без
  населения, доходов и отраслевой структуры нельзя делать выводы о благополучии;
- индекс доступности статичен, а для {len(missing_market_ids)} МО заполнен медианой;
- региональная концентрация описательна и не учитывает разные размеры населения;
- переход считается содержательным по правилу трёх месяцев, но не доказывает
  структурный экономический сдвиг без внешних данных.

Результаты представлены на [интерактивной карте](https://artemcd.github.io/sber-index/):
карта, динамика типов, примеры переходов и паспорт муниципалитета с сопоставимыми
территориями.
"""
    REPORT.write_text(report, encoding="utf-8")
    print(f"Муниципалитеты: {OUTPUT.relative_to(ROOT)}")
    print(f"Аналоги: {COMPARABLES.relative_to(ROOT)}")
    print(f"Переходы: {TRANSITIONS.relative_to(ROOT)}")
    print(f"Отчёт: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
