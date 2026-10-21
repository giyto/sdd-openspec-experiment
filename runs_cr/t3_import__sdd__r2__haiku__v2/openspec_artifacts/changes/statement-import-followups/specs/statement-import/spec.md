## ADDED Requirements

### Requirement: Dry run
The system SHALL accept `dry_run` in `import_statement`. When `dry_run=True`, the system SHALL parse,
deduplicate, and categorize the file exactly as a normal import does, and SHALL NOT write anything to the
store. The result SHALL report the same `format`, `encoding`, `added`, `duplicates`, and `errors` as a normal
import of the same file into the same store state would report. The result `transactions` SHALL contain the
transactions that a normal import would add, with `id` equal to `None`.

#### Scenario: Preview does not touch the store
- **GIVEN** a valid `sfera` file and an empty store
- **WHEN** the file is imported with `dry_run=True`
- **THEN** `added` is 2, `transactions` contains 2 transactions with `id` `None`, and the store is unchanged

#### Scenario: Preview counts match a real import
- **GIVEN** a file with a duplicate row, a row error, and two new rows, and a store that already contains the duplicate
- **WHEN** the file is imported with `dry_run=True` and then with `dry_run=False` into the same store state
- **THEN** both results have the same `added`, `duplicates`, and `errors`, and the transactions of the real import have the same dates, amounts, and descriptions as the preview, with `id` assigned

#### Scenario: Preview with strict mode
- **GIVEN** a file with a bad row
- **WHEN** the file is imported with `dry_run=True` and `strict=True`
- **THEN** `StatementRowError` is raised and the store is unchanged

### Requirement: Sfera amount format with comma or point
For `sfera`, the amount column SHALL contain a signed or unsigned number where the thousands are
separated by a space (regular or non-breaking, U+00A0), the decimal separator is either a comma or a
point, and the fractional part has at most two digits. A missing sign means income; a `-` sign means
expense; a `+` sign means income. A row where the amount contains both a comma and a point is a row
error. More than two fractional digits is a row error and the value SHALL NOT be rounded.

#### Scenario: Expense with thousands separator
- **WHEN** the amount is `-1 200,50` (U+00A0 as separator)
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Income with and without sign
- **WHEN** the amount is `+85 000,00` or `85 000,00`
- **THEN** the transaction amount is `85000.00` in both cases

#### Scenario: Decimal point is accepted
- **WHEN** the amount is `-1 234.56`
- **THEN** the transaction amount is `-1234.56`

#### Scenario: Comma and point together is a row error
- **WHEN** the amount is `1 234,5.6` or `1.234,56`
- **THEN** the row is reported as an error

#### Scenario: Too many fractional digits is a row error
- **WHEN** the amount is `-10,555` or `-10.555`
- **THEN** the row is reported as an error and the amount is not rounded

## MODIFIED Requirements

### Requirement: Sfera split amount format
For `sfera_split`, the `Приход` and `Расход` columns SHALL contain unsigned amounts in the same
format as `sfera`, with either a comma or a point as the decimal separator. Exactly one of the two
columns SHALL be non-empty. A value of zero (`0,00`, `0.00`, or zero in any equivalent notation) in a
column SHALL be treated as empty. A sign (`+` or `-`) in either column is a row error. The value of the
`Расход` column SHALL become a negative amount; the value of the `Приход` column SHALL become a positive amount.

A row in which both `Приход` and `Расход` contain zero (in any notation) is a service row, such as a
block placed by the bank. Such a row SHALL be skipped silently: it is NOT a row error, NOT a duplicate,
and NOT an added transaction. A row in which one column is zero and the other is empty is a row error.

#### Scenario: Expense in split format
- **WHEN** `Приход` is `0,00` and `Расход` is `1 200,50`
- **THEN** the transaction amount is `-1200.50`

#### Scenario: Income in split format
- **WHEN** `Приход` is `85 000,00` and `Расход` is `0,00`
- **THEN** the transaction amount is `85000.00`

#### Scenario: Income in split format with point separator
- **WHEN** `Приход` is `85 000.00` and `Расход` is `0.00`
- **THEN** the transaction amount is `85000.00`

#### Scenario: Both columns filled
- **WHEN** both `Приход` and `Расход` contain non-zero amounts
- **THEN** the row is reported as an error

#### Scenario: Both columns empty
- **WHEN** both `Приход` and `Расход` are empty
- **THEN** the row is reported as an error

#### Scenario: Zero in one column and empty in the other
- **WHEN** `Приход` is `0,00` and `Расход` is empty
- **THEN** the row is reported as an error

#### Scenario: Service row with zeros in both columns
- **GIVEN** a `sfera_split` file with a row `01.03.2026;Блокировка;0,00;0.00` between two valid rows
- **WHEN** the file is imported
- **THEN** the service row is not in `errors`, is not counted in `duplicates` or `added`, and the two valid rows are imported

#### Scenario: Sign in split column
- **WHEN** `Расход` is `-1 200,50`
- **THEN** the row is reported as an error

### Requirement: Row errors
A row error is any row, not blank, from which a valid transaction cannot be built. This includes:
wrong number of cells with non-blank extra cells, invalid date, invalid amount, zero amount, empty
description, and the format-specific conditions above. A row error SHALL NOT stop the import in
non-strict mode. Each row error SHALL be reported in `ImportResult.errors` as a `RowError` with
`line_no` of the physical line where the row starts (the header is line 1; blank lines are counted),
a `message` describing the problem, and `raw`: the text of the record as it stands in the file, without
the line break at its end. A record that spans several physical lines SHALL have them joined with `\n`;
Windows line breaks (`\r\n`) SHALL be written as `\n`. A byte order mark SHALL NOT be part of `raw`.

