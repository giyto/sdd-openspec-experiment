"""Источники времени.

Код пакета никогда не вызывает ``datetime.now()`` напрямую: время всегда берётся
из объекта-часов, который внедряется в :class:`~jobq.queue.JobQueue`.
Все моменты времени — aware ``datetime`` в UTC.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Protocol

from .errors import ConfigError

DEFAULT_START = datetime(2024, 1, 1, tzinfo=timezone.utc)


class Clock(Protocol):
    """Минимальный интерфейс часов."""

    def now(self) -> datetime: ...


class SystemClock:
    """Реальные часы (UTC)."""

    def now(self) -> datetime:
        return datetime.now(timezone.utc)


class ManualClock:
    """Часы, которые двигаются только вручную. Используются в тестах и демо."""

    def __init__(self, start: datetime | None = None) -> None:
        moment = DEFAULT_START if start is None else start
        _require_aware(moment)
        self._now = moment

    def now(self) -> datetime:
        return self._now

    def advance(self, seconds: float = 0.0) -> datetime:
        """Сдвинуть часы вперёд на ``seconds`` секунд и вернуть новое время."""
        if seconds < 0:
            raise ConfigError("ManualClock cannot move backwards")
        self._now = self._now + timedelta(seconds=seconds)
        return self._now

    def set(self, moment: datetime) -> None:
        """Установить конкретный момент (не раньше текущего)."""
        _require_aware(moment)
        if moment < self._now:
            raise ConfigError("ManualClock cannot move backwards")
        self._now = moment


def _require_aware(moment: datetime) -> None:
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ConfigError("clock requires timezone-aware datetimes")
