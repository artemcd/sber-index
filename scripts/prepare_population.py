import csv
import re
from collections import defaultdict

from build_oktmo_crosswalk import OUTPUT as CROSSWALK, ROOT, source_rows
from read_xlsx import read_sheet


RAW = ROOT / "data/raw/rosstat"
OUTPUT = ROOT / "artifacts/external/population_annual.csv"
COVERAGE = ROOT / "artifacts/external/population_coverage.csv"
REGION_ALIASES = {
    "Архангельская область без Ненецкого автономного округа": "Архангельская область",
    "Кемеровская область - Кузбасс": "Кемеровская область",
    "Тюменская область (кроме Ханты-Мансийского автономного округа - Югры и Ямало-Ненецкого автономного округа)": "Тюменская область",
    "г Москва - город федерального значения": "Москва",
    "г Санкт-Петербург - город федерального значения": "Санкт-Петербург",
}


def normalize(value):
    return re.sub(r"[^а-я0-9]", "", value.lower().replace("ё", "е"))


def population(row, start):
    if len(row) < start + 3:
        return None
    try:
        values = tuple(int(value) for value in row[start : start + 3])
    except (TypeError, ValueError):
        return None
    if min(values) < 0 or values[0] != values[1] + values[2]:
        return None
    return values


def population_2024(crosswalk):
    by_prefix = defaultdict(list)
    for row in read_sheet(RAW / "BUL_MO_2024.xlsx", "Численность_по_МО"):
        if len(row) < 5 or row[0] is None:
            continue
        code = "".join(str(row[0]).split())
        values = population(row, 2)
        if code.isdigit() and len(code) == 10 and values is not None:
            by_prefix[code[:8]].append(values)
    return {
        int(item["territory_id"]): by_prefix[item["oktmo"][:8]]
        for item in crosswalk
    }


def population_2023(crosswalk, names_2024):
    titles = {
        normalize(row[1])
        for row in read_sheet(RAW / "BUL_MO_2023.xlsx", "Перечень_субъектов_РФ")
        if len(row) > 1 and isinstance(row[1], str)
    }
    regions = {title: None for title in titles}
    regions.update({normalize(item["region_name"]): item["region_name"] for item in crosswalk})
    regions.update({normalize(alias): name for alias, name in REGION_ALIASES.items()})

    by_name = defaultdict(list)
    region = None
    for row in read_sheet(RAW / "BUL_MO_2023.xlsx", "Численность_по_МО"):
        if not row or not isinstance(row[0], str):
            continue
        values = population(row, 1)
        if values is None:
            continue
        name = normalize(row[0])
        if name in regions:
            region = regions[name]
        elif region is not None:
            by_name[(region, name)].append(values)

    ids = {int(item["territory_id"]) for item in crosswalk}
    historical = {}
    for row in source_rows():
        if row["territory_id"] and int(row["territory_id"]) in ids:
            territory_id = int(row["territory_id"])
            if int(row["year_from"]) <= 2023 < int(row["year_to"]):
                if territory_id in historical:
                    raise SystemExit(f"Несколько версий территории на 2023 год: {territory_id}")
                historical[territory_id] = row["municipal_district_name"]
    if set(historical) != ids:
        raise SystemExit("Не для всех территорий найдена версия справочника за 2023 год")

    result = {}
    for item in crosswalk:
        territory_id = int(item["territory_id"])
        names = {
            item["municipal_district_name"],
            historical[territory_id],
            *names_2024.get(territory_id, []),
        }
        result[territory_id] = [
            values
            for name in {normalize(name) for name in names}
            for values in by_name[(item["region_name"], name)]
        ]
    return result


def main():
    with CROSSWALK.open(newline="", encoding="utf-8") as file:
        crosswalk = list(csv.DictReader(file))

    names_2024 = defaultdict(list)
    prefixes = {item["oktmo"][:8]: int(item["territory_id"]) for item in crosswalk}
    for row in read_sheet(RAW / "BUL_MO_2024.xlsx", "Численность_по_МО"):
        if len(row) >= 5 and row[0] is not None:
            code = "".join(str(row[0]).split())
            if code.isdigit() and len(code) == 10 and code[:8] in prefixes and isinstance(row[1], str):
                names_2024[prefixes[code[:8]]].append(row[1])

    values_2024 = population_2024(crosswalk)
    values_2023 = population_2023(crosswalk, names_2024)
    complete = []
    coverage = []
    for item in crosswalk:
        territory_id = int(item["territory_id"])
        left = values_2023[territory_id]
        right = values_2024[territory_id]
        coverage.append({
            "territory_id": territory_id,
            "region_name": item["region_name"],
            "municipal_district_name": item["municipal_district_name"],
            "year_2023": "matched" if len(left) == 1 else "missing" if not left else "ambiguous",
            "year_2024": "matched" if len(right) == 1 else "missing" if not right else "ambiguous",
        })
        if len(left) == len(right) == 1:
            for year, values in [(2023, left[0]), (2024, right[0])]:
                complete.append({
                    "territory_id": territory_id,
                    "year": year,
                    "population": values[0],
                    "urban_population": values[1],
                    "rural_population": values[2],
                })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    for path, rows in [(OUTPUT, complete), (COVERAGE, coverage)]:
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0], lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
    print(f"Население за оба года: {len(complete) // 2} из {len(crosswalk)} территорий")
    print(f"Данные: {OUTPUT.relative_to(ROOT)}; покрытие: {COVERAGE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
