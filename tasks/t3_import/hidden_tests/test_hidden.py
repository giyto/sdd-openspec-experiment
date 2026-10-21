"""Приёмочные тесты LEDGER-58: импорт выписок «Сферы», дедупликация, ошибки, strict."""

import dataclasses
import datetime as dt
import inspect
import io
from decimal import Decimal

import pytest

from ledger.errors import StatementError
from ledger.models import Transaction
from ledger.rules import Categorizer, Rule
from ledger.storage import JsonFileStore, MemoryStore

D = dt.date


# Новые имена импортируются внутри тестов, чтобы тесты обратной совместимости
# работали и на коде без доработки.
def import_statement(*args, **kwargs):
    from ledger.importer import import_statement as fn

    return fn(*args, **kwargs)


def detect_format(path):
    from ledger.importer import detect_format as fn

    return fn(path)


def normalize_description(text):
    from ledger.importer import normalize_description as fn

    return fn(text)


def unknown_format_error():
    from ledger.errors import UnknownFormatError

    return UnknownFormatError


def statement_row_error():
    from ledger.errors import StatementRowError

    return StatementRowError


def import_csv(*args, **kwargs):
    from ledger.importer import import_csv as fn

    return fn(*args, **kwargs)


def amounts(store):
    return [t.amount for t in store.all()]


def descriptions(store):
    return [t.description for t in store.all()]


def error_lines(result):
    return [e.line_no for e in result.errors]


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

SFERA_SPLIT = (
    "Дата;Описание;Приход;Расход\n"
    "01.03.2026;Кофейня Зерно;;350,00\n"
    "02.03.2026;Зарплата;85 000,00;\n"
    "03.03.2026;Магазин Лента;;1 200,50\n"
)

EXPECTED = [
    (D(2026, 3, 1), Decimal("-350.00"), "Кофейня Зерно"),
    (D(2026, 3, 2), Decimal("85000.00"), "Зарплата"),
    (D(2026, 3, 3), Decimal("-1200.50"), "Магазин Лента"),
]


def triples(store):
    return [(t.date, t.amount, t.description) for t in store.all()]


# --- R01: import_statement и ImportResult -----------------------------------


def test_R01_nova_via_import_statement(write, clock):
    store = MemoryStore()
    result = import_statement(write(NOVA), store, clock=clock)
    assert result.format == "nova"
    assert result.encoding == "utf-8"
    assert result.added == 3
    assert result.duplicates == 0
    assert list(result.errors) == []
    assert triples(store) == EXPECTED


def test_R01_result_and_row_error_are_frozen_dataclasses(write, clock):
    from ledger.importer import ImportResult, RowError

    assert dataclasses.is_dataclass(ImportResult) and dataclasses.is_dataclass(RowError)
    assert {"format", "encoding", "added", "duplicates", "errors"} <= {f.name for f in dataclasses.fields(ImportResult)}
    assert {"line_no", "message"} <= {f.name for f in dataclasses.fields(RowError)}
    result = import_statement(write(SFERA + "04.03.2026;abc;x\n"), MemoryStore(), clock=clock)
    assert isinstance(result, ImportResult)
    err = list(result.errors)[0]
    assert isinstance(err, RowError) and isinstance(err.message, str) and err.message
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.added = 100
    with pytest.raises(dataclasses.FrozenInstanceError):
        err.line_no = 1


def test_R01_explicit_format(write, clock):
    store = MemoryStore()
    result = import_statement(write(SFERA), store, fmt="sfera", clock=clock)
    assert result.format == "sfera"
    assert result.added == 3
    result = import_statement(write(SFERA_SPLIT), MemoryStore(), fmt="sfera_split", clock=clock)
    assert result.format == "sfera_split"
    assert result.added == 3


# --- R02: формат sfera -------------------------------------------------------


def test_R02_sfera_parsing(write, clock):
    store = MemoryStore()
    result = import_statement(write(SFERA), store, clock=clock)
    assert result.format == "sfera"
    assert triples(store) == EXPECTED


