import hashlib
import json
import math
import re
from pathlib import Path

import pandas as pd

from build_oktmo_crosswalk import ROOT, source_rows
from read_xlsx import read_sheet


RAW = ROOT / "data/raw/rosstat"
YEARS = (2023, 2024)
METRICS = {
    "income": "Доходы и социальные выплаты, тыс. ₽ на жителя за год",
    "housing": "Ввод жилья, м² на жителя за год",
    "investment": "Инвестиции организаций без малого бизнеса, тыс. ₽ на жителя за год",
}
FILES = ("urov_2023_2024.xlsx", "data_section3.parquet", "data_section9.parquet")
STATUS = {
    "ok": "Включено",
    "missing": "Нет наблюдения",
    "conflict": "Разные значения для одного кода и года",
    "boundary_review": "В истории ОКТМО есть объединение, присоединение или выделение",
    "no_population": "Нет однозначного населения",
    "geography_review": "Ввод жилья во внутригородских территориях требует проверки географии",
    "value_review": "Сарпинский район, 2024: 7,14 млн ₽ на жителя; нужна проверка источника",
    "invalid": "Некорректное значение",
}


def oktmo(value):
    digits = re.sub(r"[\s-]", "", str(value))
    if not digits.isdigit() or len(digits) not in (7, 8, 11):
        raise ValueError(f"Некорректный ОКТМО: {value}")
    return digits[:8] if len(digits) == 11 else digits.zfill(8)


def unique_value(values):
    if not values:
        return None, "missing"
    if any(not math.isfinite(value) or value < 0 for value in values):
        return None, "invalid"
    return (values[0], "ok") if len(set(values)) == 1 else (None, "conflict")


def read_income():
    rows = []
    for year in YEARS:
        for row in read_sheet(RAW / FILES[0], str(year)):
            if len(row) < 4 or not str(row[0] or "").isdigit() or row[2] is None:
                continue
            rows.append({"code": oktmo(row[2]), "year": year, "value": float(row[3])})
    frame = pd.DataFrame(rows)
    assert not frame.duplicated(["code", "year"]).any(), "Повторные коды в таблице доходов"
    return frame


def read_indicator(frame, indicator):
    selected = frame[
        frame.indicator_code.eq(indicator)
        & frame.indicator_period.eq("Значение показателя за год")
        & frame.mun_level.eq("Муниципальное образование верхнего уровня")
    ]
    if indicator == "Y48109001":
        selected = selected[
            selected.istinv.eq("Всего")
            & selected.okved2.eq("Всего по обследуемым видам экономической деятельности")
        ]
    unit = "Тысяча рублей" if indicator == "Y48109001" else "Квадратный метр общей площади"
    assert set(selected.indicator_unit) == {unit}, "Неожиданная единица измерения"
    return selected.rename(columns={"oktmo": "code", "indicator_value": "value"})[["code", "year", "value"]]


