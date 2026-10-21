import datetime as dt
from decimal import Decimal

import pytest

from ledger.errors import ValidationError
from ledger.models import Transaction


def test_transaction_quantizes_amount():
    tx = Transaction(dt.date(2026, 3, 1), Decimal("-350"), "Кофе")
    assert str(tx.amount) == "-350.00"
    assert tx.is_expense
    assert tx.month == (2026, 3)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"amount": Decimal("0")},
        {"amount": 10.5},
        {"description": "   "},
        {"date": dt.datetime(2026, 3, 1, 12, 0)},
        {"category": ""},
    ],
)
def test_transaction_validation(kwargs):
    base = {"date": dt.date(2026, 3, 1), "amount": Decimal("-1.00"), "description": "x"}
    base.update(kwargs)
    with pytest.raises(ValidationError):
        Transaction(**base)


def test_transaction_roundtrip_dict():
    tx = Transaction(
        dt.date(2026, 3, 2),
        Decimal("85000.00"),
        "Зарплата",
        category="salary",
        imported_at=dt.datetime(2026, 3, 3, 10, 0, tzinfo=dt.timezone.utc),
        id=7,
    )
    assert Transaction.from_dict(tx.to_dict()) == tx