def test_R02_sfera_signs_and_short_fractions(write, clock):
    text = (
        "Дата;Сумма;Описание\n"
        "05.03.2026;+500;Возврат\n"
        "06.03.2026;-12,5;Чай\n"
        "07.03.2026;1 234 567,89;Продажа машины\n"
        "08.03.2026;-7;Проезд\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert list(result.errors) == []
    assert amounts(store) == [Decimal("500.00"), Decimal("-12.50"), Decimal("1234567.89"), Decimal("-7.00")]


def test_R02_nbsp_thousands_separator(write, clock):
    text = "Дата;Сумма;Описание\n10.03.2026;-1 234 567,80;Ремонт\n11.03.2026;2 500,00;Кэшбэк\n"
    store = MemoryStore()
    import_statement(write(text), store, clock=clock)
    assert amounts(store) == [Decimal("-1234567.80"), Decimal("2500.00")]


def test_R02_quoted_description_with_semicolon(write, clock):
    text = 'Дата;Сумма;Описание\n12.03.2026;-990,00;"ООО ""Ромашка""; оплата заказа"\n'
    store = MemoryStore()
    import_statement(write(text), store, clock=clock)
    assert descriptions(store) == ['ООО "Ромашка"; оплата заказа']


# --- R03: строгость сумм и дат «Сферы» ---------------------------------------


def test_R03_dot_in_sfera_amount_is_row_error(write, clock):
    text = "Дата;Сумма;Описание\n01.03.2026;-1 234.56;Мебель\n02.03.2026;-10,00;Хлеб\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [2]
    assert result.added == 1
    assert descriptions(store) == ["Хлеб"]


def test_R03_more_than_two_decimals_is_row_error(write, clock):
    text = "Дата;Сумма;Описание\n01.03.2026;12,345;Странное\n02.03.2026;-1 000,001;Ещё\n03.03.2026;5,10;Ок\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [2, 3]
    assert amounts(store) == [Decimal("5.10")]


def test_R03_bad_dates_are_row_errors(write, clock):
    text = (
        "Дата;Сумма;Описание\n"
        "31.02.2026;-1,00;Нет такого дня\n"
        "2026-03-01;-1,00;ISO в Сфере\n"
        "03/03/2026;-1,00;Слэши\n"
        "04.03.2026;-1,00;Ок\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [2, 3, 4]
    assert [t.date for t in store.all()] == [D(2026, 3, 4)]


# --- R04: формат sfera_split -------------------------------------------------


def test_R04_income_and_expense_columns(write, clock):
    store = MemoryStore()
    result = import_statement(write(SFERA_SPLIT), store, clock=clock)
    assert result.format == "sfera_split"
    assert triples(store) == EXPECTED


def test_R04_zero_in_unused_column_means_empty(write, clock):
    text = (
        "Дата;Описание;Приход;Расход\n"
        "03.03.2026;Такси;0,00;450,00\n"
        "04.03.2026;Кэшбэк;12,30;0,00\n"
        "05.03.2026;Аренда;0,00;45 000,00\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert list(result.errors) == []
    assert amounts(store) == [Decimal("-450.00"), Decimal("12.30"), Decimal("-45000.00")]


def test_R04_both_or_neither_filled_is_row_error(write, clock):
    text = (
        "Дата;Описание;Приход;Расход\n"
        "05.03.2026;Оба;100,00;50,00\n"
        "06.03.2026;Ни одного;;\n"
        "07.03.2026;Нули;0,00;0,00\n"
        "08.03.2026;Ок;;10,00\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [2, 3, 4]
    assert triples(store) == [(D(2026, 3, 8), Decimal("-10.00"), "Ок")]


def test_R04_sign_in_split_columns_is_row_error(write, clock):
    text = (
        "Дата;Описание;Приход;Расход\n"
        "05.03.2026;Минус в расходе;;-150,00\n"
        "06.03.2026;Плюс в приходе;+100,00;\n"
        "07.03.2026;Минус в приходе;-5,00;\n"
        "08.03.2026;Ок;1 000,00;\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [2, 3, 4]
    assert amounts(store) == [Decimal("1000.00")]


# --- R05: определение формата ------------------------------------------------


def test_R05_detect_format(write):
    assert detect_format(write(NOVA)) == "nova"
    assert detect_format(write(SFERA)) == "sfera"
    assert detect_format(write(SFERA_SPLIT)) == "sfera_split"


def test_R05_header_case_order_and_extra_columns(write, clock):
    text = (
        "  описание ;Номер карты; ДАТА;СУММА \n"
        "Кофейня Зерно;*1234;01.03.2026;-350,00\n"
        "Зарплата;*1234;02.03.2026;85 000,00\n"
    )
    path = write(text)
    assert detect_format(path) == "sfera"
    store = MemoryStore()
    result = import_statement(path, store, clock=clock)
    assert result.format == "sfera"
    assert triples(store) == EXPECTED[:2]


def test_R05_split_header_in_other_order(write, clock):
    text = "Расход;Приход;Дата;Описание;Остаток\n350,00;;01.03.2026;Кофейня Зерно;10 000,00\n;85 000,00;02.03.2026;Зарплата;95 000,00\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert result.format == "sfera_split"
    assert triples(store) == EXPECTED[:2]


def test_R05_unknown_header_raises_and_saves_nothing(write, clock, tmp_path):
    UnknownFormatError = unknown_format_error()
    assert issubclass(UnknownFormatError, StatementError)
    path = write("Date;Amount;Memo\n01.03.2026;-1,00;x\n")
    store_path = tmp_path / "ledger.json"
    store = JsonFileStore(store_path)
    for strict in (False, True):
        with pytest.raises(UnknownFormatError):
            import_statement(path, store, strict=strict, clock=clock)
    assert store.all() == []
    assert not store_path.exists()
    with pytest.raises(UnknownFormatError):
        detect_format(path)


def test_R05_explicit_format_mismatch(write, clock):
    UnknownFormatError = unknown_format_error()
    store = MemoryStore()
    with pytest.raises(UnknownFormatError):
        import_statement(write(NOVA), store, fmt="sfera", clock=clock)
    with pytest.raises(UnknownFormatError):
        import_statement(write(SFERA), store, fmt="sfera_split", clock=clock)
    with pytest.raises(UnknownFormatError):
        import_statement(write(SFERA_SPLIT), store, fmt="nova", clock=clock)
    assert store.all() == []


def test_R05_empty_file_is_unknown_format(write, clock):
    UnknownFormatError = unknown_format_error()
    path = write("")
    with pytest.raises(UnknownFormatError):
        detect_format(path)
    with pytest.raises(UnknownFormatError):
        import_statement(path, MemoryStore(), clock=clock)


# --- R06: кодировки ----------------------------------------------------------


def test_R06_utf8_bom_sfera(write, clock):
    path = write(SFERA, bom=True)
    assert detect_format(path) == "sfera"
    store = MemoryStore()
    result = import_statement(path, store, clock=clock)
    assert result.format == "sfera"
    assert result.encoding == "utf-8"
    assert triples(store) == EXPECTED


def test_R06_utf8_bom_nova(write, clock):
    store = MemoryStore()
    result = import_statement(write(NOVA, bom=True), store, clock=clock)
    assert (result.format, result.encoding, result.added) == ("nova", "utf-8", 3)
    assert triples(store) == EXPECTED


def test_R06_cp1251_sfera_with_nbsp(write, clock):
    text = SFERA.replace("85 000,00", "85 000,00")
    path = write(text, encoding="cp1251")
    assert detect_format(path) == "sfera"
    store = MemoryStore()
    result = import_statement(path, store, clock=clock)
    assert result.encoding == "cp1251"
    assert result.format == "sfera"
    assert triples(store) == EXPECTED


def test_R06_encoding_detected_for_whole_file(write, clock):
    # Заголовок чисто ASCII, кириллица только в последней строке.
    text = (
        "date,amount,description\n"
        "2026-03-01,-350.00,Coffee\n"
        "2026-03-02,85000.00,Salary\n"
        "2026-03-03,-1200.50,Магазин «Лента» №5\n"
    )
    path = write(text, encoding="cp1251")
    assert detect_format(path) == "nova"
    store = MemoryStore()
    result = import_statement(path, store, clock=clock)
    assert result.encoding == "cp1251"
    assert descriptions(store) == ["Coffee", "Salary", "Магазин «Лента» №5"]


def test_R06_cp1251_split(write, clock):
    store = MemoryStore()
    result = import_statement(write(SFERA_SPLIT, encoding="cp1251"), store, clock=clock)
    assert (result.format, result.encoding) == ("sfera_split", "cp1251")
    assert triples(store) == EXPECTED


# --- R07: дедупликация с хранилищем -----------------------------------------


def test_R07_normalize_description():
    assert normalize_description("  Кофейня   «Зёрна»\t№5 ") == "кофейня «зерна» №5"
    assert normalize_description("ЁЛКА  Ёжик") == "елка ежик"
    assert normalize_description("Straße") == "strasse"
    assert normalize_description("a\n\nb") == "a b"


def test_R07_skips_transactions_already_in_store(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 1), Decimal("-350.00"), "  КОФЕЙНЯ   зерно"))
    result = import_statement(write(SFERA), store, clock=clock)
    assert result.added == 2
    assert result.duplicates == 1
    assert descriptions(store) == ["  КОФЕЙНЯ   зерно", "Зарплата", "Магазин Лента"]


def test_R07_yo_and_case_do_not_matter(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 5), Decimal("-89.90"), "ПЯТЕРОЧКА"))
    text = "Дата;Сумма;Описание\n05.03.2026;-89,90;Пятёрочка\n"
    result = import_statement(write(text), store, clock=clock)
    assert (result.added, result.duplicates) == (0, 1)
    assert len(store.all()) == 1


def test_R07_key_includes_date_and_amount(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 1), Decimal("-350.00"), "Кофейня Зерно"))
    text = (
        "Дата;Сумма;Описание\n"
        "02.03.2026;-350,00;Кофейня Зерно\n"
        "01.03.2026;-351,00;Кофейня Зерно\n"
        "01.03.2026;350,00;Кофейня Зерно\n"
    )
    result = import_statement(write(text), store, clock=clock)
    assert (result.added, result.duplicates) == (3, 0)


