import datetime as dt

import pytest

from ledger.clock import FixedClock


@pytest.fixture
def clock():
    return FixedClock(dt.datetime(2026, 4, 1, 9, 30, tzinfo=dt.timezone.utc))


@pytest.fixture
def write_csv(tmp_path):
    def _write(text, name="statement.csv", encoding="utf-8"):
        path = tmp_path / name
        path.write_bytes(text.encode(encoding))
        return path

    return _write
