from decimal import Decimal

import pytest

from shop.catalog import MAX_QUANTITY, Cart
from shop.errors import UnknownProductError, ValidationError


def test_add_merges_same_product(products):
    cart = Cart()
    cart.add(products["book"], 2)
    cart.add(products["book"])
    assert len(cart) == 1
    assert cart.lines[0].quantity == 3
    assert cart.lines[0].amount == Decimal("1350.00")


def test_lines_keep_first_added_order(products):
    cart = Cart()
    cart.add(products["tea"])
    cart.add(products["book"])
    cart.add(products["tea"], 2)
    cart.set_quantity("BOOK-1", 5)
    assert [line.product.sku for line in cart] == ["TEA-1", "BOOK-1"]


def test_set_quantity_zero_removes(products):
    cart = Cart()
    cart.add(products["tea"])
    cart.set_quantity("tea-1", 0)
    assert cart.is_empty


def test_quantity_limits(products):
    cart = Cart()
    with pytest.raises(ValidationError):
        cart.add(products["tea"], 0)
    cart.add(products["tea"], MAX_QUANTITY)
    with pytest.raises(ValidationError):
        cart.add(products["tea"])


def test_remove_unknown(products):
    with pytest.raises(UnknownProductError):
        Cart().remove("TEA-1")