def test_R07_dedup_across_formats(write, clock):
    store = MemoryStore()
    first = import_statement(write(NOVA), store, clock=clock)
    second = import_statement(write(SFERA, encoding="cp1251"), store, clock=clock)
    third = import_statement(write(SFERA_SPLIT, bom=True), store, clock=clock)
    assert first.added == 3
    assert (second.added, second.duplicates) == (0, 3)
    assert (third.added, third.duplicates) == (0, 3)
    assert len(store.all()) == 3


# --- R08: дубли внутри файла и подсчёт по количеству -------------------------

COFFEE_TWICE = (
    "Дата;Сумма;Описание\n"
    "01.03.2026;-150,00;Кофе\n"
    "01.03.2026;-150,00;Кофе\n"
    "01.03.2026;-90,00;Круассан\n"
)


def test_R08_identical_rows_in_one_file_are_not_duplicates(write, clock):
    store = MemoryStore()
    result = import_statement(write(COFFEE_TWICE), store, clock=clock)
    assert (result.added, result.duplicates) == (3, 0)
    assert amounts(store) == [Decimal("-150.00"), Decimal("-150.00"), Decimal("-90.00")]


def test_R08_reimport_same_file_adds_nothing(write, clock):
    store = MemoryStore()
    path = write(COFFEE_TWICE)
    import_statement(path, store, clock=clock)
    again = import_statement(path, store, clock=clock)
    assert (again.added, again.duplicates) == (0, 3)
    assert len(store.all()) == 3


