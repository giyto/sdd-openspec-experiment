from datetime import datetime, timezone

import pytest

from jobq import HandlerRegistry, JobQueue, ManualClock, Worker

START = datetime(2024, 3, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(START)


@pytest.fixture
def queue(clock: ManualClock) -> JobQueue:
    return JobQueue(clock=clock)


@pytest.fixture
def registry() -> HandlerRegistry:
    return HandlerRegistry()


@pytest.fixture
def worker(queue: JobQueue, registry: HandlerRegistry) -> Worker:
    return Worker(queue, registry)
