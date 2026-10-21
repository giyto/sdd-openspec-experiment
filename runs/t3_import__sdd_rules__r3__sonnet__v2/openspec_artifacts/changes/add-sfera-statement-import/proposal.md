## Why

Пользователи приносят выписки банка «Сфера», а поддерживается только «Нова». Текущий `import_csv` к тому же хрупкий: повторный импорт задваивает операции, одна кривая строка роняет импорт посреди файла (часть строк уже записана), файлы из Excel (UTF-8 с BOM) не читаются. Нужен единый вход, который сам определяет формат, не задваивает операции и явно сообщает, что разобрать не удалось. См. LEDGER-58.

## What Changes

- Новый публичный API в `ledger/importer.py`, дословно по задаче:
  - `import_statement(path, store, *, fmt=None, strict=False, categorizer=None, clock=None) -> ImportResult`
  - `detect_format(path) -> str` (`"nova"` | `"sfera"` | `"sfera_split"`)
  - `normalize_description(text: str) -> str`
  - `@dataclass(frozen=True) RowError(line_no: int, message: str)`
  - `@dataclass(frozen=True) ImportResult(format: str, encoding: str, added: int, duplicates: int, errors: list[RowError])`
- Новые исключения в `ledger/errors.py`, оба наследуют `StatementError`: `UnknownFormatError`, `StatementRowError` (`line_no` заполнен).
- Поддержка форматов `sfera` (`Дата;Сумма;Описание`) и `sfera_split` (`Дата;Описание;Приход;Расход`) наряду с `nova`; колонки ищутся по названию без учёта регистра и пробелов по краям, порядок произвольный, лишние колонки игнорируются.
- Кодировка: UTF-8 (BOM допустим), иначе cp1251.
- Дедупликация по (дата, сумма, `normalize_description`) с учётом количества, только против содержимого хранилища до импорта.
- Мусорные строки (пустые, из пробелов, из одних разделителей) пропускаются где угодно.
- Ошибочные строки собираются в `errors`; при `strict=True` первая ошибка — `StatementRowError`, и в хранилище не попадает ничего.
- `import_csv(path, store, categorizer=None, clock=None) -> int` сохраняет сигнатуру и тип результата, но становится обёрткой: строгий импорт формата `nova` через `import_statement`, возвращает `added`. **Поведенческие изменения** `import_csv`: дубли пропускаются, читаются BOM/cp1251, пустые строки пропускаются, импорт атомарен.

## Capabilities

### New Capabilities
- `statement-import`: импорт банковских выписок (`nova`, `sfera`, `sfera_split`): определение формата и кодировки, разбор строк, дедупликация, отчёт об ошибках, строгий атомарный режим, совместимая обёртка `import_csv`.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций)

## Impact

- Код: `ledger/importer.py`, `ledger/errors.py`; документация в `README.md`; новые тесты. `ledger/cli.py` и `ledger/reports.py` не меняются, CLI получает новое поведение через `import_csv`.
- Публичный API `Transaction`, хранилищ и `Categorizer` не меняется; только стандартная библиотека. Существующие тесты не меняются.
