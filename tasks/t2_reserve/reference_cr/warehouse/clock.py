"""Источники времени.

Бизнес-код никогда не вызывает ``datetime.now()`` напрямую: часы передаются
в :class:`~warehouse.inventory.Inventory` через конструктор. Все моменты
времени — timezone-aware, в UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from .errors import ValidationError


class Clock(Protocol):
    """Всё, что умеет возвращать текущий момент (aware datetime в UTC)."""

    def now(self) -> datetime: ...


class SystemClock:
    """Настоящие часы для продакшена и CLI."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock:
    """Часы, которые двигаются только вручную. Используются в тестах."""

    def __init__(self, start: datetime) -> None:
        self._now = _require_aware(start)

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> datetime:
        if delta < timedelta(0):
            raise ValidationError("clock cannot go backwards")
        self._now = self._now + delta
        return self._now

    def set(self, moment: datetime) -> None:
        self._now = _require_aware(moment)


def _require_aware(moment: datetime) -> datetime:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValidationError("naive datetimes are not allowed, pass an aware UTC datetime")
    return moment.astimezone(timezone.utc)
