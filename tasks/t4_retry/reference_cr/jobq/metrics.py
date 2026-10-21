"""Простые счётчики событий очереди.

Имена счётчиков — ``"jobs.<событие>"``. Неизвестный счётчик читается как 0.

Счётчик статуса увеличивается ровно в момент перехода задания в этот статус:
``jobs.succeeded``, ``jobs.failed``, ``jobs.cancelled`` — переходы в SUCCEEDED, FAILED,
CANCELLED. ``jobs.started`` — каждый запуск обработчика, ``jobs.enqueued`` — постановка
нового задания, ``jobs.purged`` — удаление заданий из хранилища.
"""

from __future__ import annotations

from collections import Counter

from .errors import JobqError

JOBS_ENQUEUED = "jobs.enqueued"
JOBS_STARTED = "jobs.started"
JOBS_SUCCEEDED = "jobs.succeeded"
JOBS_FAILED = "jobs.failed"
JOBS_CANCELLED = "jobs.cancelled"
JOBS_PURGED = "jobs.purged"
JOBS_RETRIED = "jobs.retried"
JOBS_DEAD_LETTERED = "jobs.dead_lettered"
JOBS_REQUEUED = "jobs.requeued"


class Metrics:
    """Накопительные целочисленные счётчики."""

    def __init__(self) -> None:
        self._counters: Counter[str] = Counter()

    def incr(self, name: str, amount: int = 1) -> None:
        if amount < 0:
            raise JobqError("counters only go up")
        self._counters[name] += amount

    def get(self, name: str) -> int:
        return self._counters.get(name, 0)

    def snapshot(self) -> dict[str, int]:
        """Копия всех ненулевых счётчиков, отсортированная по имени."""
        return {name: value for name, value in sorted(self._counters.items()) if value}

    def reset(self) -> None:
        self._counters.clear()
