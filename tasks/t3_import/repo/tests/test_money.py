from decimal import Decimal

import pytest

from ledger.errors import ValidationError
from ledger.models import format_amount, parse_amount, to_money


def test_parse_amount_plain_and_signed():
    assert parse_amount("1234.5") == Decimal("1234.50")
    assert parse_amount(" -45.00 ") == Decimal("-45.00")
    assert parse_amount("+7") == Decimal("7.00")


@pytest.mark.parametrize("text", ["", "abc", "1,5", "1 000.00", "1.234", "--1"])
def test_parse_amount_rejects_garbage(text):
    with pytest.raises(ValidationError):
        parse_amount(text)


def test_to_money_rejects_float_and_extra_precision():
    with pytest.raises(ValidationError):
        to_money(1.5)
    with pytest.raises(ValidationError):
        to_money(Decimal("1.005"))
    assert str(to_money(Decimal("3"))) == "3.00"


def test_format_amount_groups_thousands():
    assert format_amount(Decimal("-1234567.5")) == "-1 234 567.50"
    assert format_amount(Decimal("12.00")) == "12.00"
