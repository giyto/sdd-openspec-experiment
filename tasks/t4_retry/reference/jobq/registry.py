"""Реестр обработчиков по типу задания."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from .errors import ConfigError, DuplicateHandlerError, UnknownJobTypeError
from .models import Job

logger = logging.getLogger(__name__)

Handler = Callable[[Job], Any]


class HandlerRegistry:
    """Сопоставляет тип задания (строку) с функцией-обработчиком ``handler(job) -> result``."""

    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, job_type: str, handler: Handler, *, replace: bool = False) -> None:
        if not job_type:
            raise ConfigError("job_type must be a non-empty string")
        if not callable(handler):
            raise ConfigError(f"handler for {job_type!r} is not callable")
        if job_type in self._handlers and not replace:
            raise DuplicateHandlerError(f"handler for {job_type!r} already registered")
        self._handlers[job_type] = handler
        logger.debug("registered handler for %s", job_type)

    def handler(self, job_type: str, *, replace: bool = False) -> Callable[[Handler], Handler]:
        """Декоратор-обёртка над :meth:`register`."""

        def decorator(func: Handler) -> Handler:
            self.register(job_type, func, replace=replace)
            return func

        return decorator

    def get(self, job_type: str) -> Handler:
        try:
            return self._handlers[job_type]
        except KeyError:
            raise UnknownJobTypeError(job_type) from None

    def __contains__(self, job_type: object) -> bool:
        return job_type in self._handlers

    def job_types(self) -> list[str]:
        return sorted(self._handlers)
