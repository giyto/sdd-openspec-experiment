from datetime import datetime, timezone
from decimal import Decimal

import pytest

from shop.catalog import Catalog, Category, Product
from shop.clock import FixedClock


@pytest.fixture
def products():
    return {
        "phone": Product("PHONE-1", "Phone", Decimal("2500.00"), Category.ELECTRONICS),
        "book": Product("BOOK-1", "Novel", Decimal("450.00"), Category.BOOKS),
        "tea": Product("TEA-1", "Green tea", Decimal("199.90"), Category.FOOD),
        "shirt": Product("SHIRT-1", "T-shirt", Decimal("999.00"), Category.CLOTHING),
        "gift": Product("GIFT-1000", "Gift card 1000", Decimal("1000.00"), Category.GIFT_CARD),
    }


@pytest.fixture
def catalog(products):
    return Catalog(products.values())


@pytest.fixture
def clock():
    return FixedClock(datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc))
