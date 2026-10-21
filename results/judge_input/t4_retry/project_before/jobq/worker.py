"""Синхронный воркер: берёт готовые задания по времени запуска и выполняет их."""

from __future__ import annotations

import logging

from .errors import UnknownJobTypeError
from .models import Job
from .queue import JobQueue
from .registry import HandlerRegistry

logger = logging.getLogger(__name__)


def format_error(exc: BaseException) -> str:
    """Формат текста ошибки, который сохраняется в ``Job.error``."""
    return f"{type(exc).__name__}: {exc}"


class Worker:
    """Выполняет задания из очереди по одному, в текущем потоке.

    Время берётся из часов очереди, счётчики — из её метрик.
    """

    def __init__(self, queue: JobQueue, registry: HandlerRegistry, *, name: str = "worker") -> None:
        self._queue = queue
        self._registry = registry
        self.name = name
        self.processed = 0

    @property
    def queue(self) -> JobQueue:
        return self._queue

    def run_once(self) -> Job | None:
        """Выполнить одно готовое задание. Возвращает задание или ``None``, если готовых нет."""
        job = self._queue.next_due()
        if job is None:
            return None

        self._queue.mark_running(job.id)
        logger.info("%s: running %s (%s), attempt %d", self.name, job.id, job.job_type, job.attempts)
        self.processed += 1

        try:
            handler = self._registry.get(job.job_type)
        except UnknownJobTypeError as exc:
            logger.error("%s: %s", self.name, exc)
            return self._queue.mark_failed(job.id, format_error(exc))

        try:
            result = handler(job)
        except Exception as exc:  # обработчик может бросить что угодно
            logger.warning("%s: job %s failed: %s", self.name, job.id, exc)
            return self._queue.mark_failed(job.id, format_error(exc))

        logger.info("%s: job %s succeeded", self.name, job.id)
        return self._queue.mark_succeeded(job.id, result)

    def run_pending(self, max_jobs: int | None = None) -> int:
        """Выполнять готовые задания, пока они есть (или пока не выполнено ``max_jobs``).

        Возвращает количество выполненных запусков.
        """
        executed = 0
        while max_jobs is None or executed < max_jobs:
            if self.run_once() is None:
                break
            executed += 1
        return executed
