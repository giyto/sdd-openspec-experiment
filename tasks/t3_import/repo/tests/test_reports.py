import datetime as dt
from decimal import Decimal

from ledger.models import Transaction
from ledger.reports import format_summary, monthly_summary


def _tx(day, amount, category=None, month=3):
    return Transaction(dt.date(2026, month, day), Decimal(amount), f"tx{day}", category=category)


def test_monthly_summary_groups_expenses():
    txs = [
        _tx(1, "-350.00", "cafe"),
        _tx(2, "85000.00", "salary"),
        _tx(3, "-150.00", "cafe"),
        _tx(4, "-99.90"),
        _tx(5, "-1000.00", "cafe", month=4),
    ]
    s = monthly_summary(txs, 2026, 3)
    assert s.income == Decimal("85000.00")
    assert s.expense == Decimal("-599.90")
    assert s.balance == Decimal("84400.10")
    assert s.by_category == {"cafe": Decimal("-500.00"), "uncategorized": Decimal("-99.90")}


def test_format_summary():
    s = monthly_summary([_tx(1, "-1500.00", "cafe"), _tx(2, "2000.00")], 2026, 3)
    text = format_summary(s)
    assert text.splitlines()[0] == "2026-03"
    assert "income:  2 000.00" in text
    assert "cafe  -1 500.00" in text


def test_empty_month():
    s = monthly_summary([], 2026, 1)
    assert s.income == s.expense == Decimal("0")
    assert s.by_category == {}
