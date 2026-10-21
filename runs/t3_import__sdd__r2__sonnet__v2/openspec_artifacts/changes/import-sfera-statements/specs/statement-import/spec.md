## Purpose

Импорт банковских CSV-выписок («Нова», «Сфера») в хранилище транзакций: определение формата и кодировки, разбор строк, защита от дублей, честный отчёт об ошибках и атомарная запись.

## ADDED Requirements

### Requirement: Format detection by header
The system SHALL determine the statement format from the header (first line) when no format is given. Column names SHALL be matched case-insensitively and ignoring surrounding whitespace, in any order; extra columns SHALL be ignored. Supported formats: `nova` (comma-separated, columns `date`, `amount`, `description`), `sfera` (semicolon-separated, `Дата`, `Сумма`, `Описание`), `sfera_split` (semicolon-separated, `Дата`, `Описание`, `Приход`, `Расход`). A header matching none of them (including an empty file, a header matching both `sfera` and `sfera_split`, or a header with a duplicated required column) MUST raise `UnknownFormatError`. If a format is given explicitly and the header does not match it, or the given format name is not one of the three, the system MUST raise `UnknownFormatError`. In all these cases, in every mode, nothing SHALL be saved. For a non-empty file the error SHALL carry `line_no=1`; for an empty file `line_no` SHALL be `None`.

#### Scenario: Shuffled headers with extra columns
- **WHEN** a file starts with ` ДАТА ;Номер карты; Сумма ;Описание;Остаток`
- **THEN** it is detected as `sfera` and the extra columns are ignored

#### Scenario: Split format
- **WHEN** a file starts with `Дата;Описание;Приход;Расход`
- **THEN** it is detected as `sfera_split`

#### Scenario: Unrecognized header
- **WHEN** a file starts with `date,sum,description`
- **THEN** `UnknownFormatError` with `line_no=1` is raised and the store is unchanged

#### Scenario: Empty file
- **WHEN** the file is empty
- **THEN** `UnknownFormatError` is raised even with `strict=False`

#### Scenario: Explicit format contradicts header
- **WHEN** `fmt="nova"` is given for a `sfera` file
- **THEN** `UnknownFormatError` is raised and nothing is saved

### Requirement: Encoding detection
The system SHALL read a file as UTF-8 if the whole file decodes as UTF-8 (a leading BOM is allowed and ignored); otherwise as cp1251. The result SHALL report `encoding` as `"utf-8"` or `"cp1251"`. A file that decodes in neither encoding MUST raise `StatementError` without saving anything.

#### Scenario: UTF-8 with BOM
- **WHEN** a file saved from Excel starts with a UTF-8 BOM
- **THEN** the header is recognized and `encoding` is `"utf-8"`

#### Scenario: cp1251 file
- **WHEN** a file is encoded in cp1251
- **THEN** descriptions are read correctly and `encoding` is `"cp1251"`

### Requirement: Sfera row parsing
For `sfera`, the date MUST be strictly `ДД.ММ.ГГГГ` and a real calendar date. The amount MUST use a decimal comma, MAY use a space or U+00A0 as thousands separator, and MAY carry a leading `-` (expense) or `+` (income); no sign means income. A decimal point, more than two decimal digits, a non-numeric value, or a zero amount MUST make the row erroneous (amounts SHALL NOT be guessed or rounded). An empty description MUST make the row erroneous.

#### Scenario: Thousands and sign
- **WHEN** a row is `01.03.2026;-1 200,50;Магазин Лента` (the space may be U+00A0)
- **THEN** a transaction dated 2026-03-01 with amount `-1200.50` is produced

#### Scenario: Income with plus
- **WHEN** a row is `02.03.2026;+85 000,00;Зарплата`
- **THEN** the amount is `85000.00`

#### Scenario: Point instead of comma
- **WHEN** the amount is `1 234.56`
- **THEN** the row is erroneous

#### Scenario: Too many decimals or wrong date
- **WHEN** the amount is `10,005` or the date is `2026-03-01` or `1.3.2026`
- **THEN** the row is erroneous

### Requirement: Sfera split row parsing
For `sfera_split`, amounts in `Приход` and `Расход` MUST be unsigned (a `+` or `-` makes the row erroneous), with the same decimal-comma and thousands rules as `sfera`. Exactly one of the two columns SHALL be filled; a column containing a zero amount (`0,00`) SHALL be equivalent to an empty one. An expense becomes a negative amount. Rows with both columns filled, or with neither, MUST be erroneous. Dates follow the same rule as `sfera`.

#### Scenario: Expense column
- **WHEN** `Расход` is `150,00` and `Приход` is empty
- **THEN** the amount is `-150.00`

#### Scenario: Zero in unused column
- **WHEN** `Приход` is `0,00` and `Расход` is `150,00`
- **THEN** the row is valid with amount `-150.00`

#### Scenario: Both or neither filled
- **WHEN** both columns hold non-zero amounts, or both are empty or zero
- **THEN** the row is erroneous

#### Scenario: Signed amount
- **WHEN** `Расход` is `-150,00`
- **THEN** the row is erroneous

