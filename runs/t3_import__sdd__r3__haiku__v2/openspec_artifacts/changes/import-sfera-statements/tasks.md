## 1. Исключения и заголовок

- [x] 1.1 Добавить `UnknownFormatError` и `StatementRowError` в `ledger/errors.py` (оба наследуют `StatementError`); проверить `issubclass` и что `StatementRowError` несёт `line_no` в тексте сообщения
- [x] 1.2 Реализовать чтение файла: байты целиком, UTF-8 с BOM или без, иначе cp1251; при `OSError` и неудачном декодировании — `StatementError` / `UnknownFormatError` по design.md, решения 5 и 13; проверить тестами на BOM, cp1251 и битый файл
- [x] 1.3 Реализовать `detect_format(path)`: заголовок — строка 1, колонки по `strip().casefold()`, порядок и лишние колонки игнорируются; неоднозначный и пустой заголовок — `UnknownFormatError` с `line_no=1`; проверить сценарии из spec.md (Format detection by header)
- [x] 1.4 Проверить `fmt` (явный): несовпадение заголовка и неизвестное значение `fmt` дают `UnknownFormatError` до любого разбора строк; проверить сценарии из spec.md (Explicit format must match the header)

## 2. Разбор строк

- [x] 2.1 Разбор `nova` через `csv.reader` с разделителем `,`: ISO-дата, `parse_amount`, описание с обрезкой пробелов; `line_no` — физическая строка начала записи; проверить, что существующие тесты `tests/test_importer.py` проходят на этом пути
- [x] 2.2 Разбор `sfera`: дата строго `ДД.ММ.ГГГГ`, сумма по правилам design.md решения 6 (знак, тысячи пробелом и U+00A0, одна или две цифры дроби, точка и дробь длиннее двух знаков — ошибка, нулевая сумма — ошибка); проверить сценарии из spec.md (Sfera amounts and dates) отдельными тестами
- [x] 2.3 Разбор `sfera_split`: суммы без знака, `0,00` равен пустой ячейке, ровно одна ячейка заполнена, знак и обе ячейки — ошибки строки; проверить сценарии из spec.md (Sfera split amounts)
- [x] 2.4 Пропуск мусорных строк (все ячейки пусты после `strip()`) до проверки количества полей; проверить сценарии из spec.md (Junk rows are skipped) и отсутствие «not enough fields» у строк `;;;` и `,,`
- [x] 2.5 Проверить номер строки для многострочной записи в кавычках: `RowError.line_no` равен строке начала записи; проверить сценарий из spec.md (Multi-line quoted record)

## 3. Конвейер импорта

- [x] 3.1 Реализовать `normalize_description(text)` как делегирование к `ledger.rules.normalize_text`, без собственной логики; проверить сценарии из spec.md (Normalized description comparison)
- [x] 3.2 Дедупликация по количеству: счётчик ключей `(date, amount, normalize_description(description))` по `store.all()` до импорта, первые `min(k, n)` строк файла — дубли; проверить сценарии из spec.md (Duplicate detection against the existing store), включая повторный импорт и две одинаковые покупки в одном файле
- [x] 3.3 Режим по умолчанию: собрать `RowError` в `ImportResult.errors` и записать все новые транзакции одним `store.add_many`; проверить сценарии из spec.md (Row errors do not stop a non-strict import)
- [x] 3.4 Строгий режим: первая ошибка бросает `StatementRowError` до любой записи; проверить, что `store.all()` и файл `JsonFileStore` не меняются, сценарии из spec.md (Strict mode is atomic)
- [x] 3.5 Категоризатор вызывается только для добавляемых строк; `imported_at = clock.now()` один раз на импорт; проверить сценарии из spec.md (Categorization and import timestamp)
- [x] 3.6 Собрать `import_statement` и `ImportResult` (`format`, `encoding`, `added`, `duplicates`, `errors`) с сигнатурой из задачи; проверить сценарии из spec.md (Format detection by header) на уровне публичного API

## 4. Совместимость import_csv

- [x] 4.1 Переписать `import_csv` как обёртку: `import_statement(path, store, fmt="nova", strict=True, categorizer=categorizer, clock=clock).added`; сигнатура и `int` прежние; проверить, что `tests/test_importer.py`, `tests/test_cli.py` и остальные существующие тесты проходят без изменений
- [x] 4.2 Проверить сценарии из spec.md (Import_csv compatibility): повторный вызов возвращает 0, плохая строка Nova даёт `StatementRowError` без записи, отсутствующий файл даёт `StatementError`

## 5. Новые тесты и документация

- [x] 5.1 Добавить `tests/test_statement_import.py` с тестами на все сценарии из spec.md, которые ещё не покрыты в 2–4; существующие файлы тестов не менять
- [x] 5.2 Обновить `README.md`: строка про `ledger/importer.py` (импорт трёх форматов), раздел «Формат выписки» с `sfera` и `sfera_split`, правило дедупликации по количеству
- [x] 5.3 Запустить `python -m pytest -q` и убедиться, что все тесты проходят; в отчёте привести вывод команды
- [x] 5.4 Проверить, что `ledger/cli.py` и `ledger/reports.py` не изменены (`git diff --stat`)
