import json
import math
from pathlib import Path


SITE = Path(__file__).resolve().parents[1] / "site"


def check(name, html, script):
    page = (SITE / html).read_text()
    assert f'src="{script}' in page, f"{html}: не подключён {script}"
    assert (SITE / script).is_file(), f"нет {script}"
    assert 'src="overview.js' in page and (SITE / "overview.js").is_file(), f"{html}: нет сводного графика"
    assert 'id="overview-chart"' in page and 'id="overview-result"' in page, f"{html}: нет элементов сводки"
    assert all(f'id="{key}"' in page for key in ["studio-chart", "studio-legend", "cohort-chart", "cohort-readout", "story-progress", "atlas", "history-chart", "network-chart", "coverage-chart", "distribution-chart", "calendar-chart", "flows-chart"]), f"{html}: нет элементов исследования"

    data = json.loads((SITE / name).read_text())
    items = data["municipalities"]
    clusters = data["clusters"]
    ids = [item["id"] for item in items]
    assert len(ids) == len(set(ids)) == data["meta"]["municipalities"], f"{name}: неверное число муниципалитетов"
    assert sum(cluster["count"] for cluster in clusters) == len(ids), f"{name}: неверные размеры кластеров"
    assert {cluster["id"] for cluster in clusters} == set(range(1, len(clusters) + 1)), f"{name}: неверные номера кластеров"
    assert all(item["cluster"] in range(1, len(clusters) + 1) for item in items), f"{name}: неизвестный кластер"
    assert all(len(item["trajectory"]) == data["meta"]["months"] for item in items), f"{name}: неполные траектории"
    assert all(len(item["trajectory"]) == 24 for item in items), f"{name}: сайт рассчитан на 24 месяца"
    assert all(set(item["trajectory"]) <= {cluster["id"] for cluster in clusters} for item in items), f"{name}: неизвестный тип в истории"
    assert all(item["trajectory"][-1] == item["cluster"] for item in items), f"{name}: итоговый тип не совпадает с историей"
    assert all(sum(item["trajectory"][-1] == cluster["id"] for item in items) == cluster["count"] for cluster in clusters), f"{name}: сводка не совпадает с карточками типов"
    measures = {"spend", "spendIndex", "health_share", "marketplace_share", "food_service_share", "grocery_share", "transport_share"}
    assert set(data["historyMedian"]) == measures, f"{name}: нет медиан для графика"
    for history in [data["historyMedian"], *[item["history"] for item in items]]:
        assert set(history) == measures, f"{name}: неполные показатели расходов"
        assert all(len(values) == 24 and all(math.isfinite(v) and v >= 0 for v in values) for values in history.values()), f"{name}: неверный ряд расходов"
        assert all(v <= 100 for key, values in history.items() if key.endswith("share") for v in values), f"{name}: доля больше 100%"
    assert all(item["lat"] is not None and item["lon"] is not None for item in items), f"{name}: нет координат"
    coverage = data["exploration"]["coverage"]
    assert len(coverage) == len({id for id, _ in coverage}) == 2190, f"{name}: неверный исходный охват"
    assert all(1 <= months <= 24 for _, months in coverage), f"{name}: неверная полнота рядов"
    complete = {id for id, months in coverage if months == 24}
    assert len(complete) == 2016 and set(ids) <= complete, f"{name}: панель не соответствует полным рядам"
    assert data["exploration"]["networks"], f"{name}: нет примеров сети"
    for network in data["exploration"]["networks"]:
        assert network["center"] in ids and network["edges"], f"{name}: неверный центр сети"
        assert len({edge["id"] for edge in network["edges"]}) == len(network["edges"]), f"{name}: повторяются соседи"
        for edge in network["edges"]:
            assert edge["id"] in ids and edge["id"] != network["center"], f"{name}: неверный сосед"
            assert edge["transport"] > 0 and len(edge["weights"]) == 24, f"{name}: неверный транспортный вес или период"
            assert all(math.isfinite(weight) and 0 <= weight <= edge["transport"] + 1e-6 for weight in edge["weights"]), f"{name}: неверный экономический вес"
    density = data["densityComparison"]
    assert {row["name"] for row in density} == {"KMeans, все", "KMeans, назначенные HDBSCAN", "HDBSCAN"}, f"{name}: неполное сравнение HDBSCAN"
    assert all(0 < row["coverage"] <= 1 for row in density), f"{name}: неверный охват модели"
    print(f"{html}: {len(items)} муниципалитетов, {len(clusters)} кластеров, 24 месяца — OK")
    return data


base = check("data.json", "index.html", "app.js")
external = check("external-data.json", "external.html", "external.js")
assert external["meta"]["totalMunicipalities"] == base["meta"]["municipalities"]

context = json.loads((SITE / "rosstat-data.json").read_text())
assert context["years"] == [2023, 2024]
assert {row["id"] for row in context["municipalities"]} == {row["id"] for row in base["municipalities"]}
assert len(context["municipalities"]) == len(base["municipalities"])
for metric in ("income", "housing", "investment"):
    for row in context["municipalities"]:
        assert len(row[metric]) == 2
        assert all(v is None or (math.isfinite(v) and v >= 0) for v in row[metric])
    assert sum(all(v is not None for v in row[metric]) for row in context["municipalities"]) == context["coverage"][metric]["both"]
for name in ("index.html", "external.html"):
    page = (SITE / name).read_text()
    assert 'src="rosstat.js' in page
    assert all(f'id="{metric}-chart"' in page for metric in ("income", "housing", "investment"))
    assert page.index('id="data-details"') < page.index('id="data"') < page.index('id="income"') < page.index('id="basket"')
print("Росстат: значения, охват и порядок разделов — OK")
