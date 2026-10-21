## MODIFIED Requirements

### Requirement: Split-column amounts
In `sfera_split`, the `Приход` and `Расход` columns SHALL hold unsigned amounts in the same notation as `sfera`
(either decimal separator is accepted, and a value with both is a row error).
Exactly one of the two columns SHALL be non-empty and non-zero; a value that is zero (`0,00`, `0.00`, `0`) counts as empty
for this rule. An amount in `Приход` is income (positive). An amount in `Расход` is an expense and is stored as a negative amount.
A row with both columns empty or both filled, with one column zero and the other empty, or with a sign in either column,
is a row error.

#### Scenario: Expense in the Расход column
- **WHEN** a `sfera_split` row has `Расход` = `1 200,50` and `Приход` = `0,00`
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Expense with decimal point
- **WHEN** a `sfera_split` row has `Расход` = `1 200.50` and `Приход` = `0.00`
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Both columns filled
- **WHEN** a `sfera_split` row has non-zero values in both `Приход` and `Расход`
- **THEN** the row is reported as an error

#### Scenario: One column zero, the other empty
- **WHEN** a `sfera_split` row has `Приход` = `0,00` and `Расход` empty
- **THEN** the row is reported as an error

#### Scenario: Sign in a split column
- **WHEN** a `sfera_split` row has `Расход` = `-1 200,50`
- **THEN** the row is reported as an error

### Requirement: Row errors and line numbers
Each row that cannot produce a valid transaction SHALL be reported as a `RowError` with `line_no` set to the
physical line where the record starts (the header is line 1; blank lines are counted), a human-readable `message`,
and `raw`: the text of the record as it appears in the file, decoded, without a byte-order mark, without the line
break at its end, with each line break inside a multi-line record (`\r\n`, `\r` or `\n`) represented as `\n`.
Whitespace inside `raw` is not normalized. A header-level error raised as `UnknownFormatError` SHALL carry `line_no=1`
when the file has a header line.
In non-strict mode (`strict=False`) row errors SHALL NOT stop the import: valid rows are imported and invalid rows
are listed in `ImportResult.errors` in file order.

#### Scenario: Bad row in the middle of the file
- **WHEN** a file of 5 data rows has an invalid row at physical line 4
- **THEN** the 4 valid rows are added, and `errors` contains one `RowError` with `line_no=4`

#### Scenario: Raw text of a row
- **WHEN** a file saved with Windows line breaks has the row `01.03.2026;-1 200,5x;Кофе` on line 3
- **THEN** the `RowError` for that row has `raw` equal to `01.03.2026;-1 200,5x;Кофе` with no `\r` and no trailing line break

#### Scenario: Raw text of a multi-line record
- **WHEN** a record in quotes spans lines 5 and 6 of the file and is invalid
- **THEN** its `RowError` has `line_no=5` and `raw` contains the two lines joined by `\n`

### Requirement: Strict import is all-or-nothing
With `strict=True` the system SHALL parse the whole file and, if any row errors exist, raise `StatementRowError`
after the parse. The exception SHALL carry `errors`, the list of all row errors of the file in file order, and its
`line_no` and message SHALL be those of the first error. No transaction SHALL be written, and both the in-memory store
and any JSON file SHALL remain unchanged. Duplicates SHALL NOT count as errors.

#### Scenario: Error on the last line
- **WHEN** a file of 100 valid rows has an invalid row on the last line and `strict=True`
- **THEN** `StatementRowError` is raised with that `line_no`, `errors` has one entry, and the store contains no new transactions

#### Scenario: Several errors in strict mode
- **WHEN** a file has invalid rows on lines 3 and 7 and `strict=True`
- **THEN** `StatementRowError` is raised with `line_no=3`, and `errors` lists the `RowError` for line 3 followed by the one for line 7

#### Scenario: Duplicates in strict mode
- **WHEN** a file contains only rows already in the store and `strict=True`
- **THEN** the import succeeds with `added=0` and `duplicates` equal to the number of rows

### Requirement: Categorization and timestamps
Each added transaction SHALL be categorized with the given `categorizer` if one is provided, and SHALL have
`imported_at` set to the time returned by `clock.now()` read once per import.

#### Scenario: Categorizer applied
- **WHEN** a categorizer matches one of the new transactions
- **THEN** that transaction is stored with the matched category; duplicates are not re-categorized

### Requirement: Result object
`import_statement` SHALL return an `ImportResult` with `format`, `encoding`, `added`, `duplicates`, `errors`, and
`transactions`. `added + duplicates + len(errors)` SHALL equal the number of non-skipped data rows in the file.
`transactions` SHALL list the added transactions in file order. For a normal import each one carries the `id`
assigned by the store; for a dry run each one has `id` equal to `None`.

#### Scenario: Result counts
- **WHEN** a file has 10 data rows, 2 blank lines, 1 invalid row, and 3 duplicates of stored transactions
- **THEN** `added + duplicates + len(errors)` equals 10 and `errors` has one entry

