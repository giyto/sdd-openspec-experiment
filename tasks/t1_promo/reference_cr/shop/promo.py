"""Promo codes: definition, registry with usage counters, discount computation."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from .catalog import Category, normalize_key
from .clock import Clock
from .errors import (
    PromoConditionsError,
    PromoExpiredError,
    UnknownPromoCodeError,
    ValidationError,
)
from .money import CENT, ZERO, quantize_money, sum_money

logger = logging.getLogger(__name__)

#: Categories that never take part in any promo discount.
ALWAYS_EXCLUDED: frozenset[Category] = frozenset({Category.GIFT_CARD})

HUNDRED = Decimal("100")
#: A fixed discount may cover at most this share of the qualifying items.
FIXED_DISCOUNT_SHARE = Decimal("0.5")


def normalize_code(raw: str) -> str:
    return normalize_key(raw)


class DiscountKind(StrEnum):
    PERCENT = "percent"
    FIXED = "fixed"
    FREE_SHIPPING = "free_shipping"


@dataclass(frozen=True)
class PromoCode:
    code: str
    kind: DiscountKind
    value: Decimal
    min_order_amount: Decimal = ZERO
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    max_uses: int | None = None
    excluded_categories: frozenset[Category] = frozenset()
    max_discount: Decimal | None = None
    max_uses_per_customer: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.code, str) or not normalize_code(self.code):
            raise ValidationError("promo code must be a non-empty string")
        object.__setattr__(self, "code", normalize_code(self.code))
        if not isinstance(self.kind, DiscountKind):
            raise ValidationError(f"{self.code}: kind must be a DiscountKind")
        if not isinstance(self.value, Decimal) or not self.value.is_finite():
            raise ValidationError(f"{self.code}: value must be a finite Decimal")
        if self.kind is DiscountKind.PERCENT:
            if not ZERO < self.value <= HUNDRED:
                raise ValidationError(f"{self.code}: percent must be in (0, 100]")
        elif self.kind is DiscountKind.FREE_SHIPPING:
            if self.value != 0:
                raise ValidationError(f"{self.code}: free shipping code must have value 0")
        else:
            if self.value <= 0:
                raise ValidationError(f"{self.code}: fixed discount must be positive")
            if quantize_money(self.value) != self.value:
                raise ValidationError(f"{self.code}: fixed discount has more than two fractional digits")
        if not isinstance(self.min_order_amount, Decimal) or self.min_order_amount < 0:
            raise ValidationError(f"{self.code}: min_order_amount must be a non-negative Decimal")
        for name in ("max_uses", "max_uses_per_customer"):
            limit = getattr(self, name)
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int) or limit < 1):
                raise ValidationError(f"{self.code}: {name} must be a positive integer or None")
        if self.max_discount is not None:
            if self.kind is not DiscountKind.PERCENT:
                raise ValidationError(f"{self.code}: max_discount is allowed for percent codes only")
            if not isinstance(self.max_discount, Decimal) or self.max_discount <= 0:
                raise ValidationError(f"{self.code}: max_discount must be a positive Decimal")
        for moment in (self.starts_at, self.expires_at):
            if moment is not None and (moment.tzinfo is None or moment.utcoffset() is None):
                raise ValidationError(f"{self.code}: validity bounds must be aware datetimes")
        if self.starts_at is not None and self.expires_at is not None and self.starts_at >= self.expires_at:
            raise ValidationError(f"{self.code}: starts_at must be earlier than expires_at")
        object.__setattr__(self, "excluded_categories", frozenset(self.excluded_categories))

    def is_active_at(self, moment: datetime) -> bool:
        if self.starts_at is not None and moment < self.starts_at:
            return False
        if self.expires_at is not None and moment >= self.expires_at:
            return False
        return True

    def applies_to(self, category: Category) -> bool:
        return category not in ALWAYS_EXCLUDED and category not in self.excluded_categories


class PromoRegistry:
    """Known promo codes plus the number of times each one has been used."""

    def __init__(self, clock: Clock, promos: Iterable[PromoCode] = ()) -> None:
        self._clock = clock
        self._promos: dict[str, PromoCode] = {}
        self._uses: dict[str, int] = {}
        self._customer_uses: dict[tuple[str, str], int] = {}
        for promo in promos:
            self.add(promo)

    def add(self, promo: PromoCode) -> None:
        if promo.code in self._promos:
            raise ValidationError(f"duplicate promo code: {promo.code}")
        self._promos[promo.code] = promo
        self._uses[promo.code] = 0

    def _get(self, raw_code: str) -> PromoCode:
        code = normalize_code(raw_code)
        try:
            return self._promos[code]
        except KeyError:
            raise UnknownPromoCodeError(f"unknown promo code: {code!r}", code) from None

    def resolve(self, raw_code: str, customer_id: str | None = None) -> PromoCode:
        """Return an applicable-by-time-and-usage promo code or raise a PromoError."""
        promo = self._get(raw_code)
        if not promo.is_active_at(self._clock.now()):
            raise PromoExpiredError(f"promo code {promo.code} is not active", promo.code)
        if promo.max_uses is not None and self._uses[promo.code] >= promo.max_uses:
            raise PromoConditionsError(f"promo code {promo.code} has been used up", promo.code)
        if promo.max_uses_per_customer is not None:
            if customer_id is None:
                raise PromoConditionsError(f"promo code {promo.code} requires a customer", promo.code)
            if self._customer_uses.get((promo.code, customer_id), 0) >= promo.max_uses_per_customer:
                raise PromoConditionsError(
                    f"promo code {promo.code} has been used up by {customer_id}", promo.code
                )
        return promo

    def uses(self, raw_code: str, customer_id: str | None = None) -> int:
        code = self._get(raw_code).code
        if customer_id is None:
            return self._uses[code]
        return self._customer_uses.get((code, customer_id), 0)

    def record_use(self, code: str, customer_id: str | None = None) -> None:
        promo = self._get(code)
        self._uses[promo.code] += 1
        if customer_id is not None:
            key = (promo.code, customer_id)
            self._customer_uses[key] = self._customer_uses.get(key, 0) + 1
        logger.info("promo %s used (%d)", promo.code, self._uses[promo.code])

    def release_use(self, code: str, customer_id: str | None = None) -> None:
        promo = self._get(code)
        if self._uses[promo.code] > 0:
            self._uses[promo.code] -= 1
            logger.info("promo %s use released (%d)", promo.code, self._uses[promo.code])
        key = (promo.code, customer_id)
        if customer_id is not None and self._customer_uses.get(key, 0) > 0:
            self._customer_uses[key] -= 1


def compute_line_discounts(
    promo: PromoCode, lines: Sequence[tuple[Category, Decimal]]
) -> list[Decimal]:
    """Discount of every line (category, amount) in cart order.

    Raises :class:`PromoConditionsError` when the order does not qualify.
    """
    eligible = [i for i, (category, _) in enumerate(lines) if promo.applies_to(category)]
    if not eligible:
        raise PromoConditionsError(f"no items in the order qualify for {promo.code}", promo.code)
    eligible_amounts = [lines[i][1] for i in eligible]
    eligible_subtotal = sum_money(eligible_amounts)
    if eligible_subtotal < promo.min_order_amount:
        raise PromoConditionsError(
            f"{promo.code} requires {promo.min_order_amount} of qualifying items", promo.code
        )
    if promo.kind is DiscountKind.FREE_SHIPPING:
        return [ZERO] * len(lines)
    if promo.kind is DiscountKind.PERCENT:
        discount = quantize_money(eligible_subtotal * promo.value / HUNDRED)
        if promo.max_discount is not None:
            discount = min(discount, promo.max_discount)
    else:
        discount = min(promo.value, quantize_money(eligible_subtotal * FIXED_DISCOUNT_SHARE))

    shares = allocate(discount, eligible_amounts)
    result = [ZERO] * len(lines)
    for index, share in zip(eligible, shares):
        result[index] = share
    return result


def allocate(discount: Decimal, amounts: Sequence[Decimal]) -> list[Decimal]:
    """Split ``discount`` proportionally to ``amounts`` (largest remainder method).

    Ties between equal remainders go to the larger amount, then to the earlier line.
    """
    total_cents = sum(int(a / CENT) for a in amounts)
    discount_cents = int(discount / CENT)
    shares: list[int] = []
    remainders: list[int] = []
    for amount in amounts:
        numerator = discount_cents * int(amount / CENT)
        shares.append(numerator // total_cents)
        remainders.append(numerator % total_cents)
    left = discount_cents - sum(shares)
    for index in sorted(range(len(amounts)), key=lambda i: (-remainders[i], -amounts[i], i))[:left]:
        shares[index] += 1
    return [quantize_money(Decimal(share) * CENT) for share in shares]
