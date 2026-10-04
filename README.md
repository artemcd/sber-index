# Экономические архетипы муниципалитетов

Проект для трека «Кластеризация» конкурса СберИндекса. Цель — найти устойчивые типы
локальных экономик и проследить их изменения во времени с помощью атрибутированных
сетей.

Сейчас в репозитории зафиксирован первый этап: проверка исходных данных и выбор
исследовательской выборки. Модельные результаты появятся после проверки baseline.

## Данные

Скачайте и распакуйте в `data/raw`:

- [муниципальные данные конкурса](https://sberbank.com/common/img/uploaded/files/pdf/sberindex/hackathonlicence.zip);
- [справочник и границы муниципалитетов](https://sberindex.ru/ru/research/dataset-borders-and-changes-of-municipalities).

Исходные файлы не входят в Git.

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
