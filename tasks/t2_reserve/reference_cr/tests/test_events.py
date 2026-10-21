from datetime import datetime, timedelta, timezone

import pytest

from warehouse.errors import EventFormatError
from warehouse.events import EventLog, format_timestamp, parse_line

T = datetime(2026, 3, 1, 10, 15, 0, 250000, tzinfo=timezone.utc)


def test_line_format_fields_sorted_and_missing_dash():
    log = EventLog()
    log.append(T, "ISSUE", wh="MAIN", sku="BOLT-M8", qty=2, ref=None)
    assert log.lines() == ["000001 2026-03-01T10:15:00Z ISSUE qty=2 ref=- sku=BOLT-M8 wh=MAIN"]


def test_sequence_numbers_are_continuous():
    log = EventLog()
    for _ in range(3):
        log.append(T, "RECEIVE", qty=1)
    assert [event.seq for event in log] == [1, 2, 3]


def test_timestamp_is_converted_to_utc():
    msk = timezone(timedelta(hours=3))
    assert format_timestamp(datetime(2026, 3, 1, 13, 0, tzinfo=msk)) == "2026-03-01T10:00:00Z"


def test_parse_line_roundtrip():
    log = EventLog()
    event = log.append(T, "TRANSFER", src="MAIN", dst="NORTH", sku="OIL-5L", qty=3, ref=None)
    parsed = parse_line(event.format())
    assert parsed.kind == "TRANSFER"
    assert parsed.seq == 1
    assert parsed.ts == T.replace(microsecond=0)
    assert dict(parsed.fields) == dict(event.fields)
    assert parsed.get("ref") is None


@pytest.mark.parametrize("value", ["two words", "", "a=b", 1.5, True])
def test_unloggable_values_rejected(value):
    with pytest.raises(EventFormatError):
        EventLog().append(T, "ISSUE", ref=value)


def test_bad_kind_rejected():
    with pytest.raises(EventFormatError):
        EventLog().append(T, "issue")


def test_parse_rejects_garbage():
    with pytest.raises(EventFormatError):
        parse_line("1 2026-03-01 ISSUE")


def test_events_filter_by_kind():
    log = EventLog()
    log.append(T, "RECEIVE", qty=1)
    log.append(T, "ISSUE", qty=1)
    assert [event.kind for event in log.events("ISSUE")] == ["ISSUE"]
