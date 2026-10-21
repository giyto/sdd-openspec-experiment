from datetime import datetime, timezone
from decimal import Decimal

import pytest

from shop.catalog import Cart, Category, Product
from shop.clock import FixedClock

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def p():
    return {
        "laptop": Product("LAPTOP-1", "Laptop", Decimal("2500.00"), Category.ELECTRONICS),
        "book": Product("BOOK-1", "Novel", Decimal("600.00"), Category.BOOKS),
        "shirt": Product("SHIRT-1", "Shirt", Decimal("1000.00"), Category.CLOTHING),
        "tea": Product("TEA-1", "Tea", Decimal("12.25"), Category.FOOD),
        "gift": Product("GIFT-1000", "Gift card", Decimal("1000.00"), Category.GIFT_CARD),
    }


@pytest.fixture
def clock():
    return FixedClock(NOW)


@pytest.fixture
def make_cart():
    def _make(*items):
        cart = Cart()
        for item in items:
            if isinstance(item, tuple):
                cart.add(item[0], item[1])
            else:
                cart.add(item)
        return cart

    return _make
