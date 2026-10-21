"""Orders: placing, storing and cancelling."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .catalog import Cart
from .clock import Clock, SystemClock
from .errors import InvalidOrderStateError, OrderNotFoundError
from .pricing import OrderTotal, ShippingPolicy, TaxPolicy, calculate_total

logger = logging.getLogger(__name__)


class OrderStatus(StrEnum):
    PLACED = "placed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class Order:
    order_id: str
    created_at: datetime
    total: OrderTotal
    status: OrderStatus = OrderStatus.PLACED


class OrderStore:
    """In-memory order storage. Orders are kept in insertion order."""

    def __init__(self) -> None:
        self._orders: dict[str, Order] = {}
        self._sequence = 0

    def next_id(self) -> str:
        self._sequence += 1
        return f"ORD-{self._sequence:06d}"

    def add(self, order: Order) -> None:
        self._orders[order.order_id] = order

    def save(self, order: Order) -> None:
        if order.order_id not in self._orders:
            raise OrderNotFoundError(order.order_id)
        self._orders[order.order_id] = order

    def get(self, order_id: str) -> Order:
        try:
            return self._orders[order_id]
        except KeyError:
            raise OrderNotFoundError(order_id) from None

    def __iter__(self) -> Iterator[Order]:
        return iter(list(self._orders.values()))

    def __len__(self) -> int:
        return len(self._orders)


class OrderService:
    def __init__(
        self,
        store: OrderStore | None = None,
        *,
        clock: Clock | None = None,
        shipping: ShippingPolicy | None = None,
        tax: TaxPolicy | None = None,
    ) -> None:
        self.store = store if store is not None else OrderStore()
        self._clock = clock or SystemClock()
        self._shipping = shipping
        self._tax = tax

    def quote(self, cart: Cart) -> OrderTotal:
        """Totals the customer would pay right now; nothing is stored."""
        return calculate_total(cart, self._shipping, self._tax)

    def place_order(self, cart: Cart) -> Order:
        total = self.quote(cart)
        order = Order(
            order_id=self.store.next_id(),
            created_at=self._clock.now(),
            total=total,
        )
        self.store.add(order)
        logger.info("order %s placed, total=%s", order.order_id, total.total)
        return order

    def cancel(self, order_id: str) -> Order:
        order = self.store.get(order_id)
        if order.status is not OrderStatus.PLACED:
            raise InvalidOrderStateError(f"order {order_id} is {order.status}, cannot cancel")
        cancelled = replace(order, status=OrderStatus.CANCELLED)
        self.store.save(cancelled)
        logger.info("order %s cancelled", order_id)
        return cancelled
