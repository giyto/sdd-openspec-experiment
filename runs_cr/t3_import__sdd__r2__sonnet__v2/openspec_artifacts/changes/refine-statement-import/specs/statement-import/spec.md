## MODIFIED Requirements

### Requirement: Sfera row parsing
For `sfera`, the date MUST be strictly `ДД.ММ.ГГГГ` and a real calendar date. The amount MAY use either a decimal comma or a decimal point (`-1 234,56` and `-1 234.56` are equivalent), MAY use a space or U+00A0 as thousands separator, and MAY carry a leading `-` (expense) or `+` (income); no sign means income. An amount containing both a comma and a point, more than two decimal digits (so `1.234` is not read as a thousands group), a non-numeric value, or a zero amount MUST make the row erroneous (amounts SHALL NOT be guessed or rounded). An empty description MUST make the row erroneous. The stored description SHALL be the file value with surrounding whitespace removed and every run of whitespace characters inside (spaces, tabs, line breaks, U+00A0 etc.) replaced by a single space; case and letters SHALL NOT change.

#### Scenario: Thousands and sign
- **WHEN** a row is `01.03.2026;-1 200,50;Магазин Лента` (the space may be U+00A0)
- **THEN** a transaction dated 2026-03-01 with amount `-1200.50` is produced

#### Scenario: Income with plus
- **WHEN** a row is `02.03.2026;+85 000,00;Зарплата`
- **THEN** the amount is `85000.00`

#### Scenario: Point instead of comma
- **WHEN** the amount is `-1 234.56`
- **THEN** the amount is `-1234.56`, same as for `-1 234,56`

#### Scenario: Comma and point together
- **WHEN** the amount is `1.234,56` or `1,234.56`
- **THEN** the row is erroneous

#### Scenario: Too many decimals or wrong date
- **WHEN** the amount is `10,005`, `10.005` or `1.234`, or the date is `2026-03-01` or `1.3.2026`
- **THEN** the row is erroneous

#### Scenario: Multi-line description
- **WHEN** the quoted description is `  Оплата   услуг`, a line break, a tab, `Связь` and a trailing space
- **THEN** the stored description is `Оплата услуг Связь`

### Requirement: Sfera split row parsing
For `sfera_split`, amounts in `Приход` and `Расход` MUST be unsigned (a `+` or `-` makes the row erroneous), with the same decimal comma/point, thousands and description rules as `sfera`. Exactly one of the two columns SHALL be filled with a non-zero amount; a column containing a zero amount (`0,00`, `0.00`) SHALL be equivalent to an empty one when the other column is non-zero. An expense becomes a negative amount. A row with both columns filled with non-zero amounts, or with both columns empty, or with one column zero and the other empty, MUST be erroneous. A row with an explicit zero amount in both columns (any mix of `0`, `0,00`, `0.00`) is a service operation and SHALL be skipped silently, whatever its date and description: not an error, not a duplicate, not an added transaction, and it SHALL NOT appear in `errors`, in strict-mode errors or in the counters. Dates follow the same rule as `sfera`.

#### Scenario: Expense column
- **WHEN** `Расход` is `150,00` and `Приход` is empty
- **THEN** the amount is `-150.00`

#### Scenario: Decimal point in split
- **WHEN** `Приход` is `1 000.50` and `Расход` is empty
- **THEN** the amount is `1000.50`

#### Scenario: Zero in unused column
- **WHEN** `Приход` is `0,00` and `Расход` is `150,00`
- **THEN** the row is valid with amount `-150.00`

#### Scenario: Zeros in both columns
- **WHEN** `Приход` is `0,00` and `Расход` is `0.00`
- **THEN** the row is skipped silently, in strict mode too

#### Scenario: Zero and empty
- **WHEN** one column is `0,00` and the other is empty
- **THEN** the row is erroneous

#### Scenario: Both or neither filled
- **WHEN** both columns hold non-zero amounts, or both are empty
- **THEN** the row is erroneous

#### Scenario: Signed amount
- **WHEN** `Расход` is `-150,00`
- **THEN** the row is erroneous

### Requirement: Nova row parsing
For `nova`, rows SHALL be parsed as before: ISO date, plain amount with a decimal point and no thousands separators. The description SHALL be stored with surrounding whitespace removed and inner whitespace runs replaced by a single space, as for `sfera`. Header matching follows the common case-insensitive rule.

#### Scenario: Nova statement
- **WHEN** a valid `nova` file is imported
- **THEN** transactions get the dates, amounts and descriptions from the rows

#### Scenario: Nova description whitespace
- **WHEN** a `nova` description is ` Кофейня   Зерно `
- **THEN** the stored description is `Кофейня Зерно`

### Requirement: Row errors and line numbers
A row is erroneous if a valid `Transaction` cannot be built from it (bad date, bad amount, empty description, missing required fields, zero amount, etc.), except rows that are skipped by the rules above. In non-strict mode erroneous rows SHALL be listed in `ImportResult.errors` as `RowError(line_no, message, raw)` in file order, and all other rows SHALL be imported. `line_no` SHALL be the physical file line (the header is line 1, blank lines count; a multi-line quoted record is numbered by the line where it starts). `raw` SHALL be the record text exactly as it stands in the decoded file (quotes and delimiters included), without the trailing line break; a record spanning several file lines SHALL be joined with `\n`. `raw` SHALL NOT contain a BOM or `\r` from Windows line breaks, and for cp1251 files it is the decoded text. `raw` defaults to an empty string for a `RowError` built without it.

