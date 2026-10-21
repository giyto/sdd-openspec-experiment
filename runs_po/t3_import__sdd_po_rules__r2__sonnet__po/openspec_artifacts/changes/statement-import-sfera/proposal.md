## Why

Пользователи приносят выписки банка «Сфера» (два формата), а проект умеет только «Нову». Текущий `import_csv` к тому же хрупкий: повторный импорт задваивает операции, одна кривая строка роняет импорт посреди файла (часть строк уже записана), файлы UTF-8 с BOM из Excel не читаются (LEDGER-58).

## What Changes

- Новый единый вход `import_statement(path, store, *, fmt=None, strict=False, categorizer=None, clock=None) -> ImportResult` в `ledger/importer.py`.
- `detect_format(path) -> str` (`"nova"` | `"sfera"` | `"sfera_split"`) и `normalize_description(text: str) -> str` в `ledger/importer.py`.
- Новые `@dataclass(frozen=True)` `RowError(line_no, message)` и `ImportResult(format, encoding, added, duplicates, errors)` в `ledger/importer.py`.
- Новые исключения в `ledger/errors.py`: `UnknownFormatError(StatementError)` и `StatementRowError(StatementError)` (`line_no` заполнен).
- Поддержка форматов «Сфера» (`Дата;Сумма;Описание`) и `sfera_split` (`Дата;Описание;Приход;Расход`) наряду с «Новой». Колонки ищутся по названию без учёта регистра и краевых пробелов, порядок произвольный, лишние колонки («Номер карты», «Остаток») игнорируются; `0,00` в неиспользуемой колонке `sfera_split` равно пустой.
- Определение кодировки: UTF-8 (BOM допустим) или cp1251.
- Пропуск дублей (дата + сумма + `normalize_description`) относительно операций, уже лежавших в учёте до загрузки, с учётом количества; одинаковые строки внутри одного файла — разные операции; счётчик `duplicates`.
- Кривые строки собираются в `errors`; при `strict=True` первая такая строка бросает `StatementRowError`, и в хранилище не попадает ничего.
- Пустые/мусорные строки (пробелы, `;;;`, `,,`) пропускаются молча.
- `import_csv(path, store, categorizer=None, clock=None) -> int` сохраняет сигнатуру и тип результата, делегирует в `import_statement`; CLI не меняется.
- Нет **BREAKING**-изменений публичного API. Наблюдаемое отличие `import_csv`: больше не задваивает существующие операции и читает UTF-8 с BOM и cp1251.

## Capabilities

### New Capabilities
- `statement-import`: импорт банковских выписок («Нова», «Сфера», «Сфера split»): определение формата и кодировки, разбор строк, дедупликация, отчёт об ошибках, атомарность strict-режима.

### Modified Capabilities

## Impact

- Код: `ledger/importer.py`, `ledger/errors.py`; обновить таблицу модулей и раздел про выписки в `README.md`; новые тесты (существующие не меняются).
- Не трогаем: `ledger/cli.py`, `ledger/reports.py`, публичный API `Transaction`, хранилищ, `Categorizer`.
- Зависимости: только стандартная библиотека.
- Допущения по неоднозначностям ТЗ перечислены в `design.md` (раздел «Допущения»).
