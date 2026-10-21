# statement-import Specification

## Purpose
Импорт банковских выписок в хранилище транзакций: определение формата и кодировки файла,
разбор строк трёх форматов («Нова», «Сфера», «Сфера» с раздельными колонками), защита от
повторного импорта и честный отчёт об ошибках строк.

## Requirements

### Requirement: Format detection by header
The system SHALL determine the statement format from the header row when `fmt` is not given.
The header is the first non-blank line of the file. Column names SHALL be matched case-insensitively,
ignoring leading and trailing whitespace; columns not used by the format SHALL be ignored.
The recognized formats are `nova` (columns `date`, `amount`, `description`), `sfera`
(columns `Дата`, `Сумма`, `Описание`) and `sfera_split` (columns `Дата`, `Описание`, `Приход`, `Расход`).
If the header matches none of the formats, or matches more than one, the system SHALL raise `UnknownFormatError`.

#### Scenario: Sfera header with shifted case and spaces
- **WHEN** the file header is ` ДАТА ; Номер карты ; сумма ;Описание ` followed by data rows
- **THEN** `detect_format` returns `"sfera"` and the column `Номер карты` is ignored

#### Scenario: Split-column header
- **WHEN** the header is `Дата;Описание;Приход;Расход`
- **THEN** `detect_format` returns `"sfera_split"`

#### Scenario: Unrecognized header
- **WHEN** the header is `date;sum;description` or the file is empty
- **THEN** the system raises `UnknownFormatError` with no transaction written to the store

### Requirement: Explicit format must match the header
When `fmt` is given, the system SHALL use it and SHALL raise `UnknownFormatError` if the header
does not match that format or if `fmt` is not one of `nova`, `sfera`, `sfera_split`. No transaction SHALL be written in that case.

#### Scenario: Explicit format does not match the file
- **WHEN** `import_statement` is called with `fmt="nova"` on a `sfera` file
- **THEN** the system raises `UnknownFormatError` and the store is unchanged

### Requirement: Encoding detection
The system SHALL read a file as UTF-8 if the whole file decodes as UTF-8, with or without a BOM
(a leading BOM is not part of the data). Otherwise the file SHALL be read as cp1251.
`ImportResult.encoding` SHALL report `"utf-8"` or `"cp1251"` accordingly.
If the file cannot be decoded as cp1251 either, the system SHALL raise `UnknownFormatError`.

#### Scenario: Excel export with BOM
- **WHEN** a `sfera` file is saved as UTF-8 with a BOM
- **THEN** the import succeeds, `encoding` is `"utf-8"`, and the first column name is recognized

#### Scenario: Windows-1251 file
- **WHEN** a `sfera` file contains cyrillic text in cp1251 bytes that are not valid UTF-8
- **THEN** the import reads the descriptions correctly and `encoding` is `"cp1251"`

### Requirement: Sfera amount and date rules
In `sfera`, the amount column SHALL hold digits with an optional decimal comma (at most two digits after it),
thousands separated by a single space or a no-break space (U+00A0) in groups of three digits,
and an optional `+` or `-` sign. A negative amount is an expense; a positive amount or an unsigned amount is income.
A value with a decimal point, more than two decimal places, or any other shape is a row error.
The date column SHALL be exactly `DD.MM.YYYY` and denote a real calendar date; otherwise it is a row error.

#### Scenario: Expense with thousands separator
- **WHEN** an `sfera` row has amount `-1 200,50` (space or no-break space as separator)
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Income without sign
- **WHEN** an `sfera` row has amount `85 000,00`
- **THEN** the transaction amount is `85000.00`

#### Scenario: Decimal point is a row error
- **WHEN** an `sfera` row has amount `1 234.56`
- **THEN** the row is reported in `errors` with its `line_no`, and it is not imported

#### Scenario: Three decimal places is a row error
- **WHEN** an `sfera` row has amount `-10,123`
- **THEN** the row is reported as an error and the amount is not rounded

#### Scenario: Invalid date
- **WHEN** an `sfera` row has date `2026-03-01` or `31.02.2026`
- **THEN** the row is reported as an error

### Requirement: Split-column amounts
In `sfera_split`, the `Приход` and `Расход` columns SHALL hold unsigned amounts in the same notation as `sfera`.
Exactly one of the two columns SHALL be non-empty and non-zero; a value of `0,00` counts as empty.
An amount in `Приход` is income (positive). An amount in `Расход` is an expense and is stored as a negative amount.
A row with both columns empty or both filled, or with a sign in either column, is a row error.

#### Scenario: Expense in the Расход column
- **WHEN** a `sfera_split` row has `Расход` = `1 200,50` and `Приход` = `0,00`
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Both columns filled
- **WHEN** a `sfera_split` row has non-zero values in both `Приход` and `Расход`
- **THEN** the row is reported as an error

#### Scenario: Sign in a split column
- **WHEN** a `sfera_split` row has `Расход` = `-1 200,50`
- **THEN** the row is reported as an error

### Requirement: Nova format
The `nova` format SHALL keep the rules of the existing Nova import: ISO dates `YYYY-MM-DD`,
amounts with a decimal point and a sign (no thousands separators), and `,` as the field delimiter.

#### Scenario: Nova row with bad amount
- **WHEN** a `nova` row has amount `abc`
- **THEN** the row is reported as an error with its `line_no`

### Requirement: Blank and junk rows are skipped
Rows that contain only whitespace or only delimiters (for example `;;;` in `sfera`, `,,` in `nova`)
SHALL be skipped wherever they occur. A skipped row is neither an error, nor a duplicate, nor an imported transaction.