def test_R08_duplicates_are_counted_by_quantity(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 1), Decimal("-150.00"), "кофе"))
    text = COFFEE_TWICE + "01.03.2026;-150,00;КОФЕ\n"
    result = import_statement(write(text), store, clock=clock)
    assert (result.added, result.duplicates) == (3, 1)
    assert sorted(descriptions(store)) == sorted(["кофе", "Кофе", "КОФЕ", "Круассан"])


def test_R08_overlapping_period_adds_only_new(write, clock):
    store = MemoryStore()
    first = "Дата;Сумма;Описание\n" + "".join(f"0{d}.03.2026;-{d}0,00;Обед\n" for d in (1, 2, 3))
    second = "Дата;Сумма;Описание\n" + "".join(f"0{d}.03.2026;-{d}0,00;Обед\n" for d in (2, 3, 4, 5))
    import_statement(write(first), store, clock=clock)
    result = import_statement(write(second), store, clock=clock)
    assert (result.added, result.duplicates) == (2, 2)
    assert [t.date.day for t in store.all()] == [1, 2, 3, 4, 5]


# --- R09: ошибки строк в обычном режиме -------------------------------------


def test_R09_errors_collected_and_valid_rows_imported(write, clock):
    text = (
        "Дата;Сумма;Описание\n"
        "01.03.2026;-350,00;Кофейня Зерно\n"
        "32.03.2026;-1,00;Плохая дата\n"
        "02.03.2026;85 000,00;Зарплата\n"
        "03.03.2026;много;Плохая сумма\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert result.added == 2
    assert error_lines(result) == [3, 5]
    assert all(isinstance(e.message, str) and e.message for e in result.errors)
    assert triples(store) == EXPECTED[:2]


def test_R09_line_numbers_count_blank_lines(write, clock):
    text = (
        "Дата;Сумма;Описание\n"  # 1
        "01.03.2026;-350,00;Кофейня Зерно\n"  # 2
        "\n"  # 3
        "   \n"  # 4
        ";;\n"  # 5
        "01.03.2026;oops;Ошибка\n"  # 6
        "02.03.2026;85 000,00;Зарплата\n"  # 7
        "\n"  # 8
        "xx.03.2026;-1,00;Ошибка\n"  # 9
    )
    for kwargs in ({}, {"bom": True}, {"encoding": "cp1251"}):
        result = import_statement(write(text, **kwargs), MemoryStore(), clock=clock)
        assert error_lines(result) == [6, 9]
        assert result.added == 2


def test_R09_zero_amount_and_empty_description_are_row_errors(write, clock):
    text = (
        "Дата;Сумма;Описание\n"
        "01.03.2026;0,00;Ноль\n"
        "02.03.2026;-5,00;   \n"
        "03.03.2026;-5,00;Ок\n"
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [2, 3]
    assert descriptions(store) == ["Ок"]


def test_R09_missing_fields_is_row_error(write, clock):
    text = "date,amount,description\n2026-03-01,-5.00\n2026-03-02,-6.00,Ок\n2026-03-03\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [2, 4]
    assert descriptions(store) == ["Ок"]


def test_R09_multiline_record_line_number(write, clock):
    text = (
        "Дата;Сумма;Описание\n"  # 1
        '01.03.2026;-100,00;"Перевод\nпо договору 7"\n'  # 2-3
        "02.03.2026;-1,00x;Ошибка\n"  # 4
        '32.03.2026;-5,00;"Ещё\nодин перевод"\n'  # 5-6
        "03.03.2026;-2,00;Ок\n"  # 7
    )
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert error_lines(result) == [4, 5]
    assert descriptions(store) == ["Перевод\nпо договору 7", "Ок"]


# --- R10: строгий режим ------------------------------------------------------

STRICT_BAD = (
    "Дата;Сумма;Описание\n"  # 1
    "01.03.2026;-350,00;Кофейня Зерно\n"  # 2
    "02.03.2026;85 000,00;Зарплата\n"  # 3
    "03.03.2026;-1 200.50;Магазин Лента\n"  # 4 - точка
    "04.03.2026;;Пусто\n"  # 5
)


def test_R10_strict_raises_row_error_with_line(write, clock):
    StatementRowError = statement_row_error()
    assert issubclass(StatementRowError, StatementError)
    with pytest.raises(StatementRowError) as info:
        import_statement(write(STRICT_BAD), MemoryStore(), strict=True, clock=clock)
    assert info.value.line_no == 4


def test_R10_strict_saves_nothing_in_memory(write, clock):
    StatementRowError = statement_row_error()
    store = MemoryStore()
    store.add(Transaction(D(2026, 2, 1), Decimal("-1.00"), "Было до"))
    before = store.all()
    with pytest.raises(StatementRowError):
        import_statement(write(STRICT_BAD), store, strict=True, clock=clock)
    assert store.all() == before


def test_R10_strict_saves_nothing_in_json_file(write, clock, tmp_path):
    StatementRowError = statement_row_error()
    store_path = tmp_path / "ledger.json"
    store = JsonFileStore(store_path)
    store.add(Transaction(D(2026, 2, 1), Decimal("-1.00"), "Было до"))
    snapshot = store_path.read_bytes()
    with pytest.raises(StatementRowError):
        import_statement(write(STRICT_BAD, encoding="cp1251"), store, strict=True, clock=clock)
    assert store_path.read_bytes() == snapshot
    assert len(JsonFileStore(store_path).all()) == 1
    assert len(store.all()) == 1


def test_R10_strict_allows_duplicates_and_blank_lines(write, clock):
    store = MemoryStore()
    import_statement(write(SFERA), store, clock=clock)
    text = SFERA + "04.03.2026;-10,00;Новое\n\n;;\n   \n"
    result = import_statement(write(text), store, strict=True, clock=clock)
    assert (result.added, result.duplicates) == (1, 3)
    assert list(result.errors) == []
    assert len(store.all()) == 4


def test_R10_strict_row_error_on_split_rule(write, clock):
    StatementRowError = statement_row_error()
    text = SFERA_SPLIT + "\n04.03.2026;Оба;1,00;2,00\n"
    store = MemoryStore()
    with pytest.raises(StatementRowError) as info:
        import_statement(write(text, bom=True), store, strict=True, clock=clock)
    assert info.value.line_no == 6
    assert store.all() == []


# --- R11: пустые строки ------------------------------------------------------


def test_R11_trailing_blank_lines_ignored(write, clock):
    for tail in ("\n\n\n", ";;\n;;\n", "   \n \t \n", " ; ; \n\n"):
        store = MemoryStore()
        result = import_statement(write(SFERA + tail), store, clock=clock)
        assert (result.added, result.duplicates, list(result.errors)) == (3, 0, [])


def test_R11_blank_lines_in_nova(write, clock):
    text = "date,amount,description\n,,\n2026-03-01,-350.00,Кофейня Зерно\n  ,  , \n\n2026-03-02,85000.00,Зарплата\n,,\n"
    store = MemoryStore()
    result = import_statement(write(text), store, clock=clock)
    assert result.added == 2
    assert list(result.errors) == []


def test_R11_header_only_file(write, clock):
    store = MemoryStore()
    result = import_statement(write("Дата;Описание;Приход;Расход\n\n;;;\n"), store, clock=clock)
    assert result.format == "sfera_split"
    assert (result.added, result.duplicates, list(result.errors)) == (0, 0, [])
    assert store.all() == []


def test_R11_crlf_line_endings(write, clock):
    text = SFERA.replace("\n", "\r\n") + "\r\n;;\r\n"
    store = MemoryStore()
    result = import_statement(write(text, encoding="cp1251"), store, clock=clock)
    assert (result.added, list(result.errors)) == (3, [])
    assert triples(store) == EXPECTED


# --- R12: содержимое импортированных транзакций ------------------------------


def test_R12_description_stored_as_in_file(write, clock):
    text = "Дата;Сумма;Описание\n01.03.2026;-89,90;  ПЯТЁРОЧКА   №12  \n"
    store = MemoryStore()
    import_statement(write(text), store, clock=clock)
    assert descriptions(store) == ["ПЯТЁРОЧКА   №12"]


def test_R12_categorizer_applied(write, clock):
    cat = Categorizer([Rule("кофейня", "cafe"), Rule("зарплата", "salary", kind="income")])
    store = MemoryStore()
    import_statement(write(SFERA_SPLIT, encoding="cp1251"), store, categorizer=cat, clock=clock)
    assert [t.category for t in store.all()] == ["cafe", "salary", None]


def test_R12_imported_at_from_clock(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 2, 1), Decimal("-1.00"), "Ручная"))
    import_statement(write(SFERA), store, clock=clock)
    imported = store.all()[1:]
    assert len(imported) == 3
    assert all(t.imported_at == clock.now() for t in imported)
    assert store.all()[0].imported_at is None


