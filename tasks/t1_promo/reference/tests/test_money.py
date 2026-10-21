from decimal import Decimal

import pytest

from shop.errors import ValidationError
from shop.money import format_money, quantize_money, sum_money, to_money


def test_quantize_uses_half_up():
    assert quantize_money(Decimal("1.005")) == Decimal("1.01")
    assert quantize_money(Decimal("2.345")) == Decimal("2.35")


def test_to_money_accepts_str_int_decimal():
    assert to_money("10") == Decimal("10.00")
    assert to_money(7) == Decimal("7.00")
    assert to_money(Decimal("3.1")) == Decimal("3.10")


@pytest.mark.parametrize("bad", [1.5, True, "abc", "NaN"])
def test_to_money_rejects_bad_values(bad):
    with pytest.raises(ValidationError):
        to_money(bad)


def test_sum_money_of_empty_is_zero():
    assert sum_money([]) == Decimal("0.00")


def test_format_money():
    assert format_money(Decimal("12345.6")) == "12 345.60 RUB"
