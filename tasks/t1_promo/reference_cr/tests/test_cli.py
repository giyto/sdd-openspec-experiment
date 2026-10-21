import json

import pytest

from shop.cli import main


@pytest.fixture
def catalog_file(tmp_path):
    path = tmp_path / "catalog.json"
    path.write_text(
        json.dumps(
            [
                {"sku": "BOOK-1", "name": "Novel", "price": "450.00", "category": "books"},
                {"sku": "GIFT-500", "name": "Gift", "price": "500.00", "category": "gift_card"},
            ]
        ),
        encoding="utf-8",
    )
    return path


def test_quote(catalog_file, capsys):
    assert main(["quote", "--catalog", str(catalog_file), "book-1:2", "GIFT-500"]) == 0
    out = capsys.readouterr().out
    assert "TOTAL" in out
    assert "1 789.00 RUB" in out


def test_products_filter(catalog_file, capsys):
    assert main(["products", "--catalog", str(catalog_file), "--category", "books"]) == 0
    out = capsys.readouterr().out
    assert "BOOK-1" in out and "GIFT-500" not in out


def test_unknown_sku_is_reported(catalog_file, capsys):
    assert main(["quote", "--catalog", str(catalog_file), "NOPE-1"]) == 2
    assert "unknown product" in capsys.readouterr().err
