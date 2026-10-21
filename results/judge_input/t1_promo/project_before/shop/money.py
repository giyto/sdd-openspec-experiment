"""Money helpers.

All amounts in the shop are rubles stored as :class:`decimal.Decimal` with exactly
two fractional digits (kopecks). Floats are never accepted for money. Rounding is
always commercial (``ROUND_HALF_UP``), never the Decimal default (banker's rounding).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from .errors import ValidationError

CENT = Decimal("0.01")
ZERO = Decimal("0.00")


def quantize_money(amount: Decimal) -> Decimal:
    """Round an arbitrary Decimal to kopecks using ROUND_HALF_UP."""
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def to_money(value: Decimal | int | str) -> Decimal:
    """Convert user input to a money Decimal.

    Accepts ``Decimal``, ``int`` and numeric strings. Floats and booleans are
    rejected because they silently lose precision / make no sense as money.
    """
    if isinstance(value, bool) or isinstance(value, float):
        raise ValidationError(f"money must be Decimal, int or str, got {type(value).__name__}")
    if isinstance(value, Decimal):
        amount = value
    else:
        try:
            amount = Decimal(str(value).strip())
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError(f"not a money amount: {value!r}") from exc
    if not amount.is_finite():
        raise ValidationError(f"not a money amount: {value!r}")
    return quantize_money(amount)


def sum_money(amounts: Iterable[Decimal]) -> Decimal:
    """Sum money amounts; an empty iterable gives ``0.00``."""
    return sum(amounts, ZERO)


def format_money(amount: Decimal) -> str:
    """Human readable representation, e.g. ``12 345.60 RUB``."""
    text = f"{quantize_money(amount):,.2f}".replace(",", " ")
    return f"{text} RUB"
