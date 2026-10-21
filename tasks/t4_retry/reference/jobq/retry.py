"""Политика повторного выполнения упавших заданий."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .errors import ConfigError, PermanentJobError


@dataclass(frozen=True, kw_only=True)
class RetryPolicy:
    """Как и сколько раз повторять упавшее задание.

    ``max_attempts`` — общее число попыток, включая первую. Задержка перед повтором
    после неудачной попытки номер ``attempt`` равна
    ``min(base_delay * factor ** (attempt - 1), max_delay)``, затем к ней применяется
    джиттер (множитель из ``[1 - jitter, 1 + jitter]``) и повторно ограничение ``max_delay``.
    """

    max_attempts: int = 3
    base_delay: float = 1.0
    factor: float = 2.0
    max_delay: float = 60.0
    jitter: float = 0.0
    non_retryable: tuple[type[BaseException], ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.max_attempts, bool) or not isinstance(self.max_attempts, int):
            raise ConfigError("max_attempts must be an integer")
        if self.max_attempts < 1:
            raise ConfigError("max_attempts must be >= 1")
        if self.base_delay < 0:
            raise ConfigError("base_delay must be >= 0")
        if self.factor < 1:
            raise ConfigError("factor must be >= 1")
        if self.max_delay < self.base_delay:
            raise ConfigError("max_delay must be >= base_delay")
        if not 0 <= self.jitter <= 1:
            raise ConfigError("jitter must be within [0, 1]")
        try:
            classes = tuple(self.non_retryable)
        except TypeError:
            raise ConfigError("non_retryable must be a sequence of exception classes") from None
        for cls in classes:
            if not (isinstance(cls, type) and issubclass(cls, BaseException)):
                raise ConfigError(f"non_retryable item {cls!r} is not an exception class")
        object.__setattr__(self, "non_retryable", classes)

    def is_retryable(self, exc: BaseException) -> bool:
        """Можно ли повторять задание после такой ошибки."""
        if isinstance(exc, PermanentJobError):
            return False
        return not isinstance(exc, self.non_retryable)

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float:
        """Задержка (секунды) перед следующей попыткой после неудачной попытки ``attempt``."""
        if attempt < 1:
            raise ConfigError("attempt numbers start at 1")
        delay = min(self._raw_delay(attempt), self.max_delay)
        if self.jitter > 0:
            generator = rng if rng is not None else random.Random()
            delay = delay * generator.uniform(1 - self.jitter, 1 + self.jitter)
        return min(delay, self.max_delay)

    def _raw_delay(self, attempt: int) -> float:
        if self.base_delay == 0:
            return 0.0
        try:
            raw = self.base_delay * self.factor ** (attempt - 1)
        except OverflowError:
            return math.inf
        return raw