def main():
    population = pd.read_csv(ROOT / "artifacts/external/population_annual.csv")
    ids = set(pd.read_csv(ROOT / "artifacts/external/oktmo_crosswalk.csv").territory_id)
    mapping = []
    for row in source_rows():
        if not row["territory_id"] or int(row["territory_id"]) not in ids:
            continue
        for year in YEARS:
            if int(row["year_from"]) <= year < int(row["year_to"]):
                mapping.append({"territory_id": int(row["territory_id"]), "year": year,
                                "code": oktmo(row["oktmo"]), "region": row["region_name"]})
    mapping = pd.DataFrame(mapping)
    assert len(mapping) == len(ids) * 2
    assert not mapping.duplicated(["code", "year"]).any()
    assert not mapping.duplicated(["territory_id", "year"]).any()
    mapping = mapping.merge(population[["territory_id", "year", "population"]],
                            on=["territory_id", "year"], how="left", validate="one_to_one")

    housing = pd.read_parquet(RAW / FILES[1], filters=[("year", "in", YEARS)])
    investment = pd.read_parquet(RAW / FILES[2], filters=[("year", "in", YEARS)])
    assert set(housing.indicator_section) == {"Строительство"}
    history = pd.concat([housing, investment], ignore_index=True)
    boundary_review = set(history.loc[
        history.oktmo_history.str.contains("Объединение|Присоединение|Выделение", na=False), "oktmo"
    ])
    frames = {"income": read_income(), "housing": read_indicator(housing, "Y48010001"),
              "investment": read_indicator(investment, "Y48109001")}
    audit = []
    records = {id: {"id": id, **{key: [None, None] for key in METRICS}} for id in sorted(ids)}
    for metric, frame in frames.items():
        groups = frame.groupby(["code", "year"]).value.agg(list).to_dict()
        for row in mapping.itertuples():
            values = groups.get((row.code, row.year), [])
            value, status = unique_value(values)
            if status == "ok":
                if row.code in boundary_review:
                    status = "boundary_review"
                elif metric == "housing" and row.region in ("Москва", "Санкт-Петербург", "Севастополь"):
                    status = "geography_review"
                elif metric == "income" and row.territory_id == 188 and row.year == 2024:
                    status = "value_review"
                elif not math.isfinite(row.population) or row.population <= 0:
                    status = "no_population"
            if status == "ok":
                records[row.territory_id][metric][row.year - 2023] = round(value / row.population, 6)
            audit.append({"territory_id": row.territory_id, "year": row.year, "oktmo": row.code,
                          "metric": metric, "source_values": " | ".join(map(str, values)),
                          "population": row.population, "status": status})
    audit = pd.DataFrame(audit)
    audit.to_csv(ROOT / "artifacts/external/rosstat_coverage.csv", index=False)
    coverage = {}
    for metric in METRICS:
        data = audit[audit.metric.eq(metric)]
        coverage[metric] = {str(year): data[data.year.eq(year)].status.value_counts().to_dict() for year in YEARS}
        coverage[metric]["both"] = sum(all(v is not None for v in row[metric]) for row in records.values())
    payload = {
        "years": YEARS, "units": METRICS, "coverage": coverage,
        "sources": [{"file": name, "sha256": hashlib.sha256((RAW / name).read_bytes()).hexdigest()} for name in FILES],
        "municipalities": list(records.values()),
    }
    (ROOT / "site/rosstat-data.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
    lines = ["# Росстат: контекст типов", "",
             "Эти показатели не участвуют в обучении кластеров. Они сопоставляются с уже готовыми типами.", "",
             "ОКТМО берётся из версии справочника соответствующего года. Доходы и инвестиции — тыс. рублей за год, жильё — м². Делим на население на 1 января соответствующего года; это не среднегодовое население. Денежные суммы номинальные.", "",
             "Доходы включают социальные выплаты и налогооблагаемые доходы, но не ненаблюдаемый сектор. В инвестициях исключён малый бизнес. В файле data_section3.parquet находится раздел 37 «Строительство».", "",
             "На графиках фиксируется состав территорий с допустимыми значениями за оба года. Пропуски не заменяются нулями. Итоги не складываются с отраслями или источниками финансирования.", "",
             "История объединений в выгрузке не всегда содержит дату события. Такие коды исключены консервативно до проверки границ; это не утверждение, что все они изменились именно в 2023–2024 годах. Внутригородские территории федеральных городов исключены из жилья до проверки географии показателя. Остальные экстремальные значения не обрезаются.", "",
             "| Показатель | 2023 | 2024 | Оба года |", "|---|---:|---:|---:|"]
    for metric, label in METRICS.items():
        counts = coverage[metric]
        lines.append(f"| {label} | {counts['2023'].get('ok', 0)} | {counts['2024'].get('ok', 0)} | {counts['both']} |")
    lines += ["", "## Исключения", "", "Статусы в [полном протоколе](../artifacts/external/rosstat_coverage.csv):", ""]
    lines += [f"- `{key}`: {value}." for key, value in STATUS.items()]
    lines += ["", "Конфликты инвестиций: Жигулёвск, Кинель, Владикавказ. В исходных строках встречается несоответствие типа муниципалитета коду; значения не суммируются и не выбираются произвольно.", "", "## Воспроизведение", "", "`make context` — после подготовки населения и справочника. Исходные файлы находятся в `data/raw/rosstat/`. Контрольные суммы:", ""]
    lines += [f"- `{row['file']}`: `{row['sha256']}`" for row in payload["sources"]]
    (ROOT / "reports/rosstat_context.md").write_text("\n".join(lines) + "\n")
    print("Росстат: общая панель за оба года —", {key: value["both"] for key, value in coverage.items()})


if __name__ == "__main__":
    main()
