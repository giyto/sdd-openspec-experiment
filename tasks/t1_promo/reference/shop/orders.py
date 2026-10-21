"""Orders: placing, storing and cancelling."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from .catalog import Cart
from .clock import Clock, SystemClock
from .errors import InvalidOrderStateError, OrderNotFoundError, UnknownPromoCodeError
from .pricing import OrderTotal, ShippingPolicy, TaxPolicy, calculate_total
from .promo import PromoCode, PromoRegistry, normalize_code

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
    promo_code: str | None = None


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
        promos: PromoRegistry | None = None,
    ) -> None:
        self.store = store if store is not None else OrderStore()
        self._clock = clock or SystemClock()
        self._shipping = shipping
        self._tax = tax
        self._promos = promos

    def _resolve_promo(self, promo_code: str | None) -> PromoCode | None:
        if promo_code is None or not normalize_code(promo_code):
            return None
        if self._promos is None:
            code = normalize_code(promo_code)
            raise UnknownPromoCodeError(f"unknown promo code: {code!r}", code)
        return self._promos.resolve(promo_code)

    def quote(self, cart: Cart, promo_code: str | None = None) -> OrderTotal:
        """Totals the customer would pay right now; nothing is stored or used up."""
        promo = self._resolve_promo(promo_code)
        return calculate_total(cart, self._shipping, self._tax, promo=promo)

    def place_order(self, cart: Cart, promo_code: str | None = None) -> Order:
        promo = self._resolve_promo(promo_code)
        total = calculate_total(cart, self._shipping, self._tax, promo=promo)
        order = Order(
            order_id=self.store.next_id(),
            created_at=self._clock.now(),
            total=total,
            promo_code=promo.code if promo else None,
        )
        self.store.add(order)
        if promo is not None and self._promos is not None:
            self._promos.record_use(promo.code)
        logger.info("order %s placed, total=%s", order.order_id, total.total)
        return order

    def cancel(self, order_id: str) -> Order:
        order = self.store.get(order_id)
        if order.status is not OrderStatus.PLACED:
            raise InvalidOrderStateError(f"order {order_id} is {order.status}, cannot cancel")
        cancelled = replace(order, status=OrderStatus.CANCELLED)
        self.store.save(cancelled)
        if order.promo_code is not None and self._promos is not None:
            self._promos.release_use(order.promo_code)
        logger.info("order %s cancelled", order_id)
        return cancelled
