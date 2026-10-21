"""Приёмочные тесты LEDGER-74: доработки импорта выписок (этап 2)."""

import datetime as dt
from decimal import Decimal

import pytest

from ledger.errors import StatementError
from ledger.models import Transaction
from ledger.rules import Categorizer, Rule
from ledger.storage import JsonFileStore, MemoryStore

D = dt.date


def import_statement(*args, **kwargs):
    from ledger.importer import import_statement as fn

    return fn(*args, **kwargs)


def import_csv(*args, **kwargs):
    from ledger.importer import import_csv as fn

    return fn(*args, **kwargs)


def statement_row_error():
    from ledger.errors import StatementRowError

    return StatementRowError


def unknown_format_error():
    from ledger.errors import UnknownFormatError

    return UnknownFormatError


def amounts(store_or_list):
    items = store_or_list.all() if hasattr(store_or_list, "all") else store_or_list
    return [t.amount for t in items]


def descriptions(store_or_list):
    items = store_or_list.all() if hasattr(store_or_list, "all") else store_or_list
    return [t.description for t in items]


def error_lines(errors):
    return [e.line_no for e in errors]


NOVA = (
    "date,amount,description\n"
    "2026-03-01,-350.00,Кофейня Зерно\n"
    "2026-03-02,85000.00,Зарплата\n"
    "2026-03-03,-1200.5,Магазин Лента\n"
)

SFERA = (
    "Дата;Сумма;Описание\n"
    "01.03.2026;-350,00;Кофейня Зерно\n"
    "02.03.2026;85 000,00;Зарплата\n"
    "03.03.2026;-1 200,50;Магазин Лента\n"
)

EXPECTED = [
    (D(2026, 3, 1), Decimal("-350.00"), "Кофейня Зерно"),
    (D(2026, 3, 2), Decimal("85000.00"), "Зарплата"),
    (D(2026, 3, 3), Decimal("-1200.50"), "Магазин Лента"),
]


def triples(items):
    items = items.all() if hasattr(items, "all") else items
    return [(t.date, t.amount, t.description) for t in items]


# --- C01: точка как десятичный разделитель в «Сфере» -------------------------


