"""Command line interface for support staff.

Examples::

    python -m shop.cli products --catalog catalog.json
    python -m shop.cli quote --catalog catalog.json BOOK-001:2 GIFT-500:1
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence

from .catalog import Cart, Catalog, Category
from .errors import ShopError, ValidationError
from .money import format_money
from .pricing import OrderTotal, ShippingPolicy, calculate_total


def _parse_item(spec: str) -> tuple[str, int]:
    sku, sep, qty = spec.partition(":")
    if not sep:
        return sku.strip().upper(), 1
    try:
        return sku.strip().upper(), int(qty)
    except ValueError:
        raise ValidationError(f"bad item spec {spec!r}, expected SKU:QTY") from None


def _render_total(total: OrderTotal) -> str:
    rows = []
    for line in total.lines:
        rows.append(
            f"{line.sku:<16} {line.quantity:>3} x {format_money(line.unit_price):>16}"
            f" = {format_money(line.amount):>16}"
        )
    rows.append("-" * 60)
    rows.append(f"{'Subtotal':<38}{format_money(total.subtotal):>22}")
    rows.append(f"{'Tax':<38}{format_money(total.tax):>22}")
    rows.append(f"{'Shipping':<38}{format_money(total.shipping):>22}")
    rows.append(f"{'TOTAL':<38}{format_money(total.total):>22}")
    return "\n".join(rows)


def _cmd_products(args: argparse.Namespace) -> int:
    catalog = Catalog.load_json(args.catalog)
    products = catalog.by_category(Category(args.category)) if args.category else list(catalog)
    for product in products:
        print(f"{product.sku:<16} {product.category.value:<12} {format_money(product.price):>16}  {product.name}")
    return 0


def _cmd_quote(args: argparse.Namespace) -> int:
    catalog = Catalog.load_json(args.catalog)
    cart = Cart()
    for spec in args.items:
        sku, qty = _parse_item(spec)
        cart.add(catalog.get(sku), qty)
    shipping = ShippingPolicy(free_threshold=None) if args.no_free_shipping else None
    print(_render_total(calculate_total(cart, shipping)))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="shop", description="Shop support tools")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    products = sub.add_parser("products", help="list catalog products")
    products.add_argument("--catalog", required=True)
    products.add_argument("--category", choices=[c.value for c in Category])
    products.set_defaults(func=_cmd_products)

    quote = sub.add_parser("quote", help="calculate totals for a list of SKU:QTY items")
    quote.add_argument("--catalog", required=True)
    quote.add_argument("--no-free-shipping", action="store_true")
    quote.add_argument("items", nargs="+")
    quote.set_defaults(func=_cmd_quote)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING)
    try:
        return args.func(args)
    except ShopError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