#### Scenario: Bad row among good ones
- **WHEN** line 3 has an invalid amount and lines 2 and 4 are valid
- **THEN** two transactions are added and `errors` contains one `RowError` with `line_no=3`

#### Scenario: Numbering with blank lines
- **WHEN** a blank line sits between the header and a bad row
- **THEN** the bad row's `line_no` counts the blank line

#### Scenario: Raw text of a row
- **WHEN** line 2 of a CRLF file is `01.03.2026;abc;Магазин`
- **THEN** its `RowError.raw` is `01.03.2026;abc;Магазин` without `\r` or `\n`

#### Scenario: Raw text of a multi-line record
- **WHEN** a bad record starts at line 3 with `03.03.2026;x;"Оплата` and continues on line 4 with `услуг"` in a CRLF file
- **THEN** `line_no=3` and `raw` is `03.03.2026;x;"Оплата` + `\n` + `услуг"`

#### Scenario: Raw in BOM and cp1251 files
- **WHEN** the file has a UTF-8 BOM, or is encoded in cp1251, and its first data row is bad
- **THEN** `raw` has no BOM and contains the decoded Cyrillic text

### Requirement: Strict mode
With `strict=True` the system MUST parse the whole file and, if any row is erroneous, raise `StatementRowError` whose `errors` lists every `RowError` of the file in file order; its `line_no` and message SHALL be those of the first error. Nothing from the file SHALL reach the store, neither in memory nor in JSON, whether or not there are errors. Duplicates and silently skipped rows SHALL NOT count as errors. Header and format problems still raise immediately as before.

#### Scenario: Error after valid rows
- **WHEN** a strict import meets a bad row at line 4 after three valid rows
- **THEN** `StatementRowError` with `line_no=4` is raised and the store (and its JSON file) is unchanged

#### Scenario: Several errors
- **WHEN** a strict import has bad rows at lines 3 and 6 and valid rows between them
- **THEN** `StatementRowError` has `line_no=3`, the message of line 3 and `errors` with two `RowError` items for lines 3 and 6; the store is unchanged

#### Scenario: Duplicates in strict mode
- **WHEN** a strict import is run on a file whose rows all exist in the store
- **THEN** no error is raised and `duplicates` equals the number of rows

### Requirement: Atomic write, categorization and metadata
All new transactions of one import SHALL be written in a single batch, so a store failure leaves nothing partial; when nothing is to be added the store SHALL NOT be written. `imported_at` SHALL be one clock reading for the whole import (the system clock by default). If a categorizer is given, each added transaction SHALL get the category it returns, when it returns one. The transaction description SHALL be the whitespace-normalized file value. The result SHALL report `format`, `encoding`, `added`, `duplicates`, `errors` and `transactions`: the added transactions in file order, with the `id` assigned by the store (empty list when nothing is added).

#### Scenario: Categorized import
- **WHEN** a categorizer matches some rows
- **THEN** those transactions carry the category and `imported_at` equals the clock time

#### Scenario: Result transactions
- **WHEN** a file with three rows, one of them a duplicate, is imported
- **THEN** `transactions` holds the two added transactions in file order and each `id` equals the one the store holds

### Requirement: Compatible import_csv wrapper
`import_csv(path, store, categorizer=None, clock=None) -> int` SHALL keep its signature and return the number of added transactions. It SHALL perform a strict import of format `nova` with deduplication, UTF-8/BOM/cp1251 support, junk-row skipping and atomicity. Its statement errors SHALL be `StatementError` or subclasses; header problems keep `line_no=1`, row errors keep the `line_no` of the first erroneous row.

#### Scenario: Re-import through import_csv
- **WHEN** the same `nova` file is imported twice via `import_csv`
- **THEN** the second call returns `0`

#### Scenario: Bad row is atomic
- **WHEN** the third line of a `nova` file is invalid
- **THEN** `StatementError` with `line_no=3` is raised and the store is empty

#### Scenario: Wrong header
- **WHEN** the header is `date,sum,description`
- **THEN** a `StatementError` with `line_no=1` is raised

## ADDED Requirements

### Requirement: Dry-run preview
`import_statement` SHALL accept `dry_run` (default `False`). With `dry_run=True` the system SHALL do everything a normal import does — decoding, format detection, parsing, deduplication against the store, categorization, error collection, strict-mode behaviour — but SHALL NOT write to the store, neither in memory nor in JSON. The result SHALL have the same `format`, `encoding`, `added`, `duplicates` and `errors` as the real import of the same file into the same store would have, and `transactions` SHALL hold the transactions that would be added, in file order, with `id=None`. Calls without `dry_run` behave as before.

#### Scenario: Preview matches real import
- **WHEN** a file is imported with `dry_run=True` and then really, into the same store with the same clock
- **THEN** both results have equal `added`, `duplicates`, `errors`, and the transactions are equal except for `id`

#### Scenario: Store untouched
- **WHEN** a file is imported with `dry_run=True` into a `JsonFileStore` whose file does not exist
- **THEN** the store is empty and no file is created, and `transactions` items have `id=None`

#### Scenario: Strict dry run with errors
- **WHEN** `dry_run=True` and `strict=True` and the file has bad rows
- **THEN** `StatementRowError` with all errors is raised, as in a real import
