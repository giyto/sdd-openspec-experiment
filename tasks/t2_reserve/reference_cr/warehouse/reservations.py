"""Учёт резервов под заказы.

Истечение резерва не требует фонового процесса: статус вычисляется по часам
в момент обращения (резерв активен, пока ``now < expires_at``).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterator

from .errors import ValidationError
from .models import Reservation, ReservationLine, ReservationStatus

DEFAULT_RESERVATION_TTL = timedelta(minutes=20)
MAX_RESERVATION_LIFETIME = timedelta(hours=2)


@dataclass
class _Record:
    order_id: str
    lines: tuple[ReservationLine, ...]
    created_at: datetime
    expires_at: datetime
    state: ReservationStatus = ReservationStatus.ACTIVE
    expiry_logged: bool = False

    @property
    def deadline(self) -> datetime:
        """Позже этого момента срок резерва не может быть."""
        return self.created_at + MAX_RESERVATION_LIFETIME

    def status_at(self, now: datetime) -> ReservationStatus:
        if self.state is ReservationStatus.ACTIVE and now >= self.expires_at:
            return ReservationStatus.EXPIRED
        return self.state

    def snapshot(self, now: datetime) -> Reservation:
        return Reservation(
            order_id=self.order_id,
            lines=self.lines,
            created_at=self.created_at,
            expires_at=self.expires_at,
            status=self.status_at(now),
        )


def validate_ttl(ttl: object) -> timedelta:
    if not isinstance(ttl, timedelta) or ttl <= timedelta(0):
        raise ValidationError(f"ttl must be a positive timedelta, got {ttl!r}")
    return ttl


def totals(lines: tuple[ReservationLine, ...]) -> Counter[tuple[str, str]]:
    """Суммарное количество по позициям ``(warehouse, sku)``."""
    result: Counter[tuple[str, str]] = Counter()
    for line in lines:
        result[(line.warehouse, line.sku)] += line.qty
    return result


class ReservationBook:
    """Хранилище резервов в памяти (по одному текущему резерву на заказ)."""

    def __init__(self) -> None:
        self._records: dict[str, _Record] = {}

    def get(self, order_id: str) -> _Record | None:
        return self._records.get(order_id)

    def put(self, record: _Record) -> None:
        self._records[record.order_id] = record

    def __iter__(self) -> Iterator[_Record]:
        return iter(list(self._records.values()))

    def active(self, now: datetime, exclude: str | None = None) -> Iterator[_Record]:
        for record in self._records.values():
            if record.order_id != exclude and record.status_at(now) is ReservationStatus.ACTIVE:
                yield record

    def reserved(
        self, warehouse: str, sku: str, now: datetime, exclude: str | None = None
    ) -> int:
        return sum(
            line.qty
            for record in self.active(now, exclude)
            for line in record.lines
            if line.warehouse == warehouse and line.sku == sku
        )
