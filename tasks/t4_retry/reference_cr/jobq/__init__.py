"""jobq — простая очередь фоновых заданий с синхронным воркером."""

from .clock import Clock, ManualClock, SystemClock
from .errors import (
    ConfigError,
    DuplicateHandlerError,
    InvalidJobError,
    InvalidTransitionError,
    JobNotFoundError,
    JobqError,
    PermanentJobError,
    RetryLaterError,
    UnknownJobTypeError,
)
from .metrics import Metrics
from .models import DeadLetterEntry, DeadLetterReason, Job, JobStatus
from .queue import JobQueue
from .registry import HandlerRegistry
from .retry import RetryPolicy
from .store import InMemoryJobStore
from .worker import Worker

__all__ = [
    "Clock",
    "ConfigError",
    "DeadLetterEntry",
    "DeadLetterReason",
    "DuplicateHandlerError",
    "HandlerRegistry",
    "InMemoryJobStore",
    "InvalidJobError",
    "InvalidTransitionError",
    "Job",
    "JobNotFoundError",
    "JobQueue",
    "JobStatus",
    "JobqError",
    "ManualClock",
    "Metrics",
    "PermanentJobError",
    "RetryLaterError",
    "RetryPolicy",
    "SystemClock",
    "UnknownJobTypeError",
    "Worker",
]