### Requirement: Nova row parsing
For `nova`, rows SHALL be parsed as before: ISO date, plain amount with a decimal point and no thousands separators, trimmed description. Header matching follows the common case-insensitive rule.

#### Scenario: Nova statement
- **WHEN** a valid `nova` file is imported
- **THEN** transactions get the dates, amounts and descriptions from the rows

### Requirement: Junk rows are skipped
Rows that are empty, consist only of whitespace, or contain only delimiters (and whitespace) SHALL be skipped silently wherever they appear: not an error, not a duplicate, not an added transaction.

#### Scenario: Junk at the end and in the middle
- **WHEN** a file contains `;;;`, a blank line and a whitespace-only line after and between data rows (or `,,` in `nova`)
- **THEN** all data rows are imported, `errors` is empty and the counters ignore the junk

### Requirement: Row errors and line numbers
A row is erroneous if a valid `Transaction` cannot be built from it (bad date, bad amount, empty description, missing required fields, zero amount, etc.). In non-strict mode erroneous rows SHALL be listed in `ImportResult.errors` as `RowError(line_no, message)` in file order, and all other rows SHALL be imported. `line_no` SHALL be the physical file line (the header is line 1, blank lines count; a multi-line quoted record is numbered by the line where it starts).

#### Scenario: Bad row among good ones
- **WHEN** line 3 has an invalid amount and lines 2 and 4 are valid
- **THEN** two transactions are added and `errors` contains one `RowError` with `line_no=3`

#### Scenario: Numbering with blank lines
- **WHEN** a blank line sits between the header and a bad row
- **THEN** the bad row's `line_no` counts the blank line

### Requirement: Strict mode
With `strict=True` the system MUST raise `StatementRowError` (with `line_no` set) on the first erroneous row, and nothing from the file SHALL reach the store, neither in memory nor in JSON. Duplicates SHALL NOT count as errors.

#### Scenario: Error after valid rows
- **WHEN** a strict import meets a bad row at line 4 after three valid rows
- **THEN** `StatementRowError` with `line_no=4` is raised and the store (and its JSON file) is unchanged

#### Scenario: Duplicates in strict mode
- **WHEN** a strict import is run on a file whose rows all exist in the store
- **THEN** no error is raised and `duplicates` equals the number of rows

### Requirement: Deduplication
A row is a duplicate if the store, as it was before the import, holds a transaction with the same date, the same amount and the same description compared via `normalize_description` (the project-wide description comparison: trimmed, whitespace collapsed, casefolded, `ё` treated as `е`). Matching SHALL be by count: if the store held k such transactions and the file has n valid rows with that key, the first min(k, n) of them in file order are duplicates (counted in `duplicates`, not added) and the rest are added. Identical rows inside one file SHALL NOT be duplicates of each other. Stored descriptions SHALL stay as in the file (trimmed), not normalized. `normalize_description` SHALL produce the same result as the project's description comparison normalization.

#### Scenario: Re-import adds nothing
- **WHEN** the same file is imported twice
- **THEN** the second result has `added=0` and `duplicates` equal to the number of data rows

#### Scenario: Two identical coffees
- **WHEN** a file has two identical rows of 150 for one day and the store is empty
- **THEN** `added=2` and `duplicates=0`

#### Scenario: Partially overlapping
- **WHEN** the store has 1 such transaction and the file has 2 identical rows
- **THEN** the first row is a duplicate and the second is added

#### Scenario: Description spelling
- **WHEN** the stored description is `Магазин  Лента` and the file has `магазин лента`
- **THEN** the row is a duplicate

### Requirement: Atomic write, categorization and metadata
All new transactions of one import SHALL be written in a single batch, so a store failure leaves nothing partial; when nothing is to be added the store SHALL NOT be written. `imported_at` SHALL be one clock reading for the whole import (the system clock by default). If a categorizer is given, each added transaction SHALL get the category it returns, when it returns one. The transaction description SHALL be the trimmed file value. The result SHALL report `format`, `encoding`, `added`, `duplicates` and `errors`.

#### Scenario: Categorized import
- **WHEN** a categorizer matches some rows
- **THEN** those transactions carry the category and `imported_at` equals the clock time

### Requirement: Compatible import_csv wrapper
`import_csv(path, store, categorizer=None, clock=None) -> int` SHALL keep its signature and return the number of added transactions. It SHALL perform a strict import of format `nova` with deduplication, UTF-8/BOM/cp1251 support, junk-row skipping and atomicity. Its statement errors SHALL be `StatementError` or subclasses; header problems keep `line_no=1`, row errors keep the row's `line_no`.

#### Scenario: Re-import through import_csv
- **WHEN** the same `nova` file is imported twice via `import_csv`
- **THEN** the second call returns `0`

#### Scenario: Bad row is atomic
- **WHEN** the third line of a `nova` file is invalid
- **THEN** `StatementError` with `line_no=3` is raised and the store is empty

#### Scenario: Wrong header
- **WHEN** the header is `date,sum,description`
- **THEN** a `StatementError` with `line_no=1` is raised