#### Scenario: Trailing junk rows
- **WHEN** a `sfera` file ends with an empty line, a line of spaces and a line `;;;`
- **THEN** none of these lines appear in `errors` and none is counted as added or duplicate

### Requirement: Field count
A data row with fewer fields than the columns the format needs, or with a non-empty value beyond the
header's columns, SHALL be reported as a row error. A row with the required columns present but empty
is handled by the rules of the format (for example, a missing description is a row error).

#### Scenario: Short row
- **WHEN** an `sfera` row contains only a date and an amount
- **THEN** the row is reported as an error with its `line_no`

### Requirement: Row errors and line numbers
Each row that cannot produce a valid transaction SHALL be reported as a `RowError` with `line_no` set to the
physical line where the record starts (the header is line 1; blank lines are counted), and a human-readable message.
A header-level error raised as `UnknownFormatError` SHALL carry `line_no=1` when the file has a header line.
In non-strict mode (`strict=False`) row errors SHALL NOT stop the import: valid rows are imported and invalid rows
are listed in `ImportResult.errors` in file order.

#### Scenario: Bad row in the middle of the file
- **WHEN** a file of 5 data rows has an invalid row at physical line 4
- **THEN** the 4 valid rows are added, and `errors` contains one `RowError` with `line_no=4`

### Requirement: Duplicate detection against the store
A transaction is a duplicate when the store already holds a transaction with the same date, the same amount,
and a description equal under `normalize_description`. Comparison uses the store's contents before the import starts.
For each key, if the store holds `k` such transactions and the file contains `n` valid rows with that key,
the first `min(k, n)` such rows in file order SHALL be counted in `duplicates` and not added; the remaining rows are added.
Rows that repeat within the file are NOT duplicates of each other.
`normalize_description` SHALL return the same comparison form as the rest of the project.

#### Scenario: Re-importing the same file
- **WHEN** a file is imported twice into the same store
- **THEN** the second import adds 0 transactions and reports every valid row in `duplicates`

#### Scenario: Two identical coffee purchases in one file
- **WHEN** the store is empty and the file contains two rows `01.03.2026;-150,00;Кофе`
- **THEN** both rows are added and `duplicates` is 0

#### Scenario: Overlapping statement period
- **WHEN** the store holds one `-150.00 Кофе` on 2026-03-01 and the file contains two rows of that kind on that date
- **THEN** one row is counted as a duplicate and one is added

#### Scenario: Description differs only in case or spacing
- **WHEN** the store holds `Магазин  Лента` and the file has `магазин лента` with the same date and amount
- **THEN** the row is counted as a duplicate

### Requirement: Non-strict import is row-tolerant
With `strict=False` the system SHALL write all valid, non-duplicate transactions in one storage operation,
so that a failure during writing leaves the store with none of the new transactions.

#### Scenario: Mixed file
- **WHEN** a file contains valid rows, one invalid row and one duplicate
- **THEN** `added` counts the valid new rows, `duplicates` is 1, `errors` has one entry, and the store grows by `added`

### Requirement: Strict import is all-or-nothing
With `strict=True` the system SHALL stop at the first row error in file order, raise `StatementRowError`
with that `line_no`, and leave both the in-memory store and any JSON file unchanged. Duplicates SHALL NOT count as errors.

#### Scenario: Error on the last line
- **WHEN** a file of 100 valid rows has an invalid row on the last line and `strict=True`
- **THEN** `StatementRowError` is raised with that `line_no` and the store contains no new transactions

#### Scenario: Duplicates in strict mode
- **WHEN** a file contains only rows already in the store and `strict=True`
- **THEN** the import succeeds with `added=0` and `duplicates` equal to the number of rows

### Requirement: Categorization and timestamps
Each added transaction SHALL be categorized with the given `categorizer` if one is provided, and SHALL have
`imported_at` set to the time returned by `clock.now()` read once per import. Transaction descriptions SHALL be stored
as they appear in the file, with surrounding whitespace removed.

#### Scenario: Categorizer applied
- **WHEN** a categorizer matches one of the new transactions
- **THEN** that transaction is stored with the matched category; duplicates are not re-categorized

### Requirement: Result object
`import_statement` SHALL return an `ImportResult` with `format`, `encoding`, `added`, `duplicates`, and `errors`.
`added + duplicates + len(errors)` SHALL equal the number of non-skipped data rows in the file.

#### Scenario: Result counts
- **WHEN** a file has 10 data rows, 2 blank lines, 1 invalid row, and 3 duplicates of stored transactions
- **THEN** `added + duplicates + len(errors)` equals 10 and `errors` has one entry

### Requirement: Compatibility of import_csv
`import_csv(path, store, categorizer=None, clock=None) -> int` SHALL keep its signature and return type.
It SHALL behave as a strict import of the `nova` format with the same guarantees (duplicates skipped, BOM and cp1251
accepted, blank rows skipped, all-or-nothing write), and SHALL return the number of transactions added.
Errors are raised as `StatementError` or its subclasses (`UnknownFormatError`, `StatementRowError`).

#### Scenario: Re-running the CLI import
- **WHEN** the CLI runs `import` twice on the same Nova file
- **THEN** the second run reports `Imported 0 transactions`

#### Scenario: Missing column in Nova file
- **WHEN** a Nova-style file lacks the `amount` column
- **THEN** a `StatementError` is raised with `line_no=1`