def test_R12_duplicates_do_not_change_existing(write, clock):
    store = MemoryStore()
    store.add(Transaction(D(2026, 3, 1), Decimal("-350.00"), "кофейня зерно", category="manual"))
    cat = Categorizer([Rule("кофейня", "cafe")])
    result = import_statement(write(SFERA), store, categorizer=cat, clock=clock)
    assert result.duplicates == 1
    first = store.all()[0]
    assert (first.description, first.category, first.imported_at) == ("кофейня зерно", "manual", None)


# --- R13: import_csv через новый механизм -----------------------------------


def test_R13_import_csv_reimport_adds_nothing(write, clock):
    store = MemoryStore()
    path = write(NOVA)
    assert import_csv(path, store, clock=clock) == 3
    assert import_csv(path, store, clock=clock) == 0
    assert len(store.all()) == 3


def test_R13_import_csv_bom_and_cp1251(write, clock):
    store = MemoryStore()
    assert import_csv(write(NOVA, bom=True), store, clock=clock) == 3
    other = MemoryStore()
    assert import_csv(write(NOVA, encoding="cp1251"), other, clock=clock) == 3
    assert triples(store) == triples(other) == EXPECTED


def test_R13_import_csv_is_atomic(write, clock, tmp_path):
    text = NOVA + "2026-03-04,abc,Плохая\n"
    store = MemoryStore()
    with pytest.raises(StatementError) as info:
        import_csv(write(text), store, clock=clock)
    assert info.value.line_no == 5
    assert store.all() == []
    store_path = tmp_path / "ledger.json"
    json_store = JsonFileStore(store_path)
    with pytest.raises(StatementError):
        import_csv(write(text), json_store, clock=clock)
    assert not store_path.exists() or JsonFileStore(store_path).all() == []


