import json
from pathlib import Path


SITE = Path(__file__).resolve().parents[1] / "site"


def check(name, html, script):
    page = (SITE / html).read_text()
    assert f'src="{script}' in page, f"{html}: не подключён {script}"
    assert (SITE / script).is_file(), f"нет {script}"

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
    assert all(item["lat"] is not None and item["lon"] is not None for item in items), f"{name}: нет координат"
    density = data["densityComparison"]
    assert {row["name"] for row in density} == {"KMeans, все", "KMeans, назначенные HDBSCAN", "HDBSCAN"}, f"{name}: неполное сравнение HDBSCAN"
    assert all(0 < row["coverage"] <= 1 for row in density), f"{name}: неверный охват модели"
    print(f"{html}: {len(items)} муниципалитетов, {len(clusters)} кластеров, 24 месяца — OK")
    return data


base = check("data.json", "index.html", "app.js")
external = check("external-data.json", "external.html", "external.js")
assert external["meta"]["totalMunicipalities"] == base["meta"]["municipalities"]