#### Scenario: Bad row does not stop the import
- **GIVEN** a `sfera` file with three rows where the second row has an invalid date
- **WHEN** the file is imported with `strict=False`
- **THEN** the first and third rows are added, `errors` contains one `RowError` with the line number of the second row

#### Scenario: Line numbers count physical lines
- **GIVEN** a file where a blank line precedes the bad row
- **WHEN** the file is imported
- **THEN** `line_no` of the bad row counts the blank line

#### Scenario: Raw text of a row error
- **GIVEN** a `sfera` file with a row `02.03.2026;1 2x0,00;Кофе` written with CRLF line ending
- **WHEN** the file is imported
- **THEN** the `RowError.raw` is `02.03.2026;1 2x0,00;Кофе` without the line ending

#### Scenario: Multi-line record in raw text
- **GIVEN** a `sfera` file with a row whose description is in quotes and spans two physical lines: `01.03.2026;-10,555;"Оплата\nпо договору"` where the amount has too many fractional digits
- **WHEN** the file is imported
- **THEN** `RowError.line_no` is the line where the record starts and `RowError.raw` is the record text with the two lines joined by `\n`

### Requirement: Strict mode
When `strict=True`, the system SHALL parse the whole file, collect every row error in file order, and
then raise `StatementRowError` if there is at least one. The exception SHALL have `errors` set to the list
of all row errors of the file, in file order, and SHALL have `line_no` and `message` taken from the first
of them. Nothing SHALL be written to the store (neither in memory nor on disk) when the exception is raised.
Duplicates SHALL NOT be treated as errors in strict mode.

#### Scenario: Strict import with a bad row
- **GIVEN** a file with a valid row followed by a bad row
- **WHEN** the file is imported with `strict=True`
- **THEN** `StatementRowError` is raised with the bad row's `line_no` and the store is unchanged

#### Scenario: Strict import with several bad rows
- **GIVEN** a file with a valid row, then a bad row, then another valid row, then another bad row
- **WHEN** the file is imported with `strict=True`
- **THEN** `StatementRowError` is raised, its `line_no` is the first bad row's line, its `errors` contains both bad rows in order, and the store is unchanged

#### Scenario: Strict import with duplicates only
- **GIVEN** every row of the file already exists in the store
- **WHEN** the file is imported with `strict=True`
- **THEN** no error is raised, `added` is 0 and `duplicates` equals the number of rows

### Requirement: normalize_description
The system SHALL provide `normalize_description(text)` that returns the comparison form of a
description. It SHALL be the same comparison as the project uses for descriptions everywhere.
The stored description of a transaction SHALL be the description as read, with leading and trailing
whitespace removed and every run of whitespace characters inside it (spaces, tabs, line breaks, and
non-breaking spaces) replaced by one space. The letters and their case SHALL NOT be changed. The stored
description SHALL NOT be normalized for comparison.

#### Scenario: Stored description is not normalized
- **WHEN** a row has description `  Магазин   Лента `
- **THEN** the transaction description is `Магазин Лента`

#### Scenario: Line breaks and tabs in a description
- **WHEN** a row has description `"Оплата\n\tпо  договору"` written as a quoted multi-line field
- **THEN** the transaction description is `Оплата по договору`

#### Scenario: Case is kept
- **WHEN** a row has description `  ЛЕНТА  express `
- **THEN** the transaction description is `ЛЕНТА express`

### Requirement: Result
`import_statement` SHALL return an `ImportResult` with `format`, `encoding`, `added`, `duplicates`,
`errors`, and `transactions`. `added + duplicates + len(errors)` SHALL equal the number of non-blank
data rows in the file, excluding service rows that are skipped. `transactions` SHALL be the list of
added transactions in file order. For a normal import, each transaction SHALL carry the `id` assigned by
the store. For a dry run, `id` SHALL be `None`.

#### Scenario: Result counts
- **GIVEN** a file with 5 non-blank data rows, of which 1 is a row error, 1 is a duplicate, and 3 are new
- **WHEN** the file is imported with `strict=False`
- **THEN** `added` is 3, `duplicates` is 1, `errors` has 1 entry, and `transactions` has 3 entries in file order

#### Scenario: Transactions carry store ids
- **GIVEN** an empty store and a valid file with two rows
- **WHEN** the file is imported
- **THEN** `transactions` has two entries in file order and their `id` values are the ids the store assigned

### Requirement: Error types
`UnknownFormatError` and `StatementRowError` SHALL both inherit from `StatementError`. The
`StatementRowError` SHALL have `line_no` set and SHALL have `errors`, a list of `RowError` with all row
errors of the file in file order. `UnknownFormatError` SHALL have `line_no` set to 1 when a header row was
found and to None when the file is empty.

#### Scenario: Error hierarchy
- **WHEN** code catches `StatementError`
- **THEN** it catches both `UnknownFormatError` and `StatementRowError`

#### Scenario: Row error list on the exception
- **GIVEN** a strict import that failed on two rows
- **WHEN** the caller catches `StatementRowError`
- **THEN** `errors` has two entries and `line_no` equals `errors[0].line_no`

## REMOVED Requirements

### Requirement: Sfera amount format
**Reason**: The requirement said a decimal point is not a valid separator in `sfera` amounts. The new
statement format writes amounts with a point, so both separators are accepted. The requirement is replaced
by "Sfera amount format with comma or point", which has the same thousands, sign, and digit rules.
**Migration**: Read "Sfera amount format with comma or point" (ADDED above). Scenarios for comma amounts keep
their meaning; the scenario that treated a point as a row error is replaced by "Decimal point is accepted"
and "Comma and point together is a row error".