def test_R13_import_csv_skips_blank_lines(write, clock):
    text = "date,amount,description\n2026-03-01,-350.00,Кофейня Зерно\n   \n,,\n2026-03-02,85000.00,Зарплата\n\n"
    store = MemoryStore()
    assert import_csv(write(text), store, clock=clock) == 2


# --- обратная совместимость --------------------------------------------------


def test_API_import_csv_signature():
    from ledger.importer import import_csv as fn

    params = inspect.signature(fn).parameters
    assert list(params)[:4] == ["path", "store", "categorizer", "clock"]
    assert params["categorizer"].default is None
    assert params["clock"].default is None


def test_API_import_csv_returns_int(write, clock):
    store = MemoryStore()
    cat = Categorizer([Rule("кофейня", "cafe")])
    count = import_csv(write(NOVA), store, cat, clock)
    assert type(count) is int and count == 3
    assert triples(store) == EXPECTED
    assert [t.category for t in store.all()] == ["cafe", None, None]
    assert all(t.imported_at == clock.now() for t in store.all())


def test_API_import_csv_errors_are_statement_errors(write, clock):
    with pytest.raises(StatementError) as info:
        import_csv(write("date,amount,description\n2026-03-01,-1.00,ok\n2026-03-02,x,bad\n"), MemoryStore(), clock=clock)
    assert info.value.line_no == 3
    with pytest.raises(StatementError):
        import_csv(write(SFERA), MemoryStore(), clock=clock)


def test_API_cli_import_still_works(write, clock, tmp_path):
    from ledger.cli import main

    out, err = io.StringIO(), io.StringIO()
    store_path = tmp_path / "ledger.json"
    code = main(["--store", str(store_path), "import", str(write(NOVA))], clock=clock, out=out, err=err)
    assert code == 0
    assert out.getvalue().strip() == "Imported 3 transactions"
    assert len(JsonFileStore(store_path).all()) == 3


def test_API_models_and_storage_unchanged():
    assert [f.name for f in dataclasses.fields(Transaction)] == [
        "date", "amount", "description", "category", "imported_at", "id",
    ]
    for name in ("add", "add_many", "all", "get", "update_category"):
        assert callable(getattr(MemoryStore, name))
    from ledger.reports import format_summary, monthly_summary

    s = monthly_summary([Transaction(D(2026, 3, 1), Decimal("-5.00"), "x", category="c")], 2026, 3)
    assert "c  -5.00" in format_summary(s)