#### Scenario: Transactions in file order
- **WHEN** a file of three new valid rows is imported normally
- **THEN** `transactions` has three entries in the order of the rows, each with an assigned `id`

## REMOVED Requirements

### Requirement: Sfera amount and date rules
**Reason**: Правило «точка в сумме — ошибка строки» отменено (LEDGER-74, п.1). Правило суммы разделено на
«Sfera amount notation» (новые правила разделителей) и «Sfera date rules» (дата без изменений).
**Migration**: Требования заменены ниже в разделе ADDED; сценарии «Expense with thousands separator»,
«Income without sign», «Three decimal places is a row error» и «Invalid date» перенесены без изменения смысла.

## ADDED Requirements

### Requirement: Sfera amount notation
In `sfera`, the amount column SHALL hold digits with an optional decimal separator, which is either a comma
or a decimal point (at most two digits after it), thousands separated by a single space or a no-break space
(U+00A0) in groups of three digits, and an optional `+` or `-` sign. A negative amount is an expense; a positive
amount or an unsigned amount is income. An amount that contains both a comma and a decimal point is a row error.
A value with more than two decimal places, or any other shape, is a row error.

#### Scenario: Expense with thousands separator
- **WHEN** an `sfera` row has amount `-1 200,50` (space or no-break space as separator)
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Income without sign
- **WHEN** an `sfera` row has amount `85 000,00`
- **THEN** the transaction amount is `85000.00`

#### Scenario: Decimal point is accepted
- **WHEN** an `sfera` row has amount `-1 234.56`
- **THEN** the transaction amount is `-1234.56` and the row is imported

#### Scenario: Both decimal separators in one amount is a row error
- **WHEN** an `sfera` row has amount `1.234,56` or `1,234.56`
- **THEN** the row is reported in `errors` with its `line_no`, and it is not imported

#### Scenario: Three decimal places is a row error
- **WHEN** an `sfera` row has amount `-10,123` or `-10.123`
- **THEN** the row is reported as an error and the amount is not rounded

### Requirement: Sfera date rules
The date column of `sfera` and `sfera_split` SHALL be exactly `DD.MM.YYYY` and denote a real calendar date;
otherwise it is a row error.

#### Scenario: Invalid date
- **WHEN** an `sfera` row has date `2026-03-01` or `31.02.2026`
- **THEN** the row is reported as an error

### Requirement: Description whitespace normalization
When a transaction is created from a row of any format, its description SHALL have leading and trailing whitespace
removed, and every run of whitespace characters inside it (spaces, tabs, line breaks, no-break spaces) SHALL be replaced
by a single space. Letters and letter case SHALL NOT be changed.

#### Scenario: Multiple spaces and tabs inside a description
- **WHEN** a row has description `  Кофейня\t  Зерно  ` (with tabs and spaces)
- **THEN** the stored description is `Кофейня Зерно`

#### Scenario: Multi-line quoted description
- **WHEN** a `sfera` description in quotes spans two lines, `"Оплата\nза услуги"`
- **THEN** the stored description is `Оплата за услуги`

#### Scenario: Case is preserved
- **WHEN** a row has description `ООО  Ромашка`
- **THEN** the stored description is `ООО Ромашка`

### Requirement: Zero service rows in sfera_split are skipped
In `sfera_split`, a data row whose `Приход` and `Расход` columns both hold an explicit zero amount (`0,00`, `0.00`, `0`)
SHALL be skipped silently. Such a row is neither an error, nor a duplicate, nor an imported transaction. This applies only
when both columns are explicitly zero: an empty column next to a zero column is still a row error.

#### Scenario: Blocking operation row
- **WHEN** a `sfera_split` file contains the row `05.03.2026;Блокировка;0,00;0.00`
- **THEN** the row does not appear in `errors`, is not counted in `added` or `duplicates`, and is not imported

#### Scenario: Zero in one column and empty in the other
- **WHEN** a `sfera_split` row has `Приход` = `0,00` and `Расход` empty
- **THEN** the row is reported as an error

### Requirement: Dry run preview
`import_statement` SHALL accept `dry_run: bool = False`. With `dry_run=True` the system SHALL perform the same parsing,
error handling, strict-mode checks, duplicate detection and categorization as a normal import, and SHALL NOT write to the
store: `add_many` SHALL NOT be called and a JSON file SHALL NOT be created or changed. The returned `ImportResult` SHALL
have the same `format`, `encoding`, `added`, `duplicates`, `errors` and `transactions` (with `id` equal to `None`) as a
normal import of the same file into the same store would produce. A dry run with `strict=True` SHALL raise
`StatementRowError` in the same cases as a normal import.

#### Scenario: Preview does not change the store
- **WHEN** `import_statement` is called with `dry_run=True` on a file with 3 new valid rows
- **THEN** the result has `added=3` and 3 transactions with `id` equal to `None`, and the store contents are unchanged

#### Scenario: Preview matches the real import
- **WHEN** a file is imported with `dry_run=True` and then, with the same store state, without it
- **THEN** both results have the same `added`, `duplicates`, `errors` and the same transactions, apart from `id`
