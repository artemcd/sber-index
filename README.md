# Локальный код

Карта экономических типов муниципалитетов для трека «Кластеризация» конкурса
СберИндекса. Сравниваем расходы и транспортное окружение 2016 территорий
за 24 месяца: январь 2023 — декабрь 2024.

1710 территорий не меняли тип; выделены 215 устойчивых переходов.
Динамическая сеть даёт небольшой выигрыш относительно статической.
Добавлены проверки финальной модели: устойчивость на подвыборках, альтернативная
сеть и связь типов с доходами, жильём и инвестициями. [Результаты](reports/research.md).

- [Открыть карту](https://artemcd.github.io/sber-index/) — карта по месяцам, переходы между типами и графики расходов территорий.

## Посмотреть локально

Готовые данные входят в репозиторий. Нужны Python 3 и `make`.
Из корня проекта:

```bash
make check
make serve
```

Откройте [localhost:8000](http://localhost:8000). Проверка не обучает модель.
Для остановки сервера нажмите Ctrl+C; открытие HTML через `file://` не поддерживается.

## Воспроизвести расчёт

Нужны Python 3.12 или 3.13, `uv` и `make`.

1. Скачайте [архив СберИндекса](https://sberbank.com/common/img/uploaded/files/pdf/sberindex/hackathonlicence.zip) и [границы и справочник муниципалитетов](https://sberindex.ru/ru/research/dataset-borders-and-changes-of-municipalities). Файлы Росстата за 2023 и 2024 годы уже входят в репозиторий; [источники и контрольные суммы](data/raw/rosstat/SOURCES.md).
2. Распакуйте ZIP и RAR любым архиватором. Разместите файлы СберИндекса так (архивы тоже сохраните):

```text
data/raw/
  hackathonlicence.zip
  municipal_boundaries.rar
  municipal_metadata.pdf
  hackathon/hackathonlicence/
    consumption.parquet
    market_access.parquet
    connection.parquet
  boundaries/
    t_dict_municipal_districts.xlsx
    t_dict_municipal_districts_poly.gpkg
```

3. Запустите из корня проекта:

```bash
uv sync --locked
make all
```

Расчёт работает на CPU: проверяет данные, обучает и сравнивает модели, собирает
обе карты и все исследовательские проверки. Он перезаписывает результаты в `artifacts/`, `reports/` и `site/`.
Исходные данные СберИндекса и границ не входят в Git. Полный расчёт проверен на macOS с Python 3.13.

## Метод и ограничения

Муниципалитеты связаны транспортной близостью; вес связи меняется вместе со
сходством расходов. KMeans выделяет типы, общие для всех месяцев.
Типология описывает прошлые наблюдения и не измеряет благополучие или причины изменений.
В режиме Росстата добавлены население и доля городских жителей; зарплат и занятости нет.
Доходы, строительство и инвестиции показаны отдельно от модели на обеих картах.
`make context` обновляет только эти графики из включённых файлов Росстата;
[правила сопоставления и исключения](reports/rosstat_context.md).

[Методология](reports/dynamic_clustering.md) · [Сравнение моделей и ICVI](reports/model_comparison.md) ·
[Интерпретация](reports/cluster_interpretation.md) · [Росстат](reports/population_extension.md) ·
[Параметры](config/dynamic_model.json) · [Сравнение HDBSCAN](artifacts/comparison/hdbscan_comparison.csv).
`make research` повторяет исследования по готовым данным; входит в `make all`.
`make sensitivity` проверяет [удаление признаков и 24 настройки сети](reports/sensitivity.md).
`make decisions` проверяет [число типов и обнаружение переходов](reports/decision_checks.md).
`make validate` проверяет устойчивость годовой модели и не входит в `make all`.
