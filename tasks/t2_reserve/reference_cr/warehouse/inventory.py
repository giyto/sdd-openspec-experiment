"""Сервис складского учёта: приход, расход, перемещение, инвентаризация.

Любая операция, меняющая остатки, пишет событие в журнал
(:class:`~warehouse.events.EventLog`). Операция либо выполняется целиком,
либо не меняет ничего — ни остатков, ни журнала.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Iterable

from .clock import Clock, SystemClock
from .errors import (
    DuplicateReservationError,
    DuplicateSkuError,
    InsufficientStockError,
    InvalidQuantityError,
    ReservationExpiredError,
    ReservationNotFoundError,
    ReservationStateError,
    UnknownSkuError,
    ValidationError,
)
from .events import EventLog, format_timestamp
from .models import Availability, Reservation, ReservationLine, ReservationStatus, Sku, StockLevel
from .reservations import (
    DEFAULT_RESERVATION_TTL,
    MAX_RESERVATION_LIFETIME,
    ReservationBook,
    _Record,
    totals,
    validate_ttl,
)
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
        self._reservations = ReservationBook()

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

    def reserved(self, warehouse: str, sku: str) -> int:
        """Сумма активных резервов по позиции."""
        self._require_sku(sku)
        return self._reservations.reserved(warehouse, sku, self._clock.now())

    def available(self, warehouse: str, sku: str) -> int:
        """Физический остаток минус активные резервы, не меньше нуля."""
        self._require_sku(sku)
        return self._available(warehouse, sku, self._clock.now())

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
        now = self._clock.now()
        current = self._store.get_qty(warehouse, sku)
        free = self._available(warehouse, sku, now)
        if qty > free:
            raise InsufficientStockError(warehouse, sku, qty, free)
        self._store.set_qty(warehouse, sku, current - qty)
        self._log.append(now, "ISSUE", wh=warehouse, sku=sku, qty=qty, ref=ref)
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
        now = self._clock.now()
        current = self._store.get_qty(source, sku)
        free = self._available(source, sku, now)
        if qty > free:
            raise InsufficientStockError(source, sku, qty, free)
        self._store.set_qty(source, sku, current - qty)
        self._store.set_qty(target, sku, self._store.get_qty(target, sku) + qty)
        self._log.append(
            now, "TRANSFER", src=source, dst=target, sku=sku, qty=qty, ref=ref
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

    # --- резервы -------------------------------------------------------------

    def reserve(
        self,
        order_id: str,
        lines: Iterable[tuple[str, str, int] | ReservationLine],
        ttl: timedelta | None = None,
    ) -> Reservation:
        """Резервирует все строки заказа целиком или не резервирует ничего."""
        _validate_code(order_id, "order id")
        ttl = validate_ttl(DEFAULT_RESERVATION_TTL if ttl is None else ttl)
        if ttl > MAX_RESERVATION_LIFETIME:
            raise ValidationError(f"ttl {ttl} exceeds the maximum reservation lifetime")
        parsed = tuple(self._parse_line(line) for line in lines)
        if not parsed:
            raise ValidationError("reservation must contain at least one line")
        now = self._clock.now()
        existing = self._reservations.get(order_id)
        existing_status = existing.status_at(now) if existing is not None else None
        if existing_status is ReservationStatus.CONFIRMED:
            raise DuplicateReservationError(order_id)
        # заменяемый активный резерв при проверке наличия не мешает
        replacing = existing_status is ReservationStatus.ACTIVE
        for (warehouse, sku), qty in totals(parsed).items():
            free = self._available(warehouse, sku, now, exclude=order_id if replacing else None)
            if qty > free:
                raise InsufficientStockError(warehouse, sku, qty, free)
        record = _Record(order_id, parsed, now, now + ttl)
        self._reservations.put(record)
        if replacing:
            self._log.append(now, "RESERVE_CANCEL", order=order_id)
        expires = format_timestamp(record.expires_at)
        for line in parsed:
            self._log.append(
                now, "RESERVE", order=order_id, wh=line.warehouse, sku=line.sku,
                qty=line.qty, expires=expires,
            )
        logger.info("reserved order %s until %s", order_id, expires)
        return record.snapshot(now)

    def confirm(self, order_id: str) -> Reservation:
        """Превращает активный резерв в отгрузку."""
        now = self._clock.now()
        record = self._active_record(order_id, now)
        for (warehouse, sku), qty in totals(record.lines).items():
            current = self._store.get_qty(warehouse, sku)
            if qty > current:
                raise InsufficientStockError(warehouse, sku, qty, current)
        for line in record.lines:
            current = self._store.get_qty(line.warehouse, line.sku)
            self._store.set_qty(line.warehouse, line.sku, current - line.qty)
            self._log.append(
                now, "ISSUE", wh=line.warehouse, sku=line.sku, qty=line.qty, ref=order_id
            )
        record.state = ReservationStatus.CONFIRMED
        self._log.append(now, "RESERVE_CONFIRM", order=order_id)
        logger.info("confirmed reservation for order %s", order_id)
        return record.snapshot(now)

    def cancel(self, order_id: str) -> Reservation:
        """Освобождает резерв. Повторная отмена и отмена истёкшего — no-op."""
        now = self._clock.now()
        record = self._record(order_id)
        status = record.status_at(now)
        if status is ReservationStatus.CONFIRMED:
            # возврат: товар по всем строкам приходит обратно на склады
            for line in record.lines:
                current = self._store.get_qty(line.warehouse, line.sku)
                self._store.set_qty(line.warehouse, line.sku, current + line.qty)
                self._log.append(
                    now, "RECEIVE", wh=line.warehouse, sku=line.sku, qty=line.qty, ref=order_id
                )
            record.state = ReservationStatus.CANCELLED
            self._log.append(now, "RESERVE_CANCEL", order=order_id)
            logger.info("returned confirmed order %s", order_id)
        elif status is ReservationStatus.ACTIVE:
            record.state = ReservationStatus.CANCELLED
            self._log.append(now, "RESERVE_CANCEL", order=order_id)
            logger.info("cancelled reservation for order %s", order_id)
        return record.snapshot(now)

    def extend(self, order_id: str, ttl: timedelta) -> Reservation:
        """Продлевает активный резерв до ``now + ttl`` (срок не сокращается)."""
        ttl = validate_ttl(ttl)
        now = self._clock.now()
        record = self._active_record(order_id, now)
        new_expiry = min(now + ttl, record.deadline)
        if new_expiry > record.expires_at:
            record.expires_at = new_expiry
            self._log.append(
                now, "RESERVE_EXTEND", order=order_id, expires=format_timestamp(new_expiry)
            )
            logger.info("extended reservation for order %s", order_id)
        return record.snapshot(now)

    def get_reservation(self, order_id: str) -> Reservation:
        return self._record(order_id).snapshot(self._clock.now())

    def reservations(self, status: ReservationStatus | None = None) -> list[Reservation]:
        """Снимки текущих резервов, по ``created_at``, затем по ``order_id``."""
        now = self._clock.now()
        snapshots = [record.snapshot(now) for record in self._reservations]
        if status is not None:
            snapshots = [snap for snap in snapshots if snap.status == status]
        return sorted(snapshots, key=lambda snap: (snap.created_at, snap.order_id))

    def availability(self, warehouse: str | None = None) -> list[Availability]:
        """Позиции с физическим остатком или активным резервом."""
        now = self._clock.now()
        positions = {(wh, sku) for wh, sku, _ in self._store.positions()}
        for record in self._reservations.active(now):
            positions.update((line.warehouse, line.sku) for line in record.lines)
        result = []
        for wh, sku in sorted(positions):
            if warehouse is not None and wh != warehouse:
                continue
            on_hand = self._store.get_qty(wh, sku)
            held = self._reservations.reserved(wh, sku, now)
            result.append(Availability(wh, sku, on_hand, held, max(0, on_hand - held)))
        return result

    def sweep_expired(self) -> list[str]:
        """Пишет ``RESERVE_EXPIRE`` по истёкшим резервам, о которых ещё не писали."""
        now = self._clock.now()
        expired = sorted(
            (
                record
                for record in self._reservations
                if not record.expiry_logged and record.status_at(now) is ReservationStatus.EXPIRED
            ),
            key=lambda record: (record.expires_at, record.order_id),
        )
        for record in expired:
            self._log.append(
                now, "RESERVE_EXPIRE", order=record.order_id,
                expires=format_timestamp(record.expires_at),
            )
            record.expiry_logged = True
        if expired:
            logger.info("logged expiry of %d reservations", len(expired))
        return [record.order_id for record in expired]

    # --- служебное ----------------------------------------------------------

    def _available(
        self, warehouse: str, sku: str, now: datetime, exclude: str | None = None
    ) -> int:
        held = self._reservations.reserved(warehouse, sku, now, exclude)
        return max(0, self._store.get_qty(warehouse, sku) - held)

    def _parse_line(self, line: tuple[str, str, int] | ReservationLine) -> ReservationLine:
        if isinstance(line, ReservationLine):
            warehouse, sku, qty = line.warehouse, line.sku, line.qty
        else:
            try:
                warehouse, sku, qty = line
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"bad reservation line {line!r}") from exc
        self._check_position(warehouse, sku)
        _validate_qty(qty)
        return ReservationLine(warehouse, sku, qty)

    def _record(self, order_id: str) -> _Record:
        record = self._reservations.get(order_id)
        if record is None:
            raise ReservationNotFoundError(order_id)
        return record

    def _active_record(self, order_id: str, now: datetime) -> _Record:
        record = self._record(order_id)
        status = record.status_at(now)
        if status is ReservationStatus.EXPIRED:
            raise ReservationExpiredError(order_id)
        if status is not ReservationStatus.ACTIVE:
            raise ReservationStateError(order_id, status.value)
        return record


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
