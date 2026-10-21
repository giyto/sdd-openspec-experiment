import json
from decimal import Decimal

import pytest

from shop.catalog import Catalog, Category, Product
from shop.errors import UnknownProductError, ValidationError


def test_product_validation():
    with pytest.raises(ValidationError):
        Product("bad sku", "X", Decimal("1.00"), Category.FOOD)
    with pytest.raises(ValidationError):
        Product("SKU-1", "X", Decimal("0"), Category.FOOD)
    with pytest.raises(ValidationError):
        Product("SKU-1", "X", Decimal("1.001"), Category.FOOD)


def test_gift_card_is_not_physical(products):
    assert not products["gift"].is_physical
    assert products["book"].is_physical


def test_catalog_get_and_duplicates(catalog, products):
    assert catalog.get("BOOK-1") is products["book"]
    with pytest.raises(UnknownProductError):
        catalog.get("NOPE-1")
    with pytest.raises(ValidationError):
        catalog.add(products["book"])


def test_codes_are_case_insensitive(catalog, products):
    assert Product(" tea-2 ", "Tea", Decimal("1.00"), Category.FOOD).sku == "TEA-2"
    assert catalog.get("  book-1 ") is products["book"]
    assert "Book-1" in catalog
    with pytest.raises(ValidationError):
        catalog.add(Product("book-1", "Copy", Decimal("1.00"), Category.BOOKS))


def test_catalog_by_category(catalog):
    assert [p.sku for p in catalog.by_category(Category.BOOKS)] == ["BOOK-1"]


def test_load_json(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps([{"sku": "A-1", "name": "A", "price": "10.50", "category": "food"}]),
        encoding="utf-8",
    )
    catalog = Catalog.load_json(path)
    assert catalog.get("A-1").price == Decimal("10.50")


def test_from_records_reports_missing_field():
    with pytest.raises(ValidationError):
        Catalog.from_records([{"sku": "A-1", "name": "A", "price": "1"}])
