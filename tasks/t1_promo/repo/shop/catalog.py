"""Product catalog and shopping cart.

Cart lines keep the order in which products were first added; changing a quantity
does not move a line. This order is used everywhere a deterministic order of lines
is needed (receipts, reports).
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

from .errors import UnknownProductError, ValidationError
from .money import quantize_money, to_money

logger = logging.getLogger(__name__)

SKU_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9-]{1,31}$")
MAX_QUANTITY = 99


def normalize_key(raw: str) -> str:
    """Canonical form of a human-entered code: no surrounding spaces, upper case."""
    if not isinstance(raw, str):
        raise ValidationError(f"expected a string code, got {type(raw).__name__}")
    return raw.strip().upper()


class Category(StrEnum):
    ELECTRONICS = "electronics"
    BOOKS = "books"
    CLOTHING = "clothing"
    FOOD = "food"
    GIFT_CARD = "gift_card"


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    price: Decimal
    category: Category

    def __post_init__(self) -> None:
        object.__setattr__(self, "sku", normalize_key(self.sku))
        if not SKU_PATTERN.match(self.sku):
            raise ValidationError(f"invalid SKU: {self.sku!r}")
        if not self.name.strip():
            raise ValidationError(f"product {self.sku} has an empty name")
        if not isinstance(self.price, Decimal):
            raise ValidationError(f"price of {self.sku} must be Decimal")
        if self.price <= 0:
            raise ValidationError(f"price of {self.sku} must be positive")
        if to_money(self.price) != self.price:
            raise ValidationError(f"price of {self.sku} has more than two fractional digits")
        if not isinstance(self.category, Category):
            raise ValidationError(f"category of {self.sku} must be a Category")

    @property
    def is_physical(self) -> bool:
        """Gift cards are delivered by e-mail, everything else needs shipping."""
        return self.category is not Category.GIFT_CARD


class Catalog:
    """In-memory product catalog keyed by SKU."""

    def __init__(self, products: Iterable[Product] = ()) -> None:
        self._products: dict[str, Product] = {}
        for product in products:
            self.add(product)

    def add(self, product: Product) -> None:
        if product.sku in self._products:
            raise ValidationError(f"duplicate SKU: {product.sku}")
        self._products[product.sku] = product
        logger.debug("catalog: added %s", product.sku)

    def get(self, sku: str) -> Product:
        try:
            return self._products[normalize_key(sku)]
        except KeyError:
            raise UnknownProductError(sku) from None

    def by_category(self, category: Category) -> list[Product]:
        return [p for p in self if p.category is category]

    def __contains__(self, sku: object) -> bool:
        return isinstance(sku, str) and normalize_key(sku) in self._products

    def __len__(self) -> int:
        return len(self._products)

    def __iter__(self) -> Iterator[Product]:
        return iter(sorted(self._products.values(), key=lambda p: p.sku))

    @classmethod
    def from_records(cls, records: Iterable[Mapping[str, Any]]) -> Catalog:
        """Build a catalog from plain dicts (as found in JSON files)."""
        catalog = cls()
        for index, record in enumerate(records):
            try:
                product = Product(
                    sku=str(record["sku"]),
                    name=str(record["name"]),
                    price=to_money(record["price"]),
                    category=Category(record["category"]),
                )
            except KeyError as exc:
                raise ValidationError(f"record #{index}: missing field {exc.args[0]!r}") from None
            except ValueError as exc:
                if isinstance(exc, ValidationError):
                    raise
                raise ValidationError(f"record #{index}: {exc}") from None
            catalog.add(product)
        return catalog

    @classmethod
    def load_json(cls, path: str | Path) -> Catalog:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, list):
            raise ValidationError("catalog file must contain a JSON list")
        catalog = cls.from_records(data)
        logger.info("catalog: loaded %d products from %s", len(catalog), path)
        return catalog


@dataclass(frozen=True)
class CartLine:
    product: Product
    quantity: int

    @property
    def amount(self) -> Decimal:
        """Price of the line before tax and shipping."""
        return quantize_money(self.product.price * self.quantity)


class Cart:
    def __init__(self) -> None:
        self._lines: dict[str, CartLine] = {}

    def add(self, product: Product, quantity: int = 1) -> CartLine:
        _check_quantity(quantity, allow_zero=False)
        existing = self._lines.get(product.sku)
        new_quantity = quantity + (existing.quantity if existing else 0)
        if new_quantity > MAX_QUANTITY:
            raise ValidationError(f"at most {MAX_QUANTITY} items of {product.sku} per order")
        line = CartLine(product, new_quantity)
        self._lines[product.sku] = line
        return line

    def set_quantity(self, sku: str, quantity: int) -> None:
        _check_quantity(quantity, allow_zero=True)
        sku = normalize_key(sku)
        if sku not in self._lines:
            raise UnknownProductError(sku)
        if quantity == 0:
            del self._lines[sku]
            return
        if quantity > MAX_QUANTITY:
            raise ValidationError(f"at most {MAX_QUANTITY} items of {sku} per order")
        self._lines[sku] = CartLine(self._lines[sku].product, quantity)

    def remove(self, sku: str) -> None:
        sku = normalize_key(sku)
        if sku not in self._lines:
            raise UnknownProductError(sku)
        del self._lines[sku]

    def clear(self) -> None:
        self._lines.clear()

    @property
    def lines(self) -> tuple[CartLine, ...]:
        return tuple(self._lines.values())

    @property
    def is_empty(self) -> bool:
        return not self._lines

    def __len__(self) -> int:
        return len(self._lines)

    def __iter__(self) -> Iterator[CartLine]:
        return iter(self.lines)


def _check_quantity(quantity: int, *, allow_zero: bool) -> None:
    if isinstance(quantity, bool) or not isinstance(quantity, int):
        raise ValidationError("quantity must be an integer")
    minimum = 0 if allow_zero else 1
    if quantity < minimum:
        raise ValidationError(f"quantity must be >= {minimum}")
