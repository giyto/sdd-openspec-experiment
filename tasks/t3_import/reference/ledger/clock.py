"""Источники текущего времени.

Бизнес-код не вызывает datetime.now() напрямую: часы передаются параметром,
что делает поведение детерминированным в тестах.
"""

from __future__ import annotations

import datetime as dt
from typing import Protocol


class Clock(Protocol):
    def now(self) -> dt.datetime: ...


class SystemClock:
    """Реальные часы, всегда в UTC."""

    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


class FixedClock:
    """Часы, которые показывают заданное время (для тестов)."""

    def __init__(self, at: dt.datetime) -> None:
        if at.tzinfo is None:
            raise ValueError("FixedClock requires an aware datetime")
        self._at = at

    def now(self) -> dt.datetime:
        return self._at

    def advance(self, delta: dt.timedelta) -> None:
        self._at = self._at + delta