def test_C01_dot_decimal_in_sfera(write, clock):
    text = (
        "Дата;Сумма;Описание\n"
        "01.03.2026;-1 234.56;Мебель\n"
        "02.03.2026;85 000.00;Зарплата\n"
        "03.03.2026;+12.5;Кэшбэк\n"
        "04.03.2026;-7;Проезд\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert list(result.errors) == []
    assert amounts(store) == [Decimal("-1234.56"), Decimal("85000.00"), Decimal("12.50"), Decimal("-7.00")]


def test_C01_dot_decimal_in_sfera_split(write, clock):
    text = (
        "Дата;Описание;Приход;Расход\n"
        "01.03.2026;Кофейня Зерно;;350.00\n"
        "02.03.2026;Зарплата;85 000.00;\n"
        "03.03.2026;Магазин Лента;;1 200,50\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert list(result.errors) == []
    assert triples(store) == EXPECTED


def test_C01_comma_still_works_and_mixed_separators_are_errors(write, clock):
    text = (
        "Дата;Сумма;Описание\n"
        "01.03.2026;-10,00;Запятая\n"
        "02.03.2026;1.234,56;Точка и запятая\n"
        "03.03.2026;-1,234.56;Запятая и точка\n"
        "04.03.2026;-20.00;Точка\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result.errors) == [3, 4]
    assert amounts(store) == [Decimal("-10.00"), Decimal("-20.00")]


# --- C02: нули в обеих колонках sfera_split — служебная строка ---------------


def test_C02_zero_in_both_columns_is_skipped(write, clock):
    text = (
        "Дата;Описание;Приход;Расход\n"
        "01.03.2026;Блокировка;0,00;0,00\n"
        "02.03.2026;Кофе;;150,00\n"
        "03.03.2026;Блокировка;0.00;0.00\n"
        "04.03.2026;Блокировка;0,00;0.00\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert (result.added, result.duplicates, list(result.errors)) == (1, 0, [])
    assert descriptions(store) == ["Кофе"]


def test_C02_zero_and_empty_is_still_error(write, clock):
    text = (
        "Дата;Описание;Приход;Расход\n"
        "01.03.2026;Ноль и пусто;0,00;\n"
        "02.03.2026;Пусто и ноль;;0.00\n"
        "03.03.2026;Пусто;;\n"
        "04.03.2026;Ок;;1,00\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result.errors) == [2, 3, 4]
    assert descriptions(store) == ["Ок"]


def test_C02_zero_rows_do_not_break_strict(write, clock):
    text = "Дата;Описание;Приход;Расход\n01.03.2026;Блокировка;0,00;0,00\n02.03.2026;Кофе;;150,00\n"
    store = MemoryStore()
    result = import_statement(write(text), store, strict=True, clock=clock)
    assert result.added == 1
    assert list(result.errors) == []


# --- C03: описание сохраняется со схлопнутыми пробелами ---------------------


def test_C03_spaces_collapsed_case_kept(write, clock):
    text = "Дата;Сумма;Описание\n01.03.2026;-89,90;  ПЯТЁРОЧКА   №12  \n02.03.2026;-5,00;Ёлки   Палки\n"
    store = MemoryStore()
    import_statement(write(text), store, clock=clock)
    assert descriptions(store) == ["ПЯТЁРОЧКА №12", "Ёлки Палки"]


def test_C03_newlines_and_tabs_collapsed(write, clock):
    text = 'Дата;Сумма;Описание\n01.03.2026;-100,00;"Перевод\nпо договору\t\t7"\n02.03.2026;-2,00;Ок\n'
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert list(result.errors) == []
    assert descriptions(store) == ["Перевод по договору 7", "Ок"]


def test_C03_collapse_in_nova_and_cp1251(write, clock):
    text = "date,amount,description\n2026-03-01,-350.00,  Кофейня \t Зерно \n"
    store = MemoryStore()
    import_statement(write(text, encoding="cp1251"), store, clock=clock)
    assert descriptions(store) == ["Кофейня Зерно"]


# --- C04: строгий режим сообщает обо всех ошибках ---------------------------

STRICT_MANY = (
    "Дата;Сумма;Описание\n"  # 1
    "01.03.2026;-350,00;Кофейня Зерно\n"  # 2
    "32.03.2026;-1,00;Плохая дата\n"  # 3
    "02.03.2026;85 000,00;Зарплата\n"  # 4
    "03.03.2026;много;Плохая сумма\n"  # 5
    "\n"  # 6
    "04.03.2026;0,00;Ноль\n"  # 7
)


def test_C04_strict_reports_all_errors(write, clock):
    StatementRowError = statement_row_error()
    from ledger.importer import RowError

    with pytest.raises(StatementRowError) as info:
        import_statement(write(STRICT_MANY), MemoryStore(), strict=True, clock=clock)
    exc = info.value
    assert isinstance(exc, StatementError)
    assert exc.line_no == 3
    assert error_lines(exc.errors) == [3, 5, 7]
    assert all(isinstance(e, RowError) and e.message for e in exc.errors)


def test_C04_strict_with_all_errors_is_still_atomic(write, clock, tmp_path):
    StatementRowError = statement_row_error()
    store_path = tmp_path / "ledger.json"
    store = JsonFileStore(store_path)
    store.add(Transaction(D(2026, 2, 1), Decimal("-1.00"), "Было до"))
    snapshot = store_path.read_bytes()
    with pytest.raises(StatementRowError) as info:
        import_statement(write(STRICT_MANY, encoding="cp1251"), store, strict=True, clock=clock)
    assert len(info.value.errors) == 3
    assert store_path.read_bytes() == snapshot
    assert len(store.all()) == 1


def test_C04_import_csv_strict_reports_all_errors(write, clock):
    StatementRowError = statement_row_error()
    text = NOVA + "2026-03-04,abc,Плохая\n2026-03-05,-1.00,  \n"
    store = MemoryStore()
    with pytest.raises(StatementRowError) as info:
        import_csv(write(text), store, clock=clock)
    assert info.value.line_no == 5
    assert error_lines(info.value.errors) == [5, 6]
    assert store.all() == []


# --- C05: dry_run ------------------------------------------------------------


def test_C05_dry_run_saves_nothing(write, clock):
    store = MemoryStore()
    result = import_statement(write(SFERA), store, dry_run=True, clock=clock)
    assert (result.format, result.added, result.duplicates) == ("sfera", 3, 0)
    assert store.all() == []


def test_C05_dry_run_leaves_json_file_untouched(write, clock, tmp_path):
    new_path = tmp_path / "new.json"
    import_statement(write(SFERA), JsonFileStore(new_path), dry_run=True, clock=clock)
    assert not new_path.exists()

    store_path = tmp_path / "ledger.json"
    store = JsonFileStore(store_path)
    store.add(Transaction(D(2026, 2, 1), Decimal("-1.00"), "Было до"))
    snapshot = store_path.read_bytes()
    result = import_statement(write(NOVA), store, dry_run=True, clock=clock)
    assert result.added == 3
    assert store_path.read_bytes() == snapshot
    assert len(JsonFileStore(store_path).all()) == 1


def test_C05_dry_run_transactions_without_ids(write, clock):
    result = import_statement(write(SFERA), MemoryStore(), dry_run=True, clock=clock)
    assert triples(result.transactions) == EXPECTED
    assert all(t.id is None for t in result.transactions)


# --- C06: ImportResult.transactions -------------------------------------------


def test_C06_transactions_with_store_ids_in_file_order(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 2, 1), Decimal("-1.00"), "Было до"))
    result = import_statement(write(SFERA), store, clock=clock)
    assert [t.id for t in result.transactions] == [2, 3, 4]
    assert list(result.transactions) == store.all()[1:]
    assert triples(result.transactions) == EXPECTED


def test_C06_transactions_exclude_duplicates_and_errors(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 1), Decimal("-350.00"), "кофейня зерно"))
    text = SFERA + "04.03.2026;oops;Ошибка\n05.03.2026;-10,00;Новое\n"
    result = import_statement(write(text), store, clock=clock)
    assert (result.added, result.duplicates) == (3, 1)
    assert descriptions(result.transactions) == ["Зарплата", "Магазин Лента", "Новое"]
    assert len(result.transactions) == result.added


def test_C06_transactions_carry_category_and_imported_at(write, clock):
    cat = Categorizer([Rule("кофейня", "cafe"), Rule("зарплата", "salary", kind="income")])
    result = import_statement(write(SFERA), MemoryStore(), categorizer=cat, clock=clock)
    assert [t.category for t in result.transactions] == ["cafe", "salary", None]
    assert all(t.imported_at == clock.now() for t in result.transactions)


# --- C07: RowError.raw -------------------------------------------------------


def test_C07_raw_is_line_text(write, clock):
    text = "Дата;Сумма;Описание\n01.03.2026;-1,00;Ок\n32.03.2026;-1,00;Плохая дата\n"
    result = import_statement(write(text), MemoryStore(), clock=clock)
    [err] = result.errors
    assert err.line_no == 3
    assert err.raw == "32.03.2026;-1,00;Плохая дата"


def test_C07_raw_multiline_crlf_cp1251(write, clock):
    text = (
        "Дата;Сумма;Описание\r\n"  # 1
        '01.03.2026;-100,00;"Перевод\r\nпо договору"\r\n'  # 2-3
        '32.03.2026;-5,00;"Ещё\r\nодин перевод"\r\n'  # 4-5
        "02.03.2026;плохо;№7 «Лента»\r\n"  # 6
    )
    result = import_statement(write(text, encoding="cp1251"), MemoryStore(), clock=clock)
    assert result.encoding == "cp1251"
    assert error_lines(result.errors) == [4, 6]
    assert [e.raw for e in result.errors] == [
        '32.03.2026;-5,00;"Ещё\nодин перевод"',
        "02.03.2026;плохо;№7 «Лента»",
    ]


def test_C07_raw_in_bom_file_and_nova(write, clock):
    text = "date,amount,description\n2026-03-01,x,Плохая сумма\n2026-03-02,-1.00,Ок\n"
    result = import_statement(write(text, bom=True), MemoryStore(), clock=clock)
    [err] = result.errors
    assert err.raw == "2026-03-01,x,Плохая сумма"


def test_C07_raw_in_strict_errors(write, clock):
    StatementRowError = statement_row_error()
    with pytest.raises(StatementRowError) as info:
        import_statement(write(STRICT_MANY), MemoryStore(), strict=True, clock=clock)
    assert [e.raw for e in info.value.errors] == [
        "32.03.2026;-1,00;Плохая дата",
        "03.03.2026;много;Плохая сумма",
        "04.03.2026;0,00;Ноль",
    ]


# --- C08: dry_run и прежние правила импорта ----------------------------------


def test_C08_dry_run_matches_real_import(write, clock):
    text = (
        "Дата;Сумма;Описание\n"
        "01.03.2026;-150,00;Кофе\n"
        "01.03.2026;-150,00;Кофе\n"
        "01.03.2026;-150,00;КОФЕ\n"
        "\n"
        "02.03.2026;oops;Ошибка\n"
        ";;\n"
        "03.03.2026;-90,00;Круассан\n"
    )
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 1), Decimal("-150.00"), "кофе"))
    path = write(text)
    preview = import_statement(path, store, dry_run=True, clock=clock)
    assert len(store.all()) == 1
    real = import_statement(path, store, clock=clock)
    assert (preview.added, preview.duplicates) == (real.added, real.duplicates) == (3, 1)
    assert error_lines(preview.errors) == error_lines(real.errors) == [6]
    assert triples(preview.transactions) == triples(real.transactions)


