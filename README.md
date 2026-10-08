# Локальный код

Карта экономических типов муниципалитетов для трека «Кластеризация» конкурса
СберИндекса. Сравниваем расходы и транспортное окружение 2016 территорий
за 24 месяца: январь 2023 — декабрь 2024.

1710 территорий не меняли тип; выделены 215 устойчивых переходов.
Динамическая сеть даёт небольшой выигрыш относительно статической.
Добавлены проверки финальной модели: устойчивость на подвыборках, альтернативная
сеть и связь типов с доходами, жильём и инвестициями. [Результаты](reports/research.md).

- [Открыть карту](https://artemcd.github.io/sber-index/) — карта по месяцам, переходы между типами и графики расходов территорий.
- [Карта с населением Росстата](https://artemcd.github.io/sber-index/external.html) — четыре типа на общей панели из 1923 территорий.

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

1. Скачайте [архив СберИндекса](https://sberbank.com/common/img/uploaded/files/pdf/sberindex/hackathonlicence.zip), [границы и справочник муниципалитетов](https://sberindex.ru/ru/research/dataset-borders-and-changes-of-municipalities) и [население Росстата за 2023 и 2024 годы](https://rosstat.gov.ru/compendium/document/13282).
2. Для дополнительных графиков скачайте три файла в `data/raw/rosstat/`:

| Данные | Подготовка |
| --- | --- |
| [Доходы и социальные выплаты, XLSX](https://www.rosstat.gov.ru/storage/mediabank/urov_2010-2024.xlsx) | Переименуйте в `urov_2023_2024.xlsx`. Сохраните листы `2023` и `2024` без изменений; остальные можно оставить. |
| [Строительство жилья, ZIP](https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_v20260928/by_section/data_section37_112_v20260928_section_file.zip) | Извлеките Parquet и назовите `data_section3.parquet`. Это раздел **37 «Строительство жилья»**, несмотря на имя файла в проекте. |
| [Инвестиции, ZIP](https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_v20260928/by_section/data_section9_112_v20260928_section_file.zip) | Извлеките Parquet и назовите `data_section9.parquet`. |

Выгрузки БД ПМО подготовлены [«Если быть точным»](https://tochno.st/datasets/bdmo) 28.09.2026. Годы 2023 и 2024 код отбирает сам.

3. Распакуйте ZIP и RAR любым архиватором. Разместите файлы так (архивы тоже сохраните):

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
  rosstat/
    BUL_MO_2023.xlsx
    BUL_MO_2024.xlsx
    urov_2023_2024.xlsx
    data_section3.parquet
    data_section9.parquet
```

4. Запустите из корня проекта:

```bash
uv sync --locked
make all
```

Расчёт работает на CPU: проверяет данные, обучает и сравнивает модели, собирает
обе карты и все исследовательские проверки. Он перезаписывает результаты в `artifacts/`, `reports/` и `site/`.
Исходные данные не входят в Git. Полный расчёт проверен на macOS с Python 3.13.

## Метод и ограничения

Муниципалитеты связаны транспортной близостью; вес связи меняется вместе со
сходством расходов. KMeans выделяет типы, общие для всех месяцев.
Типология описывает прошлые наблюдения и не измеряет благополучие или причины изменений.
В режиме Росстата добавлены население и доля городских жителей; зарплат и занятости нет.
Доходы, строительство и инвестиции показаны отдельно от модели на обеих картах.
`make context` обновляет только эти графики из трёх файлов Росстата выше;
[правила сопоставления и исключения](reports/rosstat_context.md).

[Методология](reports/dynamic_clustering.md) · [Сравнение моделей и ICVI](reports/model_comparison.md) ·
[Интерпретация](reports/cluster_interpretation.md) · [Росстат](reports/population_extension.md) ·
[Параметры](config/dynamic_model.json) · [Сравнение HDBSCAN](artifacts/comparison/hdbscan_comparison.csv).
`make research` повторяет исследования по готовым данным; входит в `make all`.
`make sensitivity` проверяет [удаление признаков и 24 настройки сети](reports/sensitivity.md).
`make decisions` проверяет [число типов и обнаружение переходов](reports/decision_checks.md).
`make validate` проверяет устойчивость годовой модели и не входит в `make all`.
