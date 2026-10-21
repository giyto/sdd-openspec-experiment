from datetime import datetime, timedelta, timezone

import pytest

from jobq import (
    ConfigError,
    DuplicateHandlerError,
    HandlerRegistry,
    InMemoryJobStore,
    Job,
    JobNotFoundError,
    JobqError,
    JobStatus,
    ManualClock,
    Metrics,
    UnknownJobTypeError,
)

from .conftest import START


def test_registry_register_and_get():
    registry = HandlerRegistry()
    handler = lambda job: None  # noqa: E731
    registry.register("a", handler)
    assert registry.get("a") is handler
    assert "a" in registry
    assert registry.job_types() == ["a"]


def test_registry_duplicate_and_replace():
    registry = HandlerRegistry()
    registry.register("a", lambda job: 1)
    with pytest.raises(DuplicateHandlerError):
        registry.register("a", lambda job: 2)
    registry.register("a", lambda job: 3, replace=True)
    assert registry.get("a")(None) == 3


def test_registry_decorator_and_errors():
    registry = HandlerRegistry()

    @registry.handler("b")
    def handle(job):
        return "ok"

    assert registry.get("b") is handle
    with pytest.raises(UnknownJobTypeError):
        registry.get("missing")
    with pytest.raises(ConfigError):
        registry.register("c", "not callable")


def test_store_due_filters_and_sorts():
    store = InMemoryJobStore()
    a = Job(id="a", job_type="t", run_at=START + timedelta(seconds=5), created_at=START, seq=1)
    b = Job(id="b", job_type="t", run_at=START, created_at=START, seq=2)
    c = Job(id="c", job_type="t", run_at=START, created_at=START, seq=3, status=JobStatus.FAILED)
    for job in (a, b, c):
        store.add(job)
    assert store.due(START) == [b]
    assert store.due(START + timedelta(seconds=5)) == [b, a]
    assert store.count_by_status()[JobStatus.FAILED] == 1


def test_store_errors():
    store = InMemoryJobStore()
    job = Job(id="x", job_type="t", run_at=START, created_at=START)
    store.add(job)
    with pytest.raises(JobqError):
        store.add(job)
    store.remove("x")
    with pytest.raises(JobNotFoundError):
        store.get("x")


def test_metrics_counters():
    metrics = Metrics()
    metrics.incr("jobs.b")
    metrics.incr("jobs.a", 3)
    metrics.incr("jobs.zero", 0)
    assert metrics.get("jobs.a") == 3
    assert metrics.get("jobs.unknown") == 0
    assert metrics.snapshot() == {"jobs.a": 3, "jobs.b": 1}
    with pytest.raises(JobqError):
        metrics.incr("jobs.a", -1)
    metrics.reset()
    assert metrics.snapshot() == {}


def test_manual_clock():
    clock = ManualClock(START)
    assert clock.advance(1.5) == START + timedelta(seconds=1.5)
    clock.set(START + timedelta(days=1))
    assert clock.now() == START + timedelta(days=1)
    with pytest.raises(ConfigError):
        clock.advance(-1)
    with pytest.raises(ConfigError):
        clock.set(START)
    with pytest.raises(ConfigError):
        ManualClock(datetime(2024, 1, 1))


def test_status_labels_and_terminal_flags():
    assert JobStatus.PENDING.label == "В очереди"
    assert JobStatus.FAILED.is_terminal
    assert not JobStatus.PENDING.is_terminal
    assert not JobStatus.RUNNING.is_terminal
    assert ManualClock().now().tzinfo is timezone.utc
