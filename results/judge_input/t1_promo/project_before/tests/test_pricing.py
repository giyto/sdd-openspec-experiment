from decimal import Decimal

import pytest

from shop.catalog import Cart, Category, Product
from shop.errors import EmptyCartError, ValidationError
from shop.pricing import ShippingPolicy, TaxPolicy, calculate_total


def test_empty_cart_raises():
    with pytest.raises(EmptyCartError):
        calculate_total(Cart())


def test_tax_per_category_and_rounding(products):
    cart = Cart()
    cart.add(products["tea"], 3)    # 599.70 * 10% = 59.97
    cart.add(products["shirt"])     # 999.00 * 20% = 199.80
    total = calculate_total(cart)
    assert [line.tax for line in total.lines] == [Decimal("59.97"), Decimal("199.80")]
    assert total.subtotal == Decimal("1598.70")
    assert total.tax == Decimal("259.77")
    assert total.shipping == Decimal("299.00")
    assert total.total == Decimal("2157.47")


def test_tax_is_rounded_per_line():
    a = Product("A-1", "A", Decimal("0.05"), Category.BOOKS)
    b = Product("B-1", "B", Decimal("0.05"), Category.BOOKS)
    cart = Cart()
    cart.add(a)
    cart.add(b)
    # 0.005 -> 0.01 per line, so 0.02 in total (not round(0.01) of the sum)
    assert calculate_total(cart).tax == Decimal("0.02")


def test_free_shipping_threshold_inclusive(products):
    cart = Cart()
    cart.add(products["phone"])
    cart.add(products["book"])  # 2950.00
    assert calculate_total(cart).shipping == Decimal("299.00")
    cheap = ShippingPolicy(free_threshold=Decimal("2950.00"))
    assert calculate_total(cart, cheap).shipping == Decimal("0.00")


def test_gift_cards_only_have_no_shipping_and_no_tax(products):
    cart = Cart()
    cart.add(products["gift"])
    total = calculate_total(cart)
    assert total.shipping == Decimal("0.00")
    assert total.tax == Decimal("0.00")
    assert total.total == Decimal("1000.00")


def test_custom_tax_policy(products):
    cart = Cart()
    cart.add(products["book"])
    policy = TaxPolicy(rates={}, default_rate=Decimal("0"))
    assert calculate_total(cart, tax=policy).tax == Decimal("0.00")
    with pytest.raises(ValidationError):
        TaxPolicy(default_rate=Decimal("1.5"))


def test_calculate_total_does_not_modify_cart(products):
    cart = Cart()
    cart.add(products["book"], 2)
    calculate_total(cart)
    assert cart.lines[0].quantity == 2
    assert calculate_total(cart).items_count == 2
