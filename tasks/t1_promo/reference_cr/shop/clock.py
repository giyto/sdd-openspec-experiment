"""Time sources.

Code in the package never calls ``datetime.now()`` directly: anything that needs the
current time receives a :class:`Clock`. Production code uses :class:`SystemClock`,
tests use :class:`FixedClock`. All datetimes are timezone-aware (UTC).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from .errors import ValidationError


class Clock(Protocol):
    def now(self) -> datetime:
        """Return the current moment as an aware datetime."""
        ...


class SystemClock:
    """Real wall-clock time in UTC."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class FixedClock:
    """A manually controlled clock for tests and simulations."""

    def __init__(self, at: datetime) -> None:
        self._at = _require_aware(at)

    def now(self) -> datetime:
        return self._at

    def set(self, at: datetime) -> None:
        self._at = _require_aware(at)

    def advance(self, delta: timedelta) -> None:
        self._at = self._at + delta


def _require_aware(at: datetime) -> datetime:
    if at.tzinfo is None or at.utcoffset() is None:
        raise ValidationError("naive datetimes are not allowed, pass an aware datetime")
    return at