def test_C08_dry_run_after_import_reports_duplicates(write, clock):
    store = MemoryStore()
    path = write(SFERA)
    import_statement(path, store, clock=clock)
    preview = import_statement(path, store, dry_run=True, clock=clock)
    assert (preview.added, preview.duplicates, list(preview.transactions)) == (0, 3, [])


def test_C08_dry_run_strict_and_unknown_format_still_raise(write, clock):
    StatementRowError = statement_row_error()
    UnknownFormatError = unknown_format_error()
    store = MemoryStore()
    with pytest.raises(StatementRowError):
        import_statement(write(STRICT_MANY), store, strict=True, dry_run=True, clock=clock)
    with pytest.raises(UnknownFormatError):
        import_statement(write("Date;Amount\n1;2\n"), store, dry_run=True, clock=clock)
    assert store.all() == []


# --- C09: суммы с точкой и прежние правила сумм ------------------------------


def test_C09_more_than_two_decimals_with_dot_is_error(write, clock):
    text = "Дата;Сумма;Описание\n01.03.2026;-1 234.567;Много знаков\n02.03.2026;12.345;Тоже\n03.03.2026;5.1;Ок\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result.errors) == [2, 3]
    assert amounts(store) == [Decimal("5.10")]


def test_C09_zero_with_dot_in_unused_column_means_empty(write, clock):
    text = "Дата;Описание;Приход;Расход\n01.03.2026;Такси;0.00;450.00\n02.03.2026;Кэшбэк;12.30;0.00\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert list(result.errors) == []
    assert amounts(store) == [Decimal("-450.00"), Decimal("12.30")]


