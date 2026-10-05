import hashlib
import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
DATA = RAW / "hackathon" / "hackathonlicence"
BOUNDARIES = RAW / "boundaries" / "t_dict_municipal_districts_poly.gpkg"
REPORT = ROOT / "reports" / "data_audit.md"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require_files(paths: list[Path]) -> None:
    missing = [str(path.relative_to(ROOT)) for path in paths if not path.exists()]
    if missing:
        raise SystemExit("Не найдены исходные файлы:\n- " + "\n- ".join(missing))


def markdown_table(frame: pd.DataFrame) -> str:
    rows = [list(map(str, frame.columns)), *frame.astype(str).values.tolist()]
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]

    def format_row(row: list[str]) -> str:
        cells = (value.ljust(width) for value, width in zip(row, widths, strict=True))
        return "| " + " | ".join(cells) + " |"

    separator = ["-" * width for width in widths]
    return "\n".join([format_row(rows[0]), format_row(separator), *map(format_row, rows[1:])])


def main() -> None:
    consumption_path = DATA / "consumption.parquet"
    market_path = DATA / "market_access.parquet"
    connection_path = DATA / "connection.parquet"
    archives = [
        RAW / "hackathonlicence.zip",
        RAW / "municipal_boundaries.rar",
        RAW / "municipal_metadata.pdf",
    ]
    require_files([consumption_path, market_path, connection_path, BOUNDARIES, *archives])

    consumption = pd.read_parquet(consumption_path)
    market = pd.read_parquet(market_path)
    connection = pd.read_parquet(connection_path)

    expected = {
        "consumption": {"date", "territory_id", "category", "value"},
        "market": {"territory_id", "market_access"},
        "connection": {"territory_id_x", "territory_id_y", "distance", "type"},
    }
    actual = {
        "consumption": set(consumption.columns),
        "market": set(market.columns),
        "connection": set(connection.columns),
    }
    if actual != expected:
        raise SystemExit(f"Неожиданная схема данных: {actual}")

    consumption_duplicates = consumption.duplicated(
        ["date", "territory_id", "category"]
    ).sum()
    market_duplicates = market.duplicated("territory_id").sum()
    if consumption_duplicates or market_duplicates:
        raise SystemExit("Обнаружены дубли в ключах исходных таблиц")
    categories_per_month = consumption.groupby(["date", "territory_id"])[
        "category"
    ].nunique()
    if not categories_per_month.eq(6).all():
        raise SystemExit("Не для каждого наблюдаемого месяца доступны шесть категорий")

    months = consumption.groupby("territory_id")["date"].nunique()
    complete_ids = set(months[months == 24].index)
    category_stats = (
        consumption.groupby("category")
        .agg(
            rows=("value", "size"),
            territories=("territory_id", "nunique"),
            minimum=("value", "min"),
            median=("value", "median"),
            maximum=("value", "max"),
        )
        .reset_index()
    )
    monthly_coverage = consumption.groupby("date")["territory_id"].nunique()

    wide = consumption.pivot(
        index=["date", "territory_id"], columns="category", values="value"
    )
    listed_categories = [column for column in wide if column != "Все категории"]
    listed_share = wide[listed_categories].sum(axis=1) / wide["Все категории"]

    with sqlite3.connect(BOUNDARIES) as database:
        active_ids = {
            int(row[0])
            for row in database.execute(
                """
                select territory_id
                from t_dict_municipal_districts_poly
                where year_from <= 2024 and year_to > 2024
                """
            )
        }

    consumption_ids = set(consumption["territory_id"])
    market_ids = set(market["territory_id"])
    connection_ids = set(connection["territory_id_x"]) | set(
        connection["territory_id_y"]
    )

    pair_rows = []
    for connection_type, frame in connection.groupby("type"):
        canonical = pd.DataFrame(
            {
                "left": frame[["territory_id_x", "territory_id_y"]].min(axis=1),
                "right": frame[["territory_id_x", "territory_id_y"]].max(axis=1),
                "distance": frame["distance"],
            }
        )
        pair_distances = canonical.groupby(["left", "right"])["distance"].agg(
            ["size", "min", "max"]
        )
        duplicate_rows = int((pair_distances["size"] - 1).sum())
        pair_rows.append(
            {
                "type": connection_type,
                "rows": len(frame),
                "nodes": len(set(frame["territory_id_x"]) | set(frame["territory_id_y"])),
                "unique_pairs": len(frame) - duplicate_rows,
                "duplicate_rows": duplicate_rows,
                "conflicting_distance": int(
                    pair_distances["min"].ne(pair_distances["max"]).sum()
                ),
                "zero_distance": int(frame["distance"].eq(0).sum()),
            }
        )
    pair_stats = pd.DataFrame(pair_rows)

    hashes = "\n".join(
        f"- `{path.name}` — `{sha256(path)}`" for path in archives
    )
    category_stats["median"] = category_stats["median"].astype(int)
    category_table = markdown_table(category_stats)
    pair_table = markdown_table(pair_stats)
    railway_stats = pair_stats[pair_stats["type"].eq("railway")].iloc[0]
    highway_stats = pair_stats[pair_stats["type"].eq("highway")].iloc[0]
    month_distribution = ", ".join(
        f"{month_count}: {territory_count}"
        for month_count, territory_count in months.value_counts().sort_index().items()
    )

    report = f"""# Аудит исходных данных

## Решение по выборке

Основная модель строится на сбалансированной панели из **{len(complete_ids)} муниципалитетов**:
для них присутствуют все 24 месяца и все шесть категорий. Остальные
**{consumption['territory_id'].nunique() - len(complete_ids)} муниципалитета** с неполными
рядами в модель не включены. Проверка чувствительности к их включению не выполнена.
Постоянный состав панели позволяет отделить экономические переходы от изменения
состава наблюдаемой выборки.

## Полученные файлы

{hashes}

## Потребительские расходы

- строк: {len(consumption):,};
- период: {consumption['date'].min()} — {consumption['date'].max()};
- муниципалитетов: {consumption['territory_id'].nunique()};
- полных панелей: {len(complete_ids)};
- покрытие по месяцам: от {monthly_coverage.min()} до {monthly_coverage.max()} МО;
- пропусков: {int(consumption.isna().sum().sum())};
- дублей по ключу `(date, territory_id, category)`: {int(consumption_duplicates)};
- неположительных значений: {int(consumption['value'].le(0).sum())}.

Распределение числа наблюдаемых месяцев (`месяцев: муниципалитетов`):
{month_distribution}.

{category_table}

Пять раскрытых категорий составляют медианно **{listed_share.median():.1%}** показателя
«Все категории» (диапазон {listed_share.min():.1%}–{listed_share.max():.1%}). Поэтому
«Все категории» нельзя получать сложением пяти строк.

## Территориальный справочник

- актуальных на 2024 год `territory_id`: {len(active_ids)};
- ID в расходах, но не в актуальном срезе справочника:
  {sorted(consumption_ids - active_ids)};
- актуальных ID без расходов: {len(active_ids - consumption_ids)};
- актуальных ID без индекса доступности рынков: {len(active_ids - market_ids)};
- актуальных ID без любых конкурсных показателей:
  {sorted(active_ids - (consumption_ids | market_ids | connection_ids))}.

ID 1471, 1487 и 1847 присутствуют только в 2023 году и прекратили существование после
муниципальных объединений. Для карты и временных переходов версия территории должна
выбираться по году наблюдения, а не только по состоянию на 2024 год.

## Транспортные связи

{pair_table}

Железнодорожные связи записаны в обе стороны: {railway_stats['duplicate_rows']:,} строк
повторяют уже имеющиеся неориентированные пары. Пар с разными расстояниями: {railway_stats['conflicting_distance']}.
Перед использованием связи нужно привести к
канонической паре `(min(id), max(id))`. В автодорожных данных есть
{highway_stats['zero_distance']} нулевых расстояний, поэтому величина `1 / distance`
не может применяться напрямую.

## Несоответствия документации данным

1. В PDF поле расходов называется `consumption`, в parquet оно называется `value`.
2. PDF утверждает, что транспортная пара хранится один раз, но для железной дороги
   каждая доступная пара представлена в обоих направлениях.
3. В PDF указано 22 муниципалитета без индекса доступности рынков, тогда как
   относительно актуального справочника отсутствуют {len(active_ids - market_ids)}.

Эти расхождения учитываются явно; исходные таблицы не исправляются на месте.
"""

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(report, encoding="utf-8")
    print(f"Отчёт сохранён: {REPORT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
