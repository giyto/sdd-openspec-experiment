"""Иерархия исключений jobq.

Все ошибки, которые пакет выбрасывает намеренно, наследуются от :class:`JobqError`,
чтобы вызывающий код мог перехватывать их одной веткой ``except``.
Встроенные ``ValueError``/``KeyError`` наружу из публичного API не выпускаем.
"""

from __future__ import annotations


class JobqError(Exception):
    """Базовая ошибка пакета."""


class ConfigError(JobqError):
    """Некорректная конфигурация: часы, обработчики, параметры очереди."""


class InvalidJobError(JobqError):
    """Некорректные параметры постановки задания в очередь."""


class JobNotFoundError(JobqError):
    """Задание с таким идентификатором не найдено в хранилище."""

    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id!r} not found")
        self.job_id = job_id


class UnknownJobTypeError(JobqError):
    """Для типа задания не зарегистрирован обработчик."""

    def __init__(self, job_type: str) -> None:
        super().__init__(f"no handler registered for job type {job_type!r}")
        self.job_type = job_type


class DuplicateHandlerError(JobqError):
    """Попытка повторно зарегистрировать обработчик для того же типа."""


class PermanentJobError(JobqError):
    """Обработчик сообщает, что задание повторять бессмысленно (ошибка не временная)."""


class RetryLaterError(JobqError):
    """Временная ошибка с подсказкой, через сколько секунд повторить (например, Retry-After)."""

    def __init__(self, message: str = "", *, retry_after: float) -> None:
        if retry_after < 0:
            raise ConfigError("retry_after must be >= 0")
        super().__init__(message)
        self.retry_after = float(retry_after)


class InvalidTransitionError(JobqError):
    """Недопустимый переход между статусами задания."""

    def __init__(self, job_id: str, current: str, target: str) -> None:
        super().__init__(f"job {job_id!r}: cannot move from {current!r} to {target!r}")
        self.job_id = job_id
        self.current = current
        self.target = target
