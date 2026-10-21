"""Журнал складских событий.

Каждое событие сериализуется в одну строку::

    000003 2026-03-01T10:15:00Z ISSUE qty=2 ref=SO-17 sku=BOLT-M8 wh=MAIN

* порядковый номер — 6 цифр, растёт с 1 без пропусков;
* время — UTC, формат :data:`TIMESTAMP_FORMAT` (секундная точность, суффикс ``Z``);
* тип события — заглавные латинские буквы и ``_``;
* поля ``key=value`` в алфавитном порядке ключей, отсутствующее значение — ``-``.

Журнал — источник данных для отчётов о движении и для внешней выгрузки,
поэтому формат строки менять нельзя.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Iterator, Mapping

from .errors import EventFormatError

logger = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
MISSING = "-"

_KIND_RE = re.compile(r"^[A-Z][A-Z_]*$")
_KEY_RE = re.compile(r"^[a-z][a-z_]*$")


def format_timestamp(moment: datetime) -> str:
    """Момент времени в формате журнала."""
    if moment.tzinfo is None:
        raise EventFormatError("naive datetime cannot be written to the event log")
    return moment.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def parse_timestamp(text: str) -> datetime:
    try:
        parsed = datetime.strptime(text, TIMESTAMP_FORMAT)
    except ValueError as exc:
        raise EventFormatError(f"bad timestamp {text!r}") from exc
    return parsed.replace(tzinfo=timezone.utc)


def _format_value(key: str, value: object) -> str:
    if value is None:
        return MISSING
    if isinstance(value, bool):
        raise EventFormatError(f"field {key!r}: booleans are not supported")
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        if not value or any(ch.isspace() for ch in value) or "=" in value:
            raise EventFormatError(f"field {key!r}: value {value!r} cannot be logged")
        return value
    raise EventFormatError(f"field {key!r}: unsupported type {type(value).__name__}")


@dataclass(frozen=True)
class Event:
    """Одна запись журнала. Значения полей хранятся уже в строковом виде."""

    seq: int
    ts: datetime
    kind: str
    fields: Mapping[str, str] = field(default_factory=dict)

    def format(self) -> str:
        parts = [f"{self.seq:06d}", format_timestamp(self.ts), self.kind]
        parts.extend(f"{key}={self.fields[key]}" for key in sorted(self.fields))
        return " ".join(parts)

    def get(self, key: str) -> str | None:
        """Значение поля или ``None``, если поле отсутствует или равно ``-``."""
        value = self.fields.get(key)
        return None if value in (None, MISSING) else value


def parse_line(line: str) -> Event:
    """Разбор строки журнала обратно в :class:`Event`."""
    tokens = line.strip().split(" ")
    if len(tokens) < 3:
        raise EventFormatError(f"malformed event line {line!r}")
    seq_text, ts_text, kind, *pairs = tokens
    if not (len(seq_text) == 6 and seq_text.isdigit()):
        raise EventFormatError(f"bad sequence number {seq_text!r}")
    if not _KIND_RE.match(kind):
        raise EventFormatError(f"bad event kind {kind!r}")
    fields: dict[str, str] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not _KEY_RE.match(key) or not value:
            raise EventFormatError(f"bad field {pair!r}")
        fields[key] = value
    return Event(int(seq_text), parse_timestamp(ts_text), kind, MappingProxyType(fields))


class EventLog:
    """Журнал событий в памяти, только на добавление."""

    def __init__(self) -> None:
        self._events: list[Event] = []

    def append(self, ts: datetime, kind: str, **fields: object) -> Event:
        if not _KIND_RE.match(kind):
            raise EventFormatError(f"bad event kind {kind!r}")
        rendered: dict[str, str] = {}
        for key, value in fields.items():
            if not _KEY_RE.match(key):
                raise EventFormatError(f"bad field name {key!r}")
            rendered[key] = _format_value(key, value)
        # время в журнале — с точностью до секунды
        ts = ts.astimezone(timezone.utc).replace(microsecond=0)
        event = Event(len(self._events) + 1, ts, kind, MappingProxyType(rendered))
        self._events.append(event)
        logger.debug("event %s", event.format())
        return event

    def events(self, kind: str | None = None) -> list[Event]:
        if kind is None:
            return list(self._events)
        return [event for event in self._events if event.kind == kind]

    def lines(self) -> list[str]:
        return [event.format() for event in self._events]

    def __iter__(self) -> Iterator[Event]:
        return iter(list(self._events))

    def __len__(self) -> int:
        return len(self._events)
