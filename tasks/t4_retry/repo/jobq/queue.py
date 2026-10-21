"""Очередь заданий: постановка, выборка готовых заданий и переходы статусов.

Все изменения статуса проходят через :meth:`JobQueue._transition`, которая сверяется
с таблицей допустимых переходов ``_TRANSITIONS``. Менять ``job.status`` напрямую
в обход очереди нельзя.
"""

from __future__ import annotations

import itertools
import logging
from datetime import datetime, timedelta
from typing import Any

from . import metrics as m
from .clock import Clock, SystemClock
from .errors import InvalidJobError, InvalidTransitionError
from .metrics import Metrics
from .models import Job, JobStatus
from .store import InMemoryJobStore

logger = logging.getLogger(__name__)

_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset({JobStatus.SUCCEEDED, JobStatus.FAILED}),
}


class JobQueue:
    """Очередь заданий поверх хранилища.

    :param store: хранилище; по умолчанию — новое :class:`InMemoryJobStore`.
    :param clock: источник времени; по умолчанию — :class:`SystemClock`.
    :param metrics: счётчики; по умолчанию — новый :class:`Metrics`.
    """

    def __init__(
        self,
        store: InMemoryJobStore | None = None,
        *,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self._store = store if store is not None else InMemoryJobStore()
        self._clock = clock if clock is not None else SystemClock()
        self._metrics = metrics if metrics is not None else Metrics()
        self._seq = itertools.count(len(self._store) + 1)

    # -- свойства -----------------------------------------------------------

    @property
    def store(self) -> InMemoryJobStore:
        return self._store

    @property
    def clock(self) -> Clock:
        return self._clock

    @property
    def metrics(self) -> Metrics:
        return self._metrics

    # -- постановка и чтение ------------------------------------------------

    def enqueue(
        self,
        job_type: str,
        payload: dict[str, Any] | None = None,
        *,
        delay: float | None = None,
        run_at: datetime | None = None,
    ) -> Job:
        """Поставить задание в очередь.

        Можно указать либо ``delay`` (секунды от текущего момента), либо ``run_at``.
        Без них задание готово к запуску сразу.
        """
        if not job_type:
            raise InvalidJobError("job_type must be a non-empty string")
        if delay is not None and run_at is not None:
            raise InvalidJobError("pass either delay or run_at, not both")
        if delay is not None and delay < 0:
            raise InvalidJobError("delay must be non-negative")
        if run_at is not None and (run_at.tzinfo is None or run_at.utcoffset() is None):
            raise InvalidJobError("run_at must be timezone-aware")
        if payload is not None and not isinstance(payload, dict):
            raise InvalidJobError("payload must be a dict")

        now = self._clock.now()
        if run_at is None:
            run_at = now + timedelta(seconds=delay or 0.0)
        seq = next(self._seq)
        job = Job(
            id=f"job-{seq:06d}",
            job_type=job_type,
            run_at=run_at,
            created_at=now,
            payload=dict(payload or {}),
            seq=seq,
        )
        self._store.add(job)
        self._metrics.incr(m.JOBS_ENQUEUED)
        logger.info("enqueued %s (%s) run_at=%s", job.id, job_type, run_at.isoformat())
        return job

    def get(self, job_id: str) -> Job:
        return self._store.get(job_id)

    def list_jobs(self, status: JobStatus | None = None) -> list[Job]:
        if status is None:
            return self._store.all()
        return self._store.by_status(status)

    def next_due(self) -> Job | None:
        """Ближайшее готовое к запуску задание или ``None``."""
        due = self._store.due(self._clock.now())
        return due[0] if due else None

    def stats(self) -> dict[str, int]:
        """Количество заданий по статусам: ``{status.value: count}`` для всех статусов."""
        return {status.value: count for status, count in self._store.count_by_status().items()}

    # -- управление ---------------------------------------------------------

    def cancel(self, job_id: str) -> Job:
        """Отменить задание, которое ещё не начало выполняться."""
        job = self._store.get(job_id)
        self._transition(job, JobStatus.CANCELLED)
        job.finished_at = self._clock.now()
        self._metrics.incr(m.JOBS_CANCELLED)
        return job

    def purge_finished(self, older_than: float = 0.0) -> int:
        """Удалить завершённые задания, закончившиеся не позже ``now - older_than`` секунд."""
        cutoff = self._clock.now() - timedelta(seconds=older_than)
        removed = 0
        for job in self._store.all():
            if job.is_terminal and job.finished_at is not None and job.finished_at <= cutoff:
                self._store.remove(job.id)
                removed += 1
        if removed:
            self._metrics.incr(m.JOBS_PURGED, removed)
            logger.info("purged %d finished jobs", removed)
        return removed

    # -- переходы, которые вызывает воркер ----------------------------------

    def mark_running(self, job_id: str) -> Job:
        job = self._store.get(job_id)
        self._transition(job, JobStatus.RUNNING)
        job.attempts += 1
        job.started_at = self._clock.now()
        self._metrics.incr(m.JOBS_STARTED)
        return job

    def mark_succeeded(self, job_id: str, result: Any = None) -> Job:
        job = self._store.get(job_id)
        self._transition(job, JobStatus.SUCCEEDED)
        job.result = result
        job.finished_at = self._clock.now()
        self._metrics.incr(m.JOBS_SUCCEEDED)
        return job

    def mark_failed(self, job_id: str, error: str) -> Job:
        job = self._store.get(job_id)
        self._transition(job, JobStatus.FAILED)
        job.error = error
        job.finished_at = self._clock.now()
        self._metrics.incr(m.JOBS_FAILED)
        return job

    # -- внутреннее ---------------------------------------------------------

    def _transition(self, job: Job, target: JobStatus) -> None:
        allowed = _TRANSITIONS.get(job.status, frozenset())
        if target not in allowed:
            raise InvalidTransitionError(job.id, job.status.value, target.value)
        logger.debug("job %s: %s -> %s", job.id, job.status.value, target.value)
        job.status = target
