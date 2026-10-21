from datetime import timedelta
from decimal import Decimal

import pytest

from shop.catalog import Cart, Category
from shop.errors import ValidationError
from shop.orders import OrderService
from shop.reports import build_sales_report, format_sales_report


def test_sales_report_ignores_cancelled(products, clock):
    service = OrderService(clock=clock)
    cart = Cart()
    cart.add(products["book"], 2)
    service.place_order(cart)
    clock.advance(timedelta(days=1))
    other = Cart()
    other.add(products["gift"])
    cancelled = service.place_order(other)
    service.cancel(cancelled.order_id)

    report = build_sales_report(service.store)
    assert report.orders_count == 1
    assert report.revenue == Decimal("1289.00")
    assert report.by_category == {Category.BOOKS: Decimal("900.00")}
    assert report.top_skus == [("BOOK-1", 2)]
    assert report.average_order == Decimal("1289.00")


def test_format_sales_report(products, clock):
    service = OrderService(clock=clock)
    cart = Cart()
    cart.add(products["tea"])
    service.place_order(cart)
    text = format_sales_report(build_sales_report(service.store))
    assert "Orders:        1" in text
    assert "2026-03-01" in text


def test_report_period_is_half_open(products, clock):
    service = OrderService(clock=clock)
    cart = Cart()
    cart.add(products["tea"])
    start = clock.now()
    service.place_order(cart)                 # exactly at `since` -> included
    clock.advance(timedelta(hours=1))
    service.place_order(cart)                 # exactly at `until` -> excluded
    report = build_sales_report(service.store, since=start, until=start + timedelta(hours=1))
    assert report.orders_count == 1
    assert build_sales_report(service.store, since=start).orders_count == 2
    with pytest.raises(ValidationError):
        build_sales_report(service.store, since=start, until=start)


def test_empty_report():
    report = build_sales_report([])
    assert report.orders_count == 0
    assert report.average_order == Decimal("0.00")
