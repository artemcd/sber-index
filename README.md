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
