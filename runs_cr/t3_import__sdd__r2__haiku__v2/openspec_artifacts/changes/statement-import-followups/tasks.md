## 1. Errors

- [x] 1.1 Add `errors` to `StatementRowError` in `ledger/errors.py` (keyword, default empty list, `RowError` under `TYPE_CHECKING`) and verify `StatementRowError("m", line_no=2)` still works and `errors` is a list in a unit test.

## 2. Importer data model

- [x] 2.1 Add `raw: str = ""` to `RowError` and `transactions: list[Transaction] = field(default_factory=list)` to `ImportResult` in `ledger/importer.py`, and verify with `test_result_types_are_frozen` plus a test that `transactions` defaults to an empty list.
- [x] 2.2 Add `_clean_description` (`re.sub(r"\s+", " ", text).strip()`) and use it in the `nova`, `sfera`, and `sfera_split` parsers; verify with tests for leading/trailing spaces, runs of spaces, tabs and line breaks, NBSP, and unchanged case.

## 3. Amounts and service rows

- [x] 3.1 Change `_SFERA_UNSIGNED_AMOUNT` to accept `,` or `.` as the single decimal separator (at most two digits) and verify table-driven: `1 234.56` → `1234.56`, `-1 234,56` → `-1234.56`, `1 234,5.6` and `1.234,56` are row errors, `-10.555` and `-10,555` are row errors.
- [x] 3.2 Make `_parse_split_column` return zero as `Decimal` and empty as `None`, and let `_parse_sfera_split` return `None` when both columns are zero; verify that `0,00;0.00` and `0.00;0,00` rows are skipped, while `0,00;` (one zero, one empty), `;` (both empty), and `-0,00;0,00` are row errors.
- [x] 3.3 Let the parse loop skip rows whose parser returns `None` without counting them as errors, duplicates, or added; verify with a `sfera_split` file containing a service row between two valid rows (`errors` empty, `added` and `duplicates` count only the valid rows).

## 4. Error collection and strict mode

- [x] 4.1 Replace `_record_error` with appending to a list in the parse loop (including the `csv.Error` path with `raw`), and after the loop raise `StatementRowError(errors[0].message, line_no=errors[0].line_no, errors=errors)` when `strict` is true and errors exist; verify that a strict import of a file with two bad rows raises once with `errors` of length 2 and the store is unchanged.
- [x] 4.2 Compute `raw` for each record: split the decoded text with `io.StringIO(text, newline="").readlines()`, join the lines from the record's start to `reader.line_num`, replace `\r\n` and `\r` with `\n`, and strip one trailing `\n`; verify with a CRLF file (no `\r` in `raw`), a two-line quoted record (joined with `\n`), and a file with UTF-8 BOM (no BOM in `raw`).

## 5. Preview and transactions

- [x] 5.1 Add `dry_run: bool = False` to `import_statement`; when it is true, skip `store.add_many`, return `transactions` with `id` `None`, and keep `added`, `duplicates`, `errors` the same as a normal import; verify that the JSON file is byte-identical after a dry run and that the dry-run counts equal the real-import counts on the same input.
- [x] 5.2 Fill `ImportResult.transactions` for a normal import from the list returned by `store.add_many` (ids assigned) in file order; verify with a test that `transactions` ids match `MemoryStore.all()` and that order matches the file.
- [x] 5.3 Verify that `import_csv` keeps its signature and returns `int`, and that `import_csv` with a bad row raises `StatementRowError` whose `errors` has all bad rows; verify with the existing `import_csv` tests plus one new test.

## 6. Tests

- [x] 6.1 Update the tests in `tests/test_importer.py` that assert the old behavior of items 1–4: the `1 234.56` invalid-amount case (now valid), the `sfera_split` `("0,00", "0,00")` invalid case (now a skipped service row), the stored-description test (`Магазин   Лента` becomes `Магазин Лента`), and any strict test that expects the first error only; verify with `python -m pytest -q tests/test_importer.py`.
- [x] 6.2 Add tests for the new behavior: `dry_run` (store unchanged, `id` `None`, counts match a real import, strict dry run raises), `RowError.raw` (CRLF, multi-line, BOM), `StatementRowError.errors` order and `line_no` of the first error, and the description cases with tabs and line breaks; verify with `python -m pytest -q tests/test_importer.py`.
- [x] 6.3 Do not modify `tests/test_cli.py`, `ledger/cli.py`, or `ledger/reports.py`; verify with `git diff --stat -- tests/test_cli.py ledger/cli.py ledger/reports.py` showing no changes and `python -m pytest -q` showing zero failures.

## 7. Verification

- [x] 7.1 Run `python -m pytest -q` for the whole project and confirm zero failures; verify the command output.
- [x] 7.2 Run `openspec validate statement-import-followups --strict` and confirm the change is valid; verify the output.
