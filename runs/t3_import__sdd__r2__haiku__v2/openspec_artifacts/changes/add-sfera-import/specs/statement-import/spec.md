## Purpose

Импорт банковских выписок в хранилище транзакций: определение формата и кодировки файла,
разбор строк с построчной отчётностью об ошибках, дедупликация с уже сохранёнными операциями
и атомарная запись. Поддерживаются выписки банков «Нова» и «Сфера».

## ADDED Requirements

### Requirement: Format detection by header
The system SHALL determine the statement format from the header row of the file. Column names
SHALL be matched case-insensitively and ignoring leading and trailing whitespace. Columns that
are not used by the format SHALL be ignored, and the column order SHALL NOT matter.

The recognized formats are:
- `nova`: columns `date`, `amount`, `description`; delimiter `,`.
- `sfera`: columns `Дата`, `Сумма`, `Описание`; delimiter `;`.
- `sfera_split`: columns `Дата`, `Описание`, `Приход`, `Расход`; delimiter `;`.

#### Scenario: Sfera header with different case and spaces
- **WHEN** the header row is ` ДАТА ; Описание;сумма ;Номер карты`
- **THEN** the format is detected as `sfera` and the column `Номер карты` is ignored

#### Scenario: Sfera split header
- **WHEN** the header row is `Дата;Описание;Приход;Расход`
- **THEN** the format is detected as `sfera_split`

#### Scenario: Unrecognized header
- **WHEN** the header row does not contain all required columns of any format
- **THEN** the system raises `UnknownFormatError` with `line_no` 1 and nothing is written to the store

#### Scenario: Empty file
- **WHEN** the file is empty or contains only blank lines
- **THEN** the system raises `UnknownFormatError` and nothing is written to the store

#### Scenario: Explicit format does not match the header
- **WHEN** the caller passes `fmt="nova"` and the header is recognized as `sfera`
- **THEN** the system raises `UnknownFormatError` in both strict and non-strict modes and nothing is written to the store

#### Scenario: Explicit format matches the header
- **WHEN** the caller passes `fmt="sfera"` and the header is recognized as `sfera`
- **THEN** the import proceeds as for automatic detection

### Requirement: detect_format
The system SHALL provide `detect_format(path)` that returns one of `"nova"`, `"sfera"`, `"sfera_split"`
for the file, applying the same rules as automatic detection, and raises `UnknownFormatError` when
the format cannot be determined.

#### Scenario: Detection without import
- **WHEN** `detect_format` is called for a valid `sfera` file
- **THEN** it returns `"sfera"` and the store is not touched

### Requirement: Encoding detection
The system SHALL read a file as UTF-8 when the whole file decodes as UTF-8. A leading UTF-8 byte
order mark SHALL be accepted and removed. Otherwise the file SHALL be read as cp1251. The result
SHALL report `encoding` as `"utf-8"` or `"cp1251"`.

#### Scenario: UTF-8 with BOM from Excel
- **WHEN** a `sfera` file is saved as UTF-8 with BOM and the header is `Дата;Сумма;Описание`
- **THEN** the header is recognized, the result `encoding` is `"utf-8"`, and the BOM is not part of any column name

#### Scenario: cp1251 file
- **WHEN** a `sfera` file is saved in cp1251 and is not valid UTF-8
- **THEN** the file is read as cp1251 and the result `encoding` is `"cp1251"`

### Requirement: Sfera amount format
For `sfera`, the amount column SHALL contain a signed or unsigned number where the thousands are
separated by a space (regular or non-breaking, U+00A0), the decimal separator is a comma, and the
fractional part has at most two digits. A missing sign means income; a `-` sign means expense; a
`+` sign means income. A decimal point is NOT a valid separator. More than two fractional digits
is a row error and the value SHALL NOT be rounded.

#### Scenario: Expense with thousands separator
- **WHEN** the amount is `-1 200,50` (U+00A0 as separator)
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Income with and without sign
- **WHEN** the amount is `+85 000,00` or `85 000,00`
- **THEN** the transaction amount is `85000.00` in both cases

#### Scenario: Decimal point is a row error
- **WHEN** the amount is `1 234.56`
- **THEN** the row is reported as an error

#### Scenario: Too many fractional digits is a row error
- **WHEN** the amount is `-10,555`
- **THEN** the row is reported as an error and the amount is not rounded

