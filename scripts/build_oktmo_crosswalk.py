import csv
from pathlib import Path

from read_xlsx import read_sheet


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/boundaries/t_dict_municipal_districts.xlsx"
MUNICIPALITIES = ROOT / "artifacts/interpretation/municipalities.csv"
OUTPUT = ROOT / "artifacts/external/oktmo_crosswalk.csv"


def source_rows():
    rows = read_sheet(SOURCE, "Sheet1")
    header = next(rows)
    for row in rows:
        yield {
            name: (row[index] if index < len(row) else None) or ""
            for index, name in enumerate(header)
        }


def main():
    with MUNICIPALITIES.open(newline="", encoding="utf-8") as file:
        model_ids = {int(row["territory_id"]) for row in csv.DictReader(file)}

    matches = {}
    for row in source_rows():
        if not row["territory_id"]:
            continue
        territory_id = int(row["territory_id"])
        if territory_id not in model_ids or not int(row["year_from"]) <= 2024 < int(row["year_to"]):
            continue
        if territory_id in matches:
            raise SystemExit(f"Несколько версий территории на 2024 год: {territory_id}")
        oktmo = "".join(character for character in row["oktmo"] if character.isdigit())
        if len(oktmo) != 11:
            raise SystemExit(f"Некорректный ОКТМО для территории {territory_id}: {row['oktmo']}")
        matches[territory_id] = {
            "territory_id": territory_id,
            "oktmo": oktmo,
            "region_name": row["region_name"],
            "municipal_district_name": row["municipal_district_name"],
            "source_rosstat": row["source_rosstat"],
        }

    missing = model_ids - matches.keys()
    if missing:
        raise SystemExit(f"Не найден актуальный ОКТМО для территорий: {sorted(missing)}")
    oktmo_codes = [row["oktmo"] for row in matches.values()]
    if len(set(oktmo_codes)) != len(oktmo_codes):
        raise SystemExit("Один ОКТМО соответствует нескольким территориям модели")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(
            file, fieldnames=next(iter(matches.values())).keys(), lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(matches[territory_id] for territory_id in sorted(matches))
    print(f"ОКТМО: {len(matches)} территорий; {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
