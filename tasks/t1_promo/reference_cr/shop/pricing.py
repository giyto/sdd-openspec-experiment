"""Order total calculation: line amounts, tax and shipping.

Rules (see README):

* line amount = unit price x quantity;
* tax is charged on top of the price, per line, at the rate of the line's category,
  and rounded per line (ROUND_HALF_UP); the order tax is the sum of line taxes;
* an optional promo code gives a discount on qualifying lines; the discount is
  split between those lines and tax is charged on what is left of each line;
* shipping is a flat fee, free when the goods subtotal (before any discount) reaches
  the threshold; the discount never applies to shipping, only a free shipping promo
  code waives it (the waived fee is reported as ``shipping_discount``);
  carts with gift cards only are not shipped at all;
* shipping is not taxed.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from types import MappingProxyType

from .catalog import Cart, Category
from .errors import EmptyCartError, ValidationError
from .money import ZERO, quantize_money, sum_money
from .promo import DiscountKind, PromoCode, compute_line_discounts

logger = logging.getLogger(__name__)

DEFAULT_TAX_RATE = Decimal("0.20")
DEFAULT_TAX_RATES: Mapping[Category, Decimal] = MappingProxyType(
    {
        Category.BOOKS: Decimal("0.10"),
        Category.FOOD: Decimal("0.10"),
        Category.GIFT_CARD: Decimal("0"),
    }
)


@dataclass(frozen=True)
class TaxPolicy:
    rates: Mapping[Category, Decimal] = field(default_factory=lambda: DEFAULT_TAX_RATES)
    default_rate: Decimal = DEFAULT_TAX_RATE

    def __post_init__(self) -> None:
        for rate in (*self.rates.values(), self.default_rate):
            if not Decimal("0") <= rate < Decimal("1"):
                raise ValidationError(f"tax rate out of range: {rate}")

    def rate_for(self, category: Category) -> Decimal:
        return self.rates.get(category, self.default_rate)

    def tax_for(self, category: Category, taxable_amount: Decimal) -> Decimal:
        return quantize_money(taxable_amount * self.rate_for(category))


@dataclass(frozen=True)
class ShippingPolicy:
    fee: Decimal = Decimal("299.00")
    free_threshold: Decimal | None = Decimal("3000.00")

    def __post_init__(self) -> None:
        if self.fee < 0:
            raise ValidationError("shipping fee must not be negative")
        if self.free_threshold is not None and self.free_threshold < 0:
            raise ValidationError("free shipping threshold must not be negative")

    def cost_for(self, goods_amount: Decimal, *, needs_delivery: bool) -> Decimal:
        if not needs_delivery:
            return ZERO
        if self.free_threshold is not None and goods_amount >= self.free_threshold:
            return ZERO
        return quantize_money(self.fee)


@dataclass(frozen=True)
class LineTotal:
    sku: str
    category: Category
    quantity: int
    unit_price: Decimal
    amount: Decimal
    tax: Decimal
    discount: Decimal = ZERO


@dataclass(frozen=True)
class OrderTotal:
    lines: tuple[LineTotal, ...]
    subtotal: Decimal
    shipping: Decimal
    tax: Decimal
    total: Decimal
    discount: Decimal = ZERO
    shipping_discount: Decimal = ZERO

    @property
    def items_count(self) -> int:
        return sum(line.quantity for line in self.lines)


DEFAULT_SHIPPING = ShippingPolicy()
DEFAULT_TAX = TaxPolicy()


def calculate_total(
    cart: Cart,
    shipping: ShippingPolicy | None = None,
    tax: TaxPolicy | None = None,
    *,
    promo: PromoCode | None = None,
) -> OrderTotal:
    """Calculate the totals of ``cart``. Pure function: does not modify the cart."""
    if cart.is_empty:
        raise EmptyCartError("cannot calculate total of an empty cart")
    shipping = shipping or DEFAULT_SHIPPING
    tax = tax or DEFAULT_TAX

    if promo is None:
        discounts = [ZERO] * len(cart.lines)
    else:
        discounts = compute_line_discounts(
            promo, [(line.product.category, line.amount) for line in cart.lines]
        )

    lines: list[LineTotal] = []
    for cart_line, line_discount in zip(cart.lines, discounts):
        product = cart_line.product
        amount = cart_line.amount
        lines.append(
            LineTotal(
                sku=product.sku,
                category=product.category,
                quantity=cart_line.quantity,
                unit_price=product.price,
                amount=amount,
                tax=tax.tax_for(product.category, amount - line_discount),
                discount=line_discount,
            )
        )

    subtotal = sum_money(line.amount for line in lines)
    discount = sum_money(line.discount for line in lines)
    needs_delivery = any(line.product.is_physical for line in cart.lines)
    shipping_cost = shipping.cost_for(subtotal, needs_delivery=needs_delivery)
    shipping_discount = ZERO
    if promo is not None and promo.kind is DiscountKind.FREE_SHIPPING:
        shipping_discount, shipping_cost = shipping_cost, ZERO
    tax_total = sum_money(line.tax for line in lines)
    total = subtotal - discount + shipping_cost + tax_total

    logger.debug(
        "total: subtotal=%s discount=%s shipping=%s tax=%s total=%s",
        subtotal,
        discount,
        shipping_cost,
        tax_total,
        total,
    )
    return OrderTotal(
        lines=tuple(lines),
        subtotal=subtotal,
        shipping=shipping_cost,
        tax=tax_total,
        total=total,
        discount=discount,
        shipping_discount=shipping_discount,
    )
