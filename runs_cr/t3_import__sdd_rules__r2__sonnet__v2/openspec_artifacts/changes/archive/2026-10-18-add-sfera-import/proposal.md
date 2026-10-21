## Why

Пользователи приносят выписки банка «Сфера», а импорт умеет только «Нову». Текущий `import_csv` к тому же хрупкий: повторный импорт задваивает операции, одна кривая строка роняет импорт посреди файла (часть строк уже записана), файлы из Excel (UTF-8 с BOM) не читаются. Нужен единый, атомарный, идемпотентный вход для импорта, который сам определяет формат и честно сообщает об ошибках разбора. См. LEDGER-58.

## What Changes

- Новый публичный API в `ledger/importer.py` (дословно из задачи):
  - `import_statement(path, store, *, fmt=None, strict=False, categorizer=None, clock=None) -> ImportResult`
  - `detect_format(path) -> str` — `"nova" | "sfera" | "sfera_split"`
  - `normalize_description(text: str) -> str` — то же сравнение описаний, что `ledger.rules.normalize_text`
  - `@dataclass(frozen=True) RowError(line_no: int, message: str)`
  - `@dataclass(frozen=True) ImportResult(format: str, encoding: str, added: int, duplicates: int, errors: list[RowError])`
- Новые исключения в `ledger/errors.py`: `UnknownFormatError(StatementError)`, `StatementRowError(StatementError)` (с заполненным `line_no`).
- Поддержка форматов: `nova` (как сейчас), `sfera` (`Дата;Сумма;Описание`), `sfera_split` (`Дата;Описание;Приход;Расход`). Колонки ищутся по названию без учёта регистра и пробелов по краям, порядок любой, лишние колонки игнорируются.
- Кодировка: UTF-8 (BOM допустим), иначе cp1251.
- Дедупликация относительно содержимого хранилища до импорта, по количеству (мультимножество); одинаковые строки внутри файла дублями не считаются.
- Пропуск мусорных строк (пустые, из пробелов, из одних разделителей) — не ошибка, не дубль, не добавление.
- Ошибочные строки: в `errors` (по умолчанию) либо `StatementRowError` на первой (`strict=True`); при `strict`-ошибке в хранилище не попадает ничего.
- **BREAKING (поведенческое, осознанное)**: `import_csv` остаётся с прежней сигнатурой и `int`, но становится обёрткой над строгим импортом формата `nova` через новый механизм: с дедупликацией, BOM/cp1251, пропуском пустых строк и атомарностью. Повторный импорт того же файла возвращает 0.

## Capabilities

### New Capabilities
- `statement-import`: импорт банковских выписок (nova, sfera, sfera_split): определение формата и кодировки, разбор строк, дедупликация, обработка ошибок, атомарность, совместимая обёртка `import_csv`.

### Modified Capabilities

## Impact

- Код: `ledger/importer.py` (основная работа), `ledger/errors.py` (два класса), `README.md` (строка про importer).
- Не трогаем: `ledger/cli.py`, `ledger/reports.py`, существующие тесты; публичный API `Transaction`, хранилищ и `Categorizer` не меняется. Только стандартная библиотека.
- CLI получает новое поведение `import_csv` без изменений в коде (дедупликация, атомарность).
