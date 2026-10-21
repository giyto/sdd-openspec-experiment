## 1. Errors

- [x] 1.1 Add `UnknownFormatError(StatementError)` and `StatementRowError(StatementError)` to `ledger/errors.py` with docstrings; verify `issubclass` checks and that `StatementRowError` exposes `line_no` in a unit test.

## 2. Importer core

- [x] 2.1 Add `normalize_description` delegating to `rules.normalize_text` and `RowError`/`ImportResult` frozen dataclasses to `ledger/importer.py`; verify with unit tests on `ё`/`е`, case, and whitespace.
- [x] 2.2 Implement encoding detection (strict UTF-8 with BOM stripped, then cp1251; cp1251 failure → `UnknownFormatError`) and physical-line tracking via `csv.reader.line_num`; verify with tests for BOM, cp1251, and an empty file.
- [x] 2.3 Implement header matching (strip + casefold, required columns, extra columns ignored) and `detect_format`, including `fmt` mismatch and ambiguous/unknown headers; verify with the header scenarios in specs/statement-import/spec.md.
- [x] 2.4 Implement row parsers for `nova` (existing `parse_amount`, ISO date), `sfera` (space/NBSP thousands, comma decimal, sign rules, strict `DD.MM.YYYY`), and `sfera_split` (unsigned columns, exactly one non-zero, sign is an error, expense negated); verify each scenario in the spec with table-driven tests.
- [x] 2.5 Implement blank and junk row skipping (whitespace/NBSP/delimiter-only rows) and error reporting with the start line of each record; verify with a test that a file with junk and blank lines has empty `errors` and correct `line_no` for a bad row after blank lines.
- [x] 2.6 Implement the two-pass flow: parse all rows, then in strict mode raise `StatementRowError` on the first error before any write; otherwise apply duplicate counting (min(k, n) against the pre-import store snapshot), categorize, and call `store.add_many` once; verify that a strict failure leaves `MemoryStore.all()` and the JSON file unchanged, and that `add_many` is called exactly once.
- [x] 2.7 Implement `import_statement` with the public signature from the ticket and `imported_at` taken once from `clock`; verify `ImportResult` counts satisfy `added + duplicates + len(errors) == data rows` on a mixed file.
- [x] 2.8 Rewrite `import_csv` as a wrapper over `import_statement(fmt="nova", strict=True)` returning `result.added`; verify the existing tests in `tests/test_importer.py` and `tests/test_cli.py` pass unchanged.

## 3. New tests

- [x] 3.1 Add tests for repeated import (adds nothing), overlapping periods, identical rows inside one file, and partially present duplicates; verify with `python -m pytest -q tests/test_importer.py`.
- [x] 3.2 Add a test for `csv.Error` handling (NUL byte in a row) that checks a row error is reported with the record's start line and the store is unchanged in strict mode; verify the test passes.
- [x] 3.3 Add a JSON-store test: strict import with a bad row leaves the JSON file byte-identical; non-strict import writes once and survives a reload with `JsonFileStore`; verify with `python -m pytest -q`.

## 4. Verification

- [x] 4.1 Run the full suite `python -m pytest -q` and confirm no existing test was edited (`git diff --stat tests/` shows only new test code); verify the command output shows zero failures.
- [x] 4.2 Run `openspec validate add-sfera-import --strict` and confirm it reports the change as valid; verify the output.
