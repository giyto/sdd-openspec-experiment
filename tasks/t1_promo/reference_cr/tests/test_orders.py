from datetime import timedelta
from decimal import Decimal

import pytest

from shop.catalog import Cart
from shop.errors import InvalidOrderStateError, OrderNotFoundError
from shop.orders import OrderService, OrderStatus


def test_place_order_uses_clock_and_sequence(products, clock):
    service = OrderService(clock=clock)
    cart = Cart()
    cart.add(products["book"])
    first = service.place_order(cart)
    clock.advance(timedelta(minutes=5))
    second = service.place_order(cart)
    assert (first.order_id, second.order_id) == ("ORD-000001", "ORD-000002")
    assert second.created_at - first.created_at == timedelta(minutes=5)
    assert first.total.total == Decimal("794.00")
    assert len(service.store) == 2


def test_quote_does_not_store(products, clock):
    service = OrderService(clock=clock)
    cart = Cart()
    cart.add(products["tea"])
    service.quote(cart)
    assert len(service.store) == 0


def test_cancel(products, clock):
    service = OrderService(clock=clock)
    cart = Cart()
    cart.add(products["tea"])
    order = service.place_order(cart)
    cancelled = service.cancel(order.order_id)
    assert cancelled.status is OrderStatus.CANCELLED
    assert service.store.get(order.order_id).status is OrderStatus.CANCELLED
    with pytest.raises(InvalidOrderStateError):
        service.cancel(order.order_id)


def test_cancel_unknown(clock):
    with pytest.raises(OrderNotFoundError):
        OrderService(clock=clock).cancel("ORD-999999")
