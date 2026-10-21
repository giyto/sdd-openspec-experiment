"""Модели данных: статусы и задания."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class JobStatus(str, Enum):
    """Статус задания. Значение (``.value``) используется как ключ в отчётах и stats()."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD_LETTERED = "dead_lettered"

    @property
    def label(self) -> str:
        """Человекочитаемое название для отчётов."""
        return _LABELS[self]

    @property
    def is_terminal(self) -> bool:
        """Задание в этом статусе больше не будет выполняться воркером."""
        return self in _TERMINAL


_LABELS: dict[JobStatus, str] = {
    JobStatus.PENDING: "В очереди",
    JobStatus.RUNNING: "Выполняется",
    JobStatus.SUCCEEDED: "Выполнено",
    JobStatus.FAILED: "Ошибка",
    JobStatus.CANCELLED: "Отменено",
    JobStatus.RETRY_SCHEDULED: "Ожидает повтора",
    JobStatus.DEAD_LETTERED: "В dead-letter",
}

_TERMINAL: frozenset[JobStatus] = frozenset(
    {JobStatus.SUCCEEDED, JobStatus.FAILED, JobStatus.CANCELLED, JobStatus.DEAD_LETTERED}
)

#: Статусы, в которых задание ждёт запуска воркером.
RUNNABLE: frozenset[JobStatus] = frozenset({JobStatus.PENDING, JobStatus.RETRY_SCHEDULED})


@dataclass
class Job:
    """Задание в очереди.

    ``attempts`` — сколько раз задание запускалось (увеличивается перед вызовом
    обработчика). ``error`` — текст последней ошибки в формате ``"ИмяКласса: сообщение"``;
    у задания в статусе SUCCEEDED ``error`` всегда ``None``.
    ``seq`` — порядковый номер постановки в очередь, используется для стабильной
    сортировки заданий с одинаковым ``run_at``.
    """

    id: str
    job_type: str
    run_at: datetime
    created_at: datetime
    payload: dict[str, Any] = field(default_factory=dict)
    status: JobStatus = JobStatus.PENDING
    attempts: int = 0
    error: str | None = None
    result: Any = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    seq: int = 0

    @property
    def is_terminal(self) -> bool:
        return self.status.is_terminal


class DeadLetterReason(str, Enum):
    """Почему задание попало в dead-letter."""

    EXHAUSTED = "exhausted"
    NON_RETRYABLE = "non_retryable"


@dataclass(frozen=True)
class DeadLetterEntry:
    """Запись dead-letter очереди: задание, исчерпавшее все попытки."""

    job_id: str
    job_type: str
    attempts: int
    error: str
    dead_lettered_at: datetime
    reason: DeadLetterReason
