"""Сервис складского учёта: приход, расход, перемещение, инвентаризация.

Любая операция, меняющая остатки, пишет событие в журнал
(:class:`~warehouse.events.EventLog`). Операция либо выполняется целиком,
либо не меняет ничего — ни остатков, ни журнала.
"""

from __future__ import annotations

import logging

from .clock import Clock, SystemClock
from .errors import (
    DuplicateSkuError,
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSkuError,
    ValidationError,
)
from .events import EventLog
from .models import Sku, StockLevel
from .storage import InMemoryStore

logger = logging.getLogger(__name__)


class Inventory:
    """Остатки товаров по складам."""

    def __init__(
        self,
        store: InMemoryStore | None = None,
        clock: Clock | None = None,
        log: EventLog | None = None,
    ) -> None:
        self._store = store if store is not None else InMemoryStore()
        self._clock = clock if clock is not None else SystemClock()
        self._log = log if log is not None else EventLog()

    @property
    def store(self) -> InMemoryStore:
        return self._store

    @property
    def clock(self) -> Clock:
        return self._clock

    @property
    def log(self) -> EventLog:
        return self._log

    # --- справочник ---------------------------------------------------------

    def register_sku(self, code: str, name: str, unit: str = "pcs") -> Sku:
        _validate_code(code, "SKU code")
        if self._store.has_sku(code):
            raise DuplicateSkuError(code)
        sku = Sku(code=code, name=name, unit=unit)
        self._store.add_sku(sku)
        logger.info("registered SKU %s", code)
        return sku

    def get_sku(self, code: str) -> Sku:
        sku = self._store.get_sku(code)
        if sku is None:
            raise UnknownSkuError(code)
        return sku

    # --- запросы ------------------------------------------------------------

    def on_hand(self, warehouse: str, sku: str) -> int:
        """Физический остаток SKU на складе."""
        self._require_sku(sku)
        return self._store.get_qty(warehouse, sku)

    def stock_levels(self, warehouse: str | None = None) -> list[StockLevel]:
        """Ненулевые физические остатки, отсортированные по складу и SKU."""
        return [
            StockLevel(warehouse=wh, sku=sku, on_hand=qty)
            for wh, sku, qty in self._store.positions()
            if warehouse is None or wh == warehouse
        ]

    # --- операции -----------------------------------------------------------

    def receive(self, warehouse: str, sku: str, qty: int, ref: str | None = None) -> int:
        """Приход товара. Возвращает новый физический остаток."""
        self._check_position(warehouse, sku)
        _validate_qty(qty)
        _validate_ref(ref)
        new_qty = self._store.get_qty(warehouse, sku) + qty
        self._store.set_qty(warehouse, sku, new_qty)
        self._log.append(self._clock.now(), "RECEIVE", wh=warehouse, sku=sku, qty=qty, ref=ref)
        logger.info("received %s x%d at %s", sku, qty, warehouse)
        return new_qty

    def issue(self, warehouse: str, sku: str, qty: int, ref: str | None = None) -> int:
        """Расход (отгрузка, списание). Возвращает новый физический остаток."""
        self._check_position(warehouse, sku)
        _validate_qty(qty)
        _validate_ref(ref)
        current = self._store.get_qty(warehouse, sku)
        if qty > current:
            raise InsufficientStockError(warehouse, sku, qty, current)
        self._store.set_qty(warehouse, sku, current - qty)
        self._log.append(self._clock.now(), "ISSUE", wh=warehouse, sku=sku, qty=qty, ref=ref)
        logger.info("issued %s x%d from %s", sku, qty, warehouse)
        return current - qty

    def transfer(
        self, source: str, target: str, sku: str, qty: int, ref: str | None = None
    ) -> None:
        """Перемещение между складами одним событием ``TRANSFER``.

        Для склада-источника это обычный расход: проверки те же, что у :meth:`issue`.
        """
        self._check_position(source, sku)
        _validate_code(target, "warehouse")
        if source == target:
            raise ValidationError("source and target warehouses must differ")
        _validate_qty(qty)
        _validate_ref(ref)
        current = self._store.get_qty(source, sku)
        if qty > current:
            raise InsufficientStockError(source, sku, qty, current)
        self._store.set_qty(source, sku, current - qty)
        self._store.set_qty(target, sku, self._store.get_qty(target, sku) + qty)
        self._log.append(
            self._clock.now(), "TRANSFER", src=source, dst=target, sku=sku, qty=qty, ref=ref
        )
        logger.info("moved %s x%d %s -> %s", sku, qty, source, target)

    def adjust(self, warehouse: str, sku: str, counted: int, reason: str) -> int:
        """Инвентаризация: фиксирует фактически посчитанный остаток.

        Это факт, а не запрос, поэтому никаких проверок достаточности нет.
        В журнал пишется разница ``delta`` (может быть отрицательной).
        """
        self._check_position(warehouse, sku)
        if isinstance(counted, bool) or not isinstance(counted, int) or counted < 0:
            raise ValidationError(f"counted quantity must be a non-negative integer, got {counted!r}")
        _validate_code(reason, "reason")
        current = self._store.get_qty(warehouse, sku)
        self._store.set_qty(warehouse, sku, counted)
        self._log.append(
            self._clock.now(), "ADJUST", wh=warehouse, sku=sku, delta=counted - current, reason=reason
        )
        logger.warning("stock of %s at %s adjusted %d -> %d", sku, warehouse, current, counted)
        return counted

    # --- служебное ----------------------------------------------------------

    def _require_sku(self, sku: str) -> None:
        if not self._store.has_sku(sku):
            raise UnknownSkuError(sku)

    def _check_position(self, warehouse: str, sku: str) -> None:
        _validate_code(warehouse, "warehouse")
        self._require_sku(sku)


def _validate_code(value: object, what: str) -> None:
    """Коды складов/SKU/ссылок попадают в журнал, поэтому без пробелов."""
    if not isinstance(value, str) or not value or any(ch.isspace() for ch in value) or "=" in value:
        raise ValidationError(f"{what} must be a non-empty string without spaces, got {value!r}")


def _validate_ref(ref: object) -> None:
    if ref is not None:
        _validate_code(ref, "ref")


def _validate_qty(qty: object) -> None:
    if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
        raise InvalidQuantityError(qty)
