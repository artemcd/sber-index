# Экономические архетипы муниципалитетов

Проект для трека «Кластеризация» конкурса СберИндекса. Цель — найти устойчивые типы
локальных экономик и проследить их изменения во времени с помощью атрибутированных
сетей.

В репозитории зафиксированы проверка исходных данных и атрибутивный baseline, с
которым дальше сравнивается кластеризация на транспортной сети.

## Данные

Скачайте и распакуйте в `data/raw`:

- [муниципальные данные конкурса](https://sberbank.com/common/img/uploaded/files/pdf/sberindex/hackathonlicence.zip);
- [справочник и границы муниципалитетов](https://sberindex.ru/ru/research/dataset-borders-and-changes-of-municipalities).

Исходные файлы не входят в Git.

Источник: «Потребительские безналичные расходы», «Индекс доступности рынков» и
«Автодорожные и железнодорожные связи между муниципальными образованиями» —
[СберИндекс](https://sberindex.ru/ru/research/data-sense-opisanie-nabora-dannikh-khakatona-sberindeksa-po-munitsipalnim-dannim),
CC BY-SA 4.0, данные скачаны 4 октября 2026 года.

Ожидаемая структура:

```text
data/raw/
├── hackathonlicence.zip
├── municipal_boundaries.rar
├── municipal_metadata.pdf
├── hackathon/hackathonlicence/*.parquet
└── boundaries/t_dict_municipal_districts_poly.gpkg
```

## Проверка данных

```bash
uv sync
uv run python scripts/audit_data.py
```

Скрипт проверяет схему, пропуски, покрытие муниципалитетов и семантику транспортных
пар. Результат сохраняется в `reports/data_audit.md`.

## Baseline кластеризации

```bash
uv run python scripts/run_baseline.py
```

Скрипт строит годовые признаки, сравнивает разбиения от двух до восьми кластеров и
сохраняет результат в `artifacts/baseline`, а краткий разбор — в
`reports/clustering_baseline.md`.

## Транспортная сеть

```bash
uv run python scripts/run_graph_model.py
```

Скрипт строит разреженный граф ближайших автодорожных и железнодорожных связей,
добавляет к признакам локальный транспортный контекст и сравнивает результат с
атрибутивным baseline. Итоги сохраняются в `artifacts/graph` и
`reports/graph_clustering.md`.

## Проверка устойчивости

```bash
uv run python scripts/validate_model.py
```

Проверка повторяет обучение на bootstrap-выборках месяцев, соседних параметрах графа
и отдельных годах. Результаты сохраняются в `artifacts/validation` и
`reports/model_validation.md`.

## Динамическая модель

```bash
uv run python scripts/run_dynamic_model.py
```

Финальная модель этой итерации строит 24 помесячных среза сети. Транспорт задаёт
возможные связи, а их веса меняются по экономическому сходству муниципалитетов.
Параметры находятся в `config/dynamic_model.json`, назначения — в
`artifacts/dynamic`, описание метода — в `reports/dynamic_clustering.md`.

## Сравнение методов

```bash
uv run python scripts/compare_models.py
```

Скрипт сравнивает атрибутивные, статическую сетевую и динамическую модели по
признаковым, сетевым и временным метрикам. Результаты находятся в
`artifacts/comparison`, выводы — в `reports/model_comparison.md`.

## Интерпретация типов

```bash
uv run python scripts/interpret_clusters.py
```

Скрипт добавляет названия и регионы муниципалитетов, выделяет устойчивые и
пограничные случаи, длительные переходы и подбирает сопоставимые территории.
Таблицы для лендинга сохраняются в `artifacts/interpretation`, выводы — в
`reports/cluster_interpretation.md`.

## Лендинг

```bash
uv run python scripts/build_site_data.py
uv run python -m http.server 8000 -d site
```

После запуска откройте `http://localhost:8000`. Лендинг работает без сборщика и
внешних сервисов: интерактивная карта, поиск, динамика типа и муниципальные аналоги
загружаются из подготовленного `site/data.json`.
