## 1. Исключения и типы

- [x] 1.1 В `ledger/errors.py` добавить `errors` в `StatementRowError` (необязательный keyword-аргумент, по умолчанию пустой список)
- [x] 1.2 В `ledger/importer.py` добавить поле `raw: str = ""` в `RowError` и поле `transactions: list[Transaction]` (`field(default_factory=list)`) в `ImportResult`

## 2. Суммы «Сферы» (пункт 1)

- [x] 2.1 Заменить разбор суммы `sfera` (`_sfera_amount`) регулярным выражением: знак только для `sfera`, тысячи через пробел/U+00A0, дробь `[.,]\d{1,2}`, смешанные разделители — ошибка
- [x] 2.2 Применить тот же разбор к колонкам `sfera_split` (`_split_cell`)
- [x] 2.3 Проверить, что `1.234` и `1,500` дают ошибку строки, `1 234.56` — `1234.56`

## 3. Служебные строки `sfera_split` (пункт 2)

- [x] 3.1 В `_parse_sfera_split` пропускать строку, если обе ячейки суммы совпадают с беззнаковым нулём (`0+([.,]0{1,2})?`), без `line_no` и без счётчика
- [x] 3.2 Проверить, что `0,00;` и `-0,00;0,00` остаются ошибками строки

## 4. Описание (пункт 3)

- [x] 4.1 Сохранять описание как `" ".join(text.split())` во всех форматах
- [x] 4.2 Оставить `normalize_description` (через `rules.normalize_text`) только для сравнения на дубли; регистр в сохранённом тексте не менять

## 5. Строгий режим (пункт 4)

- [x] 5.1 Переписать `_parse_rows`: собирать все `RowError` без раннего выхода
- [x] 5.2 При `strict=True` и непустых ошибках бросать `StatementRowError(first.message, line_no=first.line_no, errors=errors)` до любой записи

## 6. Исходный текст записи (пункт 7)

- [x] 6.1 Обернуть итератор строк декодированного текста так, чтобы он сохранял физические строки без `\r\n`/`\n`
- [x] 6.2 Для каждой ошибки собирать `raw` из строк от начала записи до `reader.line_num`, соединяя через `\n`
- [x] 6.3 Проверить: BOM не попадает в `raw`, `\r` из Windows-переводов строк не попадает, cp1251 декодируется до сборки `raw`

## 7. Превью и список транзакций (пункты 5, 6 и уточнение Марины Беловой)

- [x] 7.1 Добавить параметр `dry_run: bool = False` в `import_statement`; при `dry_run=True` не вызывать `store.add_many`
- [x] 7.2 В обычном импорте заполнять `ImportResult.transactions` результатом `store.add_many`
- [x] 7.3 В `dry_run` заполнять `ImportResult.transactions` собранными транзакциями с `id=None`, цифры `added`/`duplicates`/`errors` — как при импорте
- [x] 7.4 Проверить, что `dry_run=True, strict=True` с ошибкой бросает `StatementRowError` и не меняет хранилище

## 8. Тесты

- [x] 8.1 Обновить `tests/test_statement_import.py`: кейс `1 234.56` в `test_sfera_invalid_rows_become_row_errors` переносится в валидные суммы
- [x] 8.2 Обновить `tests/test_statement_import.py`: кейс `03.03.2026;Кофе;0,00;0,00` в `test_split_invalid_rows` переносится в служебные строки
- [x] 8.3 Обновить `tests/test_statement_import.py`: `test_stored_description_keeps_internal_spaces` ожидает `Магазин Лента`
- [x] 8.4 Обновить `tests/test_statement_import.py`: `test_strict_mode_is_atomic_on_json_store` дополнить проверкой `errors`
- [x] 8.5 Добавить тесты: смешанные разделители, `0.00;0.00` пропускается, `-0,00;0,00` — ошибка
- [x] 8.6 Добавить тесты: несколько ошибок в строгом режиме (порядок и `line_no` первой)
- [x] 8.7 Добавить тесты: `raw` для многострочной записи, для `\r\n`, для UTF-8 с BOM
- [x] 8.8 Добавить тесты: `dry_run` не меняет байты `JsonFileStore`, совпадает с обычным импортом, `id` равны `None`
- [x] 8.9 Добавить тесты: `ImportResult.transactions` в порядке файла с `id`, без дублей и ошибок
- [x] 8.10 Прогнать `pytest` целиком; старые тесты `tests/test_importer.py`, `test_cli.py`, `test_reports.py` должны проходить без изменений

## 9. Проверка

- [x] 9.1 `openspec validate ledger-74-statement-import-followups --strict`
- [x] 9.2 Убедиться, что `ledger/cli.py` и `ledger/reports.py` не изменены (`git diff --stat`)
