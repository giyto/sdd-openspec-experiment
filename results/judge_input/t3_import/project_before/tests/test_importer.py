import datetime as dt
from decimal import Decimal

import pytest

from ledger.errors import StatementError
from ledger.importer import import_csv
from ledger.rules import Categorizer, Rule
from ledger.storage import MemoryStore

NOVA = (
    "date,amount,description\n"
    "2026-03-01,-350.00,Кофейня Зерно\n"
    "2026-03-02,85000.00,Зарплата\n"
    "2026-03-03,-1200.5,\"Магазин \"\"Лента\"\", чек 42\"\n"
)


def test_import_nova_statement(write_csv, clock):
    store = MemoryStore()
    count = import_csv(write_csv(NOVA), store, clock=clock)
    assert count == 3
    txs = store.all()
    assert [t.amount for t in txs] == [Decimal("-350.00"), Decimal("85000.00"), Decimal("-1200.50")]
    assert txs[0].date == dt.date(2026, 3, 1)
    assert txs[2].description == 'Магазин "Лента", чек 42'
    assert all(t.imported_at == clock.now() for t in txs)


def test_import_applies_categorizer(write_csv, clock):
    store = MemoryStore()
    cat = Categorizer([Rule("кофейня", "cafe"), Rule("зарплата", "salary", kind="income")])
    import_csv(write_csv(NOVA), store, categorizer=cat, clock=clock)
    assert [t.category for t in store.all()] == ["cafe", "salary", None]


def test_import_header_only(write_csv, clock):
    store = MemoryStore()
    assert import_csv(write_csv("date,amount,description\n"), store, clock=clock) == 0
    assert store.all() == []


def test_import_missing_column(write_csv, clock):
    with pytest.raises(StatementError) as info:
        import_csv(write_csv("date,sum,description\n2026-03-01,-1.00,x\n"), MemoryStore(), clock=clock)
    assert info.value.line_no == 1


@pytest.mark.parametrize(
    "row",
    ["2026-13-01,-1.00,x", "2026-03-01,abc,x", "2026-03-01,0.00,x", "2026-03-01,-1.00,  "],
)
def test_import_bad_row_reports_line(write_csv, clock, row):
    text = "date,amount,description\n2026-03-01,-1.00,ok\n" + row + "\n"
    with pytest.raises(StatementError) as info:
        import_csv(write_csv(text), MemoryStore(), clock=clock)
    assert info.value.line_no == 3
