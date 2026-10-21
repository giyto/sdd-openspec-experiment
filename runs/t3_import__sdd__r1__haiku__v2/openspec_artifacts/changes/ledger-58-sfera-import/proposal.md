## Why

Пользователи всё чаще приносят выписки банка «Сфера», а импорт умеет только «Нову».
Текущий импорт (`import_csv`) хрупкий: повторный импорт задваивает операции, кривая строка
роняет импорт на середине (часть строк уже записана), а файлы, сохранённые из Excel
(UTF-8 с BOM), не читаются.

## What Changes

- Новый вход `import_statement(path, store, *, fmt=None, strict=False, categorizer=None, clock=None) -> ImportResult`
  в `ledger/importer.py`. Он сам определяет формат по заголовку (`nova`, `sfera`, `sfera_split`)
  и кодировку (UTF-8 с BOM или без, иначе cp1251).
- `detect_format(path) -> str` и `normalize_description(text) -> str` (сравнение описаний
  через существующий `rules.normalize_text`).
- Дедупликация по дате, сумме и нормализованному описанию относительно хранилища до импорта:
  первые `min(k, n)` строк файла, совпадающих с k транзакциями в хранилище, считаются дублями.
  Дубли внутри одного файла дублями не считаются.
- Построчная обработка ошибок: плохая строка попадает в `ImportResult.errors` с `line_no`,
  остальные строки импортируются. Режим `strict=True` бросает `StatementRowError` на первой
  ошибке и не записывает ничего.
- Пустые и «мусорные» строки (пустые, из пробелов, из одних разделителей) молча пропускаются.
- Новые исключения в `ledger/errors.py`: `UnknownFormatError` и `StatementRowError`,
  оба наследуют `StatementError`.
- **BREAKING**: нет. `import_csv(path, store, categorizer=None, clock=None) -> int` сохраняет
  сигнатуру и возвращаемое значение, но становится обёрткой над `import_statement(..., fmt="nova", strict=True)`:
  получает дедупликацию, BOM/cp1251, пропуск пустых строк и атомарность. CLI не меняется.

## Capabilities

### New Capabilities
- `statement-import`: распознавание формата и кодировки банковской выписки, разбор строк
  форматов `nova`, `sfera`, `sfera_split`, дедупликация относительно хранилища, поведение
  при ошибках строк (нестрогий и строгий режим).

### Modified Capabilities
<!-- Нет: в openspec/specs/ пока нет спецификаций импорта; поведение import_csv описано в statement-import. -->

## Impact

- Код: `ledger/importer.py` (переписывается внутри, публичная сигнатура `import_csv` сохраняется),
  `ledger/errors.py` (два новых исключения), `README.md` (раздел про форматы выписок).
- Тесты: существующие тесты `tests/test_importer.py` не меняются и должны проходить без правок;
  добавляются новые тесты импорта.
- Не затрагиваются: `ledger/cli.py`, `ledger/reports.py`, публичный API `Transaction`,
  хранилищ и `Categorizer`.
- Зависимости: только стандартная библиотека.
