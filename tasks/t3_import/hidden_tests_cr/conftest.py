import datetime as dt

import pytest

from ledger.clock import FixedClock

FIXED_NOW = dt.datetime(2026, 4, 1, 9, 30, tzinfo=dt.timezone.utc)


@pytest.fixture
def clock():
    return FixedClock(FIXED_NOW)


@pytest.fixture
def write(tmp_path):
    """Пишет CSV в tmp_path в нужной кодировке; bom=True добавляет UTF-8 BOM."""
    counter = {"n": 0}

    def _write(text, *, encoding="utf-8", bom=False, name=None):
        counter["n"] += 1
        path = tmp_path / (name or f"statement_{counter['n']}.csv")
        data = text.encode(encoding)
        if bom:
            data = b"\xef\xbb\xbf" + data
        path.write_bytes(data)
        return path

    return _write
