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
from .errors import ConfigError, InvalidJobError, InvalidTransitionError
from .metrics import Metrics
from .models import DeadLetterEntry, DeadLetterReason, Job, JobStatus
from .retry import RetryPolicy
from .store import InMemoryJobStore

logger = logging.getLogger(__name__)

_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.PENDING: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RETRY_SCHEDULED: frozenset({JobStatus.RUNNING, JobStatus.CANCELLED}),
    JobStatus.RUNNING: frozenset(
        {
            JobStatus.SUCCEEDED,
            JobStatus.FAILED,
            JobStatus.RETRY_SCHEDULED,
            JobStatus.DEAD_LETTERED,
        }
    ),
    JobStatus.DEAD_LETTERED: frozenset({JobStatus.PENDING}),
}


class JobQueue:
    """Очередь заданий поверх хранилища.

    :param store: хранилище; по умолчанию — новое :class:`InMemoryJobStore`.
    :param clock: источник времени; по умолчанию — :class:`SystemClock`.
    :param metrics: счётчики; по умолчанию — новый :class:`Metrics`.
    :param default_retry_policy: политика повторов для типов без собственной политики;
        ``None`` — повторов нет, первая ошибка переводит задание в FAILED.
    """

    def __init__(
        self,
        store: InMemoryJobStore | None = None,
        *,
        clock: Clock | None = None,
        metrics: Metrics | None = None,
        default_retry_policy: RetryPolicy | None = None,
    ) -> None:
        _require_policy(default_retry_policy)
        self._store = store if store is not None else InMemoryJobStore()
        self._clock = clock if clock is not None else SystemClock()
        self._metrics = metrics if metrics is not None else Metrics()
        self._seq = itertools.count(len(self._store) + 1)
        self._default_policy = default_retry_policy
        self._policies: dict[str, RetryPolicy] = {}
        self._dead_letters: dict[str, DeadLetterEntry] = {}

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

    # -- политика повторов ---------------------------------------------------

    def set_retry_policy(self, job_type: str, policy: RetryPolicy | None) -> None:
        """Задать политику для типа задания; ``None`` — убрать, вернуться к дефолту очереди."""
        if not job_type:
            raise ConfigError("job_type must be a non-empty string")
        _require_policy(policy)
        if policy is None:
            self._policies.pop(job_type, None)
        else:
            self._policies[job_type] = policy

    def retry_policy_for(self, job_type: str) -> RetryPolicy | None:
        """Действующая политика для типа: собственная или дефолтная (может быть ``None``)."""
        return self._policies.get(job_type, self._default_policy)

    # -- dead-letter ---------------------------------------------------------

    def dead_letters(self) -> list[DeadLetterEntry]:
        """Задания в dead-letter, в порядке попадания туда."""
        return list(self._dead_letters.values())

    def requeue_dead_letter(self, job_id: str) -> Job:
        """Вернуть задание из dead-letter в очередь с обнулённым счётчиком попыток."""
        job = self._store.get(job_id)
        self._transition(job, JobStatus.PENDING)
        self._dead_letters.pop(job.id, None)
        job.attempts = 0
        job.error = None
        job.result = None
        job.started_at = None
        job.finished_at = None
        job.run_at = self._clock.now()
        self._metrics.incr(m.JOBS_REQUEUED)
        logger.info("requeued %s from dead-letter", job.id)
        return job

    def requeue_all_dead_letters(self, job_type: str | None = None) -> list[Job]:
        """Перезапустить все задания из dead-letter (или только заданного типа), в порядке очереди."""
        targets = [
            entry.job_id
            for entry in self._dead_letters.values()
            if job_type is None or entry.job_type == job_type
        ]
        return [self.requeue_dead_letter(job_id) for job_id in targets]

    # -- управление ---------------------------------------------------------

    def cancel(self, job_id: str) -> Job:
        """Отменить задание, которое ещё не начало выполняться (или ждёт повтора)."""
        job = self._store.get(job_id)
        self._transition(job, JobStatus.CANCELLED)
        job.finished_at = self._clock.now()
        self._metrics.incr(m.JOBS_CANCELLED)
        return job

    def purge_finished(self, older_than: float = 0.0) -> int:
        """Удалить завершённые задания, закончившиеся не позже ``now - older_than`` секунд.

        Задания из dead-letter тоже удаляются (возраст считается от попадания в dead-letter),
        вместе с их записями в :meth:`dead_letters`.
        """
        cutoff = self._clock.now() - timedelta(seconds=older_than)
        removed = 0
        for job in self._store.all():
            if job.is_terminal and job.finished_at is not None and job.finished_at <= cutoff:
                self._store.remove(job.id)
                self._dead_letters.pop(job.id, None)
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
        job.error = None
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

    def mark_retry_scheduled(self, job_id: str, error: str, run_at: datetime) -> Job:
        job = self._store.get(job_id)
        self._transition(job, JobStatus.RETRY_SCHEDULED)
        job.error = error
        job.run_at = run_at
        self._metrics.incr(m.JOBS_RETRIED)
        return job

    def mark_dead_lettered(
        self,
        job_id: str,
        error: str,
        reason: DeadLetterReason = DeadLetterReason.EXHAUSTED,
    ) -> Job:
        job = self._store.get(job_id)
        self._transition(job, JobStatus.DEAD_LETTERED)
        now = self._clock.now()
        job.error = error
        job.finished_at = now
        self._dead_letters[job.id] = DeadLetterEntry(
            job_id=job.id,
            job_type=job.job_type,
            attempts=job.attempts,
            error=error,
            dead_lettered_at=now,
            reason=reason,
        )
        self._metrics.incr(m.JOBS_DEAD_LETTERED)
        logger.warning(
            "job %s moved to dead-letter (%s) after %d attempts", job.id, reason.value, job.attempts
        )
        return job

    # -- внутреннее ---------------------------------------------------------

    def _transition(self, job: Job, target: JobStatus) -> None:
        allowed = _TRANSITIONS.get(job.status, frozenset())
        if target not in allowed:
            raise InvalidTransitionError(job.id, job.status.value, target.value)
        logger.debug("job %s: %s -> %s", job.id, job.status.value, target.value)
        job.status = target


def _require_policy(policy: object) -> None:
    if policy is not None and not isinstance(policy, RetryPolicy):
        raise ConfigError("retry policy must be a RetryPolicy or None")