def test_C09_sign_with_dot_in_split_columns_is_error(write, clock):
    text = "Дата;Описание;Приход;Расход\n01.03.2026;Минус;;-150.00\n02.03.2026;Плюс;+1.00;\n03.03.2026;Ок;;2.00\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result.errors) == [2, 3]
    assert amounts(store) == [Decimal("-2.00")]


def test_C09_dot_amounts_dedup_across_formats(write, clock):
    store = MemoryStore()
    import_statement(write(NOVA), store, clock=clock)
    text = (
        "Дата;Сумма;Описание\n"
        "01.03.2026;-350.00;Кофейня Зерно\n"
        "02.03.2026;85 000.00;Зарплата\n"
        "03.03.2026;-1 200.5;Магазин Лента\n"
    )
    result = import_statement(write(text, encoding="cp1251"), store, clock=clock)
    assert (result.added, result.duplicates) == (0, 3)


# --- C10: схлопнутые описания и прежние правила ------------------------------


def test_C10_import_csv_collapses_description(write, clock):
    text = "date,amount,description\n2026-03-01,-350.00,Кофейня    Зерно\n2026-03-02,-5.00,\"Чай\nс лимоном\"\n"
    store = MemoryStore()
    count = import_csv(write(text), store, clock=clock)
    assert type(count) is int and count == 2
    assert descriptions(store) == ["Кофейня Зерно", "Чай с лимоном"]


def test_C10_dedup_with_previously_stored_descriptions(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 1), Decimal("-350.00"), "Кофейня   Зерно"))
    text = "Дата;Сумма;Описание\n01.03.2026;-350,00;Кофейня Зерно\n01.03.2026;-350,00;кофейня\tзерно\n"
    path = write(text)
    first = import_statement(path, store, clock=clock)
    assert (first.added, first.duplicates) == (1, 1)
    second = import_statement(path, store, clock=clock)
    assert (second.added, second.duplicates) == (0, 2)
    assert descriptions(store) == ["Кофейня   Зерно", "кофейня зерно"]


def test_C10_categorizer_sees_collapsed_description(write, clock):
    cat = Categorizer([Rule("кофейня зерно", "cafe")])
    text = 'Дата;Сумма;Описание\n01.03.2026;-350,00;"Кофейня\n  Зерно"\n'
    store = MemoryStore()
    import_statement(write(text), store, categorizer=cat, clock=clock)
    assert [(t.description, t.category) for t in store.all()] == [("Кофейня Зерно", "cafe")]
