# Данные Росстата

Эти пять файлов входят в репозиторий. Для `make all` и графиков Росстата скачивать их отдельно не нужно.

| Файл | Источник |
| --- | --- |
| `BUL_MO_2023.xlsx`, `BUL_MO_2024.xlsx` | [Росстат: численность населения по муниципальным образованиям](https://rosstat.gov.ru/compendium/document/13282), на 1 января 2023 и 2024 года. |
| `urov_2023_2024.xlsx` | [Росстат: доходы и социальные выплаты](https://www.rosstat.gov.ru/storage/mediabank/urov_2010-2024.xlsx). Сохранено локальное имя файла. |
| `data_section3.parquet` | [Росстат: БД ПМО, раздел 37 «Строительство жилья»](https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_v20260928/by_section/data_section37_112_v20260928_section_file.zip), выгрузка [«Если быть точным»](https://tochno.st/datasets/bdmo) от 28.09.2026. Локальное имя `data_section3` осталось от первоначальной загрузки; содержимое относится к разделу 37. |
| `data_section9.parquet` | [Росстат: БД ПМО, раздел 9 «Инвестиции в основной капитал»](https://storage.yandexcloud.net/tochno-st-catalog/Rosstat/data_bdmo_118_v20260928/by_section/data_section9_112_v20260928_section_file.zip), та же выгрузка. |

Скрипты используют показатели за 2023 и 2024 годы. Контрольные суммы SHA-256:

```text
9c2ce2e38712e33e357b25fe0a18241cd02eb1505f67be9753079806dd94adda  BUL_MO_2023.xlsx
c831e1b408a6a21e061074f0b3a5a04c2e3bb4f8eabae6c72edff55185e921bd  BUL_MO_2024.xlsx
1fed17ac3389dc990a0f8782b8affdca2f801a2a8ae4da5b23980137a996fa48  urov_2023_2024.xlsx
f5e91dd4c2115684b837e7967e7dc6fbe151ae1bd4c79f090346cf5e61c61252  data_section3.parquet
cec287e730611185cb8e19032c34de4fd99ee9d28fb9d027a7923f94d12c7035  data_section9.parquet
```