### Requirement: Sfera split amount format
For `sfera_split`, the `Приход` and `Расход` columns SHALL contain unsigned amounts in the same
format as `sfera`. Exactly one of the two columns SHALL be non-empty. A value of `0,00` (or zero
in any equivalent notation) in a column SHALL be treated as empty. A sign (`+` or `-`) in either
column is a row error. The value of the `Расход` column SHALL become a negative amount; the value of
the `Приход` column SHALL become a positive amount.

#### Scenario: Expense in split format
- **WHEN** `Приход` is `0,00` and `Расход` is `1 200,50`
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Income in split format
- **WHEN** `Приход` is `85 000,00` and `Расход` is `0,00`
- **THEN** the transaction amount is `85000.00`

#### Scenario: Both columns filled
- **WHEN** both `Приход` and `Расход` contain non-zero amounts
- **THEN** the row is reported as an error

#### Scenario: Both columns empty
- **WHEN** both `Приход` and `Расход` are empty or `0,00`
- **THEN** the row is reported as an error

#### Scenario: Sign in split column
- **WHEN** `Расход` is `-1 200,50`
- **THEN** the row is reported as an error

### Requirement: Date format
For `sfera` and `sfera_split`, the date SHALL be written strictly as `DD.MM.YYYY` and SHALL be a
valid calendar date. For `nova`, the date SHALL be an ISO date `YYYY-MM-DD`. Any other spelling
or an invalid calendar date is a row error.

#### Scenario: Invalid calendar date
- **WHEN** the date is `31.02.2026`
- **THEN** the row is reported as an error

#### Scenario: Date with single-digit day
- **WHEN** the date is `1.03.2026`
- **THEN** the row is reported as an error

### Requirement: Row errors
A row error is any row, not blank, from which a valid transaction cannot be built. This includes:
wrong number of cells with non-blank extra cells, invalid date, invalid amount, zero amount, empty
description, and the format-specific conditions above. A row error SHALL NOT stop the import in
non-strict mode. Each row error SHALL be reported in `ImportResult.errors` as a `RowError` with
`line_no` of the physical line where the row starts (the header is line 1; blank lines are counted)
and a `message` describing the problem.

#### Scenario: Bad row does not stop the import
- **GIVEN** a `sfera` file with three rows where the second row has an invalid date
- **WHEN** the file is imported with `strict=False`
- **THEN** the first and third rows are added, `errors` contains one `RowError` with the line number of the second row

#### Scenario: Line numbers count physical lines
- **GIVEN** a file where a blank line precedes the bad row
- **WHEN** the file is imported
- **THEN** `line_no` of the bad row counts the blank line

### Requirement: Strict mode
When `strict=True`, the system SHALL stop at the first row error in file order, raise
`StatementRowError` with `line_no` set to that row's line, and write nothing to the store
(neither in memory nor on disk). Duplicates SHALL NOT be treated as errors in strict mode.

#### Scenario: Strict import with a bad row
- **GIVEN** a file with a valid row followed by a bad row
- **WHEN** the file is imported with `strict=True`
- **THEN** `StatementRowError` is raised with the bad row's `line_no` and the store is unchanged

#### Scenario: Strict import with duplicates only
- **GIVEN** every row of the file already exists in the store
- **WHEN** the file is imported with `strict=True`
- **THEN** no error is raised, `added` is 0 and `duplicates` equals the number of rows

### Requirement: Skipping blank and junk rows
Rows that consist only of whitespace (including non-breaking spaces) and delimiters, such as
empty lines, `;;;` for sfera or `,,` for nova, SHALL be skipped. Skipped rows are NOT row errors,
are NOT counted as duplicates, and are NOT counted as added transactions. This applies wherever
such rows appear in the file.

#### Scenario: Trailing junk rows
- **GIVEN** a `sfera` file ending with an empty line and a line `;;;`
- **WHEN** the file is imported
- **THEN** `errors` is empty and these lines are not counted in any result field

### Requirement: Duplicate detection
A transaction from the file is a duplicate when the store already contains a transaction with the
same date, the same amount, and a description equal under `normalize_description`. Duplicates
SHALL be counted in `duplicates` and SHALL NOT be added to the store.

Comparison SHALL use only the store's content before the import. Duplicates inside the same file
SHALL NOT be treated as duplicates of each other. If the store contains `k` transactions equal to a
given transaction and the file contains `n` such valid rows, then the first `min(k, n)` of those rows
are duplicates and the remaining rows are added.

Row errors SHALL NOT consume a duplicate slot.

#### Scenario: Repeated import adds nothing
- **GIVEN** a file that was already imported completely
- **WHEN** the same file is imported again
- **THEN** `added` is 0 and `duplicates` equals the number of valid rows

#### Scenario: Overlapping statement period
- **GIVEN** the store contains transactions from March 1 to March 10
- **WHEN** a statement from March 5 to March 15 is imported
- **THEN** rows that match March 5 to March 10 are counted as duplicates and the rest are added

#### Scenario: Identical rows within one file
- **GIVEN** the store is empty and the file contains two identical rows `01.03.2026;-150,00;Кофе`
- **WHEN** the file is imported
- **THEN** both rows are added and `duplicates` is 0

#### Scenario: Partially present identical rows
- **GIVEN** the store contains one `-150.00` transaction `Кофе` on 01.03.2026 and the file contains two identical such rows
- **WHEN** the file is imported
- **THEN** the first row is a duplicate, the second is added, and `duplicates` is 1

#### Scenario: Description comparison
- **GIVEN** the store contains `Магазин Лента` and the file contains `  магазин   ЛЕНТА `
- **WHEN** the file is imported
- **THEN** the row is a duplicate

### Requirement: normalize_description
The system SHALL provide `normalize_description(text)` that returns the comparison form of a
description. It SHALL be the same comparison as the project uses for descriptions everywhere.
The stored description of a transaction SHALL remain as read (with leading and trailing whitespace
removed) and SHALL NOT be normalized.

#### Scenario: Stored description is not normalized
- **WHEN** a row has description `  Магазин   Лента `
- **THEN** the transaction description is `Магазин   Лента`

### Requirement: Atomic write
The system SHALL write the valid, non-duplicate transactions of one import in a single store
operation. If that operation fails, the store SHALL be unchanged.

#### Scenario: Write failure
- **WHEN** the store fails to persist the batch
- **THEN** the error propagates and no transactions from the file are visible in the store

### Requirement: Categorization and timestamps
Each added transaction SHALL be categorized with the given `categorizer` when provided, and every
added transaction in one import SHALL have `imported_at` equal to the time obtained once from
`clock` at the start of the import.

#### Scenario: Categorized import
- **GIVEN** a categorizer with a rule matching `Кофейня`
- **WHEN** a row with description `Кофейня Зерно` is added
- **THEN** its category is the rule's category

### Requirement: Result
`import_statement` SHALL return an `ImportResult` with `format`, `encoding`, `added`, `duplicates`,
and `errors`. `added + duplicates + len(errors)` SHALL equal the number of non-blank data rows in the file.

#### Scenario: Result counts
- **GIVEN** a file with 5 non-blank data rows, of which 1 is a row error, 1 is a duplicate, and 3 are new
- **WHEN** the file is imported with `strict=False`
- **THEN** `added` is 3, `duplicates` is 1, and `errors` has 1 entry

### Requirement: import_csv compatibility
`import_csv(path, store, categorizer=None, clock=None)` SHALL keep its signature and return the
number of added transactions as `int`. It SHALL import the file as `nova` in strict mode with
duplicate detection, BOM and cp1251 support, blank-row skipping, and atomic write. Errors SHALL be
`StatementError` or its subclasses. The header of a `nova` file that is not recognized as `nova`
SHALL raise `UnknownFormatError` with `line_no` 1.

#### Scenario: Re-importing a Nova file through import_csv
- **GIVEN** a Nova statement already imported with `import_csv`
- **WHEN** `import_csv` is called with the same file
- **THEN** it returns 0 and the store is unchanged

#### Scenario: Bad row through import_csv
- **GIVEN** a Nova file where one row has an invalid amount
- **WHEN** `import_csv` is called
- **THEN** `StatementRowError` is raised with that row's `line_no` and the store is unchanged

### Requirement: Error types
`UnknownFormatError` and `StatementRowError` SHALL both inherit from `StatementError`. The
`StatementRowError` SHALL have `line_no` set. `UnknownFormatError` SHALL have `line_no` set to 1 when
a header row was found and to None when the file is empty.

#### Scenario: Error hierarchy
- **WHEN** code catches `StatementError`
- **THEN** it catches both `UnknownFormatError` and `StatementRowError`
