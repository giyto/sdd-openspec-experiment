"""Приёмочные тесты JOBQ-212: политика повторов и dead-letter."""

from __future__ import annotations

import dataclasses
import random
from datetime import datetime, timedelta, timezone

import pytest

from jobq.clock import ManualClock
from jobq.dashboard import render_report
from jobq.errors import (
    ConfigError,
    InvalidTransitionError,
    JobNotFoundError,
)
from jobq.models import JobStatus
from jobq.queue import JobQueue
from jobq.registry import HandlerRegistry
from jobq.worker import Worker

try:  # новые имена из тикета; на старом коде их нет
    from jobq.retry import RetryPolicy
except ImportError:  # pragma: no cover
    RetryPolicy = None
try:
    from jobq.models import DeadLetterEntry
except ImportError:  # pragma: no cover
    DeadLetterEntry = None
try:
    from jobq.errors import PermanentJobError
except ImportError:  # pragma: no cover
    PermanentJobError = None

START = datetime(2024, 5, 6, 9, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- helpers


class Env:
    def __init__(self, default_policy=None, rng=None, with_default=True):
        self.clock = ManualClock(START)
        if with_default:
            self.queue = JobQueue(clock=self.clock, default_retry_policy=default_policy)
        else:
            self.queue = JobQueue(clock=self.clock)
        self.registry = HandlerRegistry()
        if rng is None:
            self.worker = Worker(self.queue, self.registry)
        else:
            self.worker = Worker(self.queue, self.registry, rng=rng)
        self.calls: list[tuple[str, int]] = []

    def always_fail(self, job_type, exc_factory=None):
        def handler(job):
            self.calls.append((job.id, job.attempts))
            if exc_factory is not None:
                raise exc_factory(job)
            raise RuntimeError(f"boom {job.attempts}")

        self.registry.register(job_type, handler)

    def fail_times(self, job_type, times, result="ok"):
        def handler(job):
            self.calls.append((job.id, job.attempts))
            if job.attempts <= times:
                raise RuntimeError(f"boom {job.attempts}")
            return result

        self.registry.register(job_type, handler)

    def metric(self, name):
        return self.queue.metrics.get(name)

    def get(self, job):
        return self.queue.get(job.id)


class RecordingRng(random.Random):
    def __init__(self, value):
        super().__init__(0)
        self.value = value
        self.calls = []

    def uniform(self, a, b):
        self.calls.append((a, b))
        return self.value


class ExplodingRng(random.Random):
    def __init__(self):
        super().__init__(0)

    def uniform(self, a, b):
        raise AssertionError("rng must not be used here")

    def random(self):
        raise AssertionError("rng must not be used here")


def close_to(actual: datetime, expected: datetime, tol: float = 1e-3) -> bool:
    return abs((actual - expected).total_seconds()) <= tol


def status_line(report: str, label: str) -> str:
    for line in report.splitlines():
        if line.strip().startswith(label):
            return line
    raise AssertionError(f"no line for {label!r} in report:\n{report}")


# --------------------------------------------------------------------------- R01


def test_R01_defaults():
    policy = RetryPolicy()
    assert policy.max_attempts == 3
    assert policy.base_delay == 1.0
    assert policy.factor == 2.0
    assert policy.max_delay == 60.0
    assert policy.jitter == 0.0
    assert tuple(policy.non_retryable) == ()


def test_R01_frozen():
    policy = RetryPolicy(max_attempts=5)
    assert dataclasses.is_dataclass(policy)
    with pytest.raises(AttributeError):
        policy.max_attempts = 7


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_attempts": 0},
        {"base_delay": -0.5},
        {"factor": 0.5},
        {"base_delay": 10.0, "max_delay": 5.0},
        {"jitter": 1.5},
        {"jitter": -0.1},
        {"non_retryable": (ValueError, "KeyError")},
        {"non_retryable": (int,)},
    ],
)
def test_R01_invalid_params_raise_config_error(kwargs):
    with pytest.raises(ConfigError):
        RetryPolicy(**kwargs)


def test_R01_non_retryable_list_is_stored_as_tuple():
    policy = RetryPolicy(non_retryable=[ValueError, KeyError])
    assert policy.non_retryable == (ValueError, KeyError)
    assert isinstance(policy.non_retryable, tuple)
    hash(policy)  # frozen dataclass с tuple остаётся хешируемым


# --------------------------------------------------------------------------- R02


def test_R02_exponential_sequence():
    policy = RetryPolicy(max_attempts=10, base_delay=2.0, factor=3.0, max_delay=1000.0)
    assert [policy.delay_for(n) for n in range(1, 6)] == pytest.approx([2, 6, 18, 54, 162])


def test_R02_capped_by_max_delay():
    policy = RetryPolicy(max_attempts=10, base_delay=1.0, factor=2.0, max_delay=10.0)
    assert policy.delay_for(4) == pytest.approx(8.0)
    assert policy.delay_for(5) == pytest.approx(10.0)
    assert policy.delay_for(9) == pytest.approx(10.0)


def test_R02_huge_attempt_numbers_do_not_overflow():
    policy = RetryPolicy(max_attempts=10_000, base_delay=1.0, factor=2.0, max_delay=30.0)
    assert policy.delay_for(5000) == pytest.approx(30.0)
    assert policy.delay_for(10_000) == pytest.approx(30.0)
    zero = RetryPolicy(max_attempts=10_000, base_delay=0.0, factor=2.0, max_delay=30.0)
    assert zero.delay_for(5000) == 0.0
    flat = RetryPolicy(max_attempts=10_000, base_delay=4.0, factor=1.0, max_delay=30.0)
    assert flat.delay_for(5000) == pytest.approx(4.0)


def test_R02_attempt_below_one_is_rejected():
    with pytest.raises(ConfigError):
        RetryPolicy().delay_for(0)


# --------------------------------------------------------------------------- R03


def test_R03_jitter_uses_one_uniform_call():
    policy = RetryPolicy(max_attempts=5, base_delay=10.0, factor=2.0, max_delay=100.0, jitter=0.25)
    rng = RecordingRng(1.2)
    assert policy.delay_for(1, rng) == pytest.approx(12.0)
    assert len(rng.calls) == 1
    low, high = rng.calls[0]
    assert low == pytest.approx(0.75)
    assert high == pytest.approx(1.25)
    rng.value = 0.8
    assert policy.delay_for(2, rng) == pytest.approx(16.0)
    assert len(rng.calls) == 2


def test_R03_jitter_never_exceeds_max_delay():
    policy = RetryPolicy(max_attempts=5, base_delay=10.0, factor=2.0, max_delay=10.0, jitter=0.5)
    assert policy.delay_for(1, RecordingRng(1.5)) == pytest.approx(10.0)
    assert policy.delay_for(4, RecordingRng(1.4)) == pytest.approx(10.0)
    # джиттер применяется к уже ограниченной задержке
    assert policy.delay_for(4, RecordingRng(0.5)) == pytest.approx(5.0)
    seeded = random.Random(99)
    for attempt in range(1, 50):
        assert 0.0 <= policy.delay_for(attempt, seeded) <= 10.0


def test_R03_zero_jitter_does_not_touch_rng():
    policy = RetryPolicy(max_attempts=5, base_delay=3.0, jitter=0.0)
    assert policy.delay_for(2, ExplodingRng()) == pytest.approx(6.0)


def test_R03_worker_uses_injected_rng_for_run_at():
    policy = RetryPolicy(max_attempts=4, base_delay=10.0, factor=2.0, max_delay=1000.0, jitter=0.2)
    env = Env(default_policy=policy, rng=random.Random(123))
    env.always_fail("sync")
    job = env.queue.enqueue("sync")

    expected_rng = random.Random(123)
    for attempt in (1, 2, 3):
        env.worker.run_once()
        now = env.clock.now()
        delay = 10.0 * 2.0 ** (attempt - 1) * expected_rng.uniform(0.8, 1.2)
        current = env.get(job)
        assert current.status is JobStatus.RETRY_SCHEDULED
        assert close_to(current.run_at, now + timedelta(seconds=delay))
        env.clock.set(current.run_at)


# --------------------------------------------------------------------------- R04


def test_R04_failure_schedules_retry():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=5.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")
    env.clock.advance(2)

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.RETRY_SCHEDULED
    assert current.run_at == START + timedelta(seconds=7)
    assert current.attempts == 1
    assert current.error == "RuntimeError: boom 1"
    assert not current.is_terminal
    assert env.metric("jobs.retried") == 1
    assert env.metric("jobs.failed") == 0


def test_R04_second_failure_uses_factor_and_latest_error():
    env = Env(default_policy=RetryPolicy(max_attempts=5, base_delay=5.0, factor=3.0, max_delay=100.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")

    env.worker.run_once()
    env.clock.advance(5)
    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.RETRY_SCHEDULED
    assert current.run_at == START + timedelta(seconds=5 + 15)
    assert current.attempts == 2
    assert current.error == "RuntimeError: boom 2"
    assert env.metric("jobs.retried") == 2
    assert env.metric("jobs.started") == 2
    assert env.metric("jobs.failed") == 0


def test_R04_retry_counters_with_type_policy_only():
    env = Env(with_default=False)
    env.queue.set_retry_policy("mail", RetryPolicy(max_attempts=2, base_delay=1.0))
    env.always_fail("mail")
    env.queue.enqueue("mail")
    env.worker.run_once()
    assert env.metric("jobs.retried") == 1
    assert env.metric("jobs.failed") == 0
    assert env.metric("jobs.dead_lettered") == 0


# --------------------------------------------------------------------------- R05


def test_R05_retry_is_not_picked_before_run_at():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=10.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")
    env.worker.run_once()

    env.clock.advance(9.999)
    assert env.worker.run_once() is None
    assert env.worker.run_pending() == 0
    assert env.get(job).attempts == 1

    env.clock.advance(0.001)
    assert env.worker.run_pending() == 1
    assert env.get(job).attempts == 2


def test_R05_retries_share_time_order_with_pending_jobs():
    env = Env(default_policy=RetryPolicy(max_attempts=5, base_delay=10.0))
    order = []

    def flaky(job):
        order.append(job.payload["name"])
        raise RuntimeError("temporary")

    env.registry.register("flaky", flaky)
    env.registry.register("rec", lambda job: order.append(job.payload["name"]))

    env.queue.enqueue("flaky", {"name": "A"})
    env.queue.enqueue("rec", {"name": "B"}, delay=15)
    env.worker.run_once()  # A падает, повтор на START+10
    env.queue.enqueue("rec", {"name": "C"}, delay=5)  # START+5
    env.queue.enqueue("rec", {"name": "D"}, run_at=START + timedelta(seconds=10))

    env.clock.advance(20)
    env.worker.run_pending(max_jobs=4)

    # C(+5), затем A и D (+10, A поставлено раньше), затем B(+15)
    assert order == ["A", "C", "A", "D", "B"]


def test_R05_zero_delay_retry_runs_in_same_run_pending():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=0.0, factor=2.0, max_delay=0.0))
    env.fail_times("sync", 2, result=42)
    job = env.queue.enqueue("sync")

    assert env.worker.run_pending() == 3

    current = env.get(job)
    assert current.status is JobStatus.SUCCEEDED
    assert current.result == 42
    assert current.attempts == 3


# --------------------------------------------------------------------------- R06


def _exhaust(env, job, delays):
    env.worker.run_once()
    for delay in delays:
        env.clock.advance(delay)
        env.worker.run_once()
    return env.get(job)


def test_R06_max_attempts_includes_first_attempt():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=1.0, factor=2.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")

    current = _exhaust(env, job, [1, 2])

    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 3
    assert len(env.calls) == 3
    assert env.metric("jobs.retried") == 2
    assert env.metric("jobs.dead_lettered") == 1
    assert env.metric("jobs.failed") == 0
    env.clock.advance(3600)
    assert env.worker.run_pending() == 0


def test_R06_dead_letter_entry_fields():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=1.0, factor=2.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")

    current = _exhaust(env, job, [1, 2])

    entries = env.queue.dead_letters()
    assert len(entries) == 1
    entry = entries[0]
    assert isinstance(entry, DeadLetterEntry)
    assert entry.job_id == job.id
    assert entry.job_type == "mail"
    assert entry.attempts == 3
    assert entry.error == "RuntimeError: boom 3"
    assert entry.error == current.error
    assert entry.dead_lettered_at == START + timedelta(seconds=3)
    with pytest.raises(AttributeError):
        entry.attempts = 1


def test_R06_single_attempt_policy_goes_to_dead_letter():
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 1
    assert [e.job_id for e in env.queue.dead_letters()] == [job.id]
    assert env.metric("jobs.retried") == 0
    assert env.metric("jobs.failed") == 0
    assert env.metric("jobs.dead_lettered") == 1


def test_R06_rng_not_used_when_dead_lettering():
    policy = RetryPolicy(max_attempts=1, base_delay=5.0, jitter=0.5)
    env = Env(default_policy=policy, rng=ExplodingRng())
    env.always_fail("mail")
    job = env.queue.enqueue("mail")
    env.worker.run_once()
    assert env.get(job).status is JobStatus.DEAD_LETTERED


def test_R06_rng_sequence_not_consumed_by_final_attempt():
    policy = RetryPolicy(max_attempts=2, base_delay=10.0, factor=1.0, max_delay=100.0, jitter=0.5)
    env = Env(default_policy=policy, rng=random.Random(7))
    env.always_fail("mail")
    first = env.queue.enqueue("mail")
    env.worker.run_once()  # first: повтор, 1-й вызов uniform
    env.clock.set(env.get(first).run_at)
    env.worker.run_once()  # first: dead-letter, uniform не вызывается
    assert env.get(first).status is JobStatus.DEAD_LETTERED

    second = env.queue.enqueue("mail")
    env.worker.run_once()  # second: повтор, 2-й вызов uniform

    expected_rng = random.Random(7)
    expected_rng.uniform(0.5, 1.5)
    expected = env.clock.now() + timedelta(seconds=10.0 * expected_rng.uniform(0.5, 1.5))
    assert close_to(env.get(second).run_at, expected)


# --------------------------------------------------------------------------- R07


class BadInput(ValueError):
    pass


def test_R07_subclass_of_non_retryable_fails_immediately():
    env = Env(default_policy=RetryPolicy(max_attempts=5, non_retryable=(ValueError,)))
    env.always_fail("parse", lambda job: BadInput("broken csv"))
    job = env.queue.enqueue("parse")

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.FAILED
    assert current.error == "BadInput: broken csv"
    assert current.attempts == 1
    assert env.metric("jobs.failed") == 1
    assert env.metric("jobs.retried") == 0
    assert env.queue.dead_letters() == []


def test_R07_permanent_error_is_never_retried():
    class Rejected(PermanentJobError):
        pass

    env = Env(default_policy=RetryPolicy(max_attempts=5), rng=ExplodingRng())
    env.always_fail("charge", lambda job: Rejected("card declined"))
    job = env.queue.enqueue("charge")

    env.worker.run_once()

    assert env.get(job).status is JobStatus.FAILED
    assert env.metric("jobs.failed") == 1
    assert env.metric("jobs.retried") == 0
    assert env.queue.dead_letters() == []


def test_R07_non_retryable_on_last_attempt_is_failed_not_dead_letter():
    env = Env(default_policy=RetryPolicy(max_attempts=2, base_delay=1.0, non_retryable=(KeyError,)))

    def handler(job):
        if job.attempts == 1:
            raise RuntimeError("temporary")
        raise KeyError("customer")

    env.registry.register("sync", handler)
    job = env.queue.enqueue("sync")
    env.worker.run_once()
    env.clock.advance(1)
    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.FAILED
    assert current.error.startswith("KeyError:")
    assert current.attempts == 2
    assert env.queue.dead_letters() == []
    assert env.metric("jobs.dead_lettered") == 0
    assert env.metric("jobs.failed") == 1
    assert env.metric("jobs.retried") == 1


def test_R07_is_retryable():
    policy = RetryPolicy(non_retryable=(LookupError,))
    assert policy.is_retryable(RuntimeError("x")) is True
    assert policy.is_retryable(IndexError("x")) is False
    assert policy.is_retryable(LookupError("x")) is False
    assert policy.is_retryable(PermanentJobError("x")) is False
    assert RetryPolicy().is_retryable(PermanentJobError("x")) is False
    assert issubclass(PermanentJobError, Exception)
    from jobq.errors import JobqError

    assert issubclass(PermanentJobError, JobqError)


# --------------------------------------------------------------------------- R08


def test_R08_type_policy_replaces_default_entirely():
    default = RetryPolicy(max_attempts=5, base_delay=100.0, max_delay=1000.0, non_retryable=(ValueError,))
    env = Env(default_policy=default)
    env.queue.set_retry_policy("import", RetryPolicy(max_attempts=2, base_delay=1.0))
    env.always_fail("import", lambda job: ValueError(f"bad row {job.attempts}"))
    job = env.queue.enqueue("import")

    env.worker.run_once()
    current = env.get(job)
    assert current.status is JobStatus.RETRY_SCHEDULED  # ValueError не исключён в политике типа
    assert current.run_at == START + timedelta(seconds=1)

    env.clock.advance(1)
    env.worker.run_once()
    current = env.get(job)
    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 2


def test_R08_retry_policy_for_resolution():
    default = RetryPolicy(max_attempts=4)
    special = RetryPolicy(max_attempts=9)
    env = Env(default_policy=default)
    assert env.queue.retry_policy_for("any") == default
    env.queue.set_retry_policy("special", special)
    assert env.queue.retry_policy_for("special") == special
    assert env.queue.retry_policy_for("other") == default
    env.queue.set_retry_policy("special", None)
    assert env.queue.retry_policy_for("special") == default

    bare = JobQueue(clock=ManualClock(START))
    assert bare.retry_policy_for("any") is None


def test_R08_default_policy_applies_to_types_without_own_policy():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=7.0))
    env.queue.set_retry_policy("special", RetryPolicy(max_attempts=3, base_delay=1.0))
    env.always_fail("plain")
    job = env.queue.enqueue("plain")
    env.worker.run_once()
    assert env.get(job).run_at == START + timedelta(seconds=7)


def test_R08_policy_is_resolved_at_failure_time():
    env = Env(with_default=False)
    env.always_fail("sync")
    job = env.queue.enqueue("sync")
    env.queue.set_retry_policy("sync", RetryPolicy(max_attempts=5, base_delay=1.0))

    env.worker.run_once()
    assert env.get(job).status is JobStatus.RETRY_SCHEDULED

    env.queue.set_retry_policy("sync", RetryPolicy(max_attempts=2, base_delay=1.0))
    env.clock.advance(1)
    env.worker.run_once()
    assert env.get(job).status is JobStatus.DEAD_LETTERED


# --------------------------------------------------------------------------- R09


def test_R09_type_without_any_policy_keeps_old_behaviour():
    env = Env(with_default=False)
    env.queue.set_retry_policy("other", RetryPolicy(max_attempts=5))
    env.always_fail("plain")
    job = env.queue.enqueue("plain")

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.FAILED
    assert current.error == "RuntimeError: boom 1"
    assert env.metric("jobs.failed") == 1
    assert env.metric("jobs.retried") == 0
    assert env.queue.dead_letters() == []


def test_R09_removing_type_policy_without_default_restores_old_behaviour():
    env = Env(default_policy=None)
    env.queue.set_retry_policy("plain", RetryPolicy(max_attempts=5))
    env.queue.set_retry_policy("plain", None)
    env.always_fail("plain")
    job = env.queue.enqueue("plain")
    env.worker.run_once()
    assert env.get(job).status is JobStatus.FAILED
    assert env.queue.dead_letters() == []


def test_R09_unknown_job_type_fails_despite_policy():
    env = Env(default_policy=RetryPolicy(max_attempts=5, base_delay=1.0))
    env.queue.set_retry_policy("ghost", RetryPolicy(max_attempts=5, base_delay=1.0))
    job = env.queue.enqueue("ghost")

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.FAILED
    assert current.error.startswith("UnknownJobTypeError:")
    assert env.metric("jobs.failed") == 1
    assert env.metric("jobs.retried") == 0
    assert env.queue.dead_letters() == []


# --------------------------------------------------------------------------- R10


def _dead_job(env, job_type="mail"):
    job = env.queue.enqueue(job_type)
    env.worker.run_once()
    assert env.get(job).status is JobStatus.DEAD_LETTERED
    return job


def test_R10_requeue_resets_job():
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    job = _dead_job(env)
    enqueued_before = env.metric("jobs.enqueued")
    jobs_before = len(env.queue.list_jobs())
    env.clock.advance(50)

    returned = env.queue.requeue_dead_letter(job.id)

    current = env.get(job)
    assert returned.id == job.id
    assert current.status is JobStatus.PENDING
    assert current.attempts == 0
    assert current.error is None
    assert current.run_at == START + timedelta(seconds=50)
    assert env.queue.dead_letters() == []
    assert env.metric("jobs.requeued") == 1
    assert env.metric("jobs.enqueued") == enqueued_before
    assert len(env.queue.list_jobs()) == jobs_before
    assert env.queue.next_due().id == job.id


def test_R10_requeued_job_gets_full_set_of_attempts():
    env = Env(default_policy=RetryPolicy(max_attempts=2, base_delay=1.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")
    _exhaust(env, job, [1])
    env.queue.requeue_dead_letter(job.id)

    env.worker.run_once()
    current = env.get(job)
    assert current.status is JobStatus.RETRY_SCHEDULED
    assert current.attempts == 1
    assert current.error == "RuntimeError: boom 1"

    env.clock.advance(1)
    env.worker.run_once()
    current = env.get(job)
    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 2
    assert [e.attempts for e in env.queue.dead_letters()] == [2]


def test_R10_requeue_errors():
    env = Env(default_policy=None)
    env.always_fail("plain")
    pending = env.queue.enqueue("plain", delay=100)
    failed = env.queue.enqueue("plain")
    env.worker.run_once()
    assert env.get(failed).status is JobStatus.FAILED

    with pytest.raises(JobNotFoundError):
        env.queue.requeue_dead_letter("job-424242")
    with pytest.raises(InvalidTransitionError):
        env.queue.requeue_dead_letter(pending.id)
    with pytest.raises(InvalidTransitionError):
        env.queue.requeue_dead_letter(failed.id)
    assert env.metric("jobs.requeued") == 0


def test_R10_dead_letters_keep_arrival_order():
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    a = env.queue.enqueue("mail")
    b = env.queue.enqueue("mail")
    env.worker.run_once()  # a
    env.worker.run_once()  # b
    assert [e.job_id for e in env.queue.dead_letters()] == [a.id, b.id]

    env.queue.requeue_dead_letter(a.id)
    assert [e.job_id for e in env.queue.dead_letters()] == [b.id]
    env.worker.run_once()  # a снова

    assert [e.job_id for e in env.queue.dead_letters()] == [b.id, a.id]


# --------------------------------------------------------------------------- R11


def test_R11_cancel_job_waiting_for_retry():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=5.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")
    env.worker.run_once()

    env.queue.cancel(job.id)

    assert env.get(job).status is JobStatus.CANCELLED
    assert env.metric("jobs.cancelled") == 1
    env.clock.advance(60)
    assert env.worker.run_pending() == 0
    assert len(env.calls) == 1


def test_R11_dead_lettered_job_cannot_be_cancelled():
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    job = _dead_job(env)

    with pytest.raises(InvalidTransitionError):
        env.queue.cancel(job.id)

    assert env.get(job).status is JobStatus.DEAD_LETTERED
    assert [e.job_id for e in env.queue.dead_letters()] == [job.id]
    assert env.metric("jobs.cancelled") == 0


# --------------------------------------------------------------------------- R12


def test_R12_success_after_retry_clears_error():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=2.0))
    env.fail_times("mail", 1, result="sent")
    job = env.queue.enqueue("mail")
    env.worker.run_once()
    assert env.get(job).error == "RuntimeError: boom 1"

    env.clock.advance(2)
    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.SUCCEEDED
    assert current.result == "sent"
    assert current.error is None
    assert current.attempts == 2
    assert env.metric("jobs.succeeded") == 1
    assert env.metric("jobs.started") == 2
    assert env.queue.dead_letters() == []


def test_R12_handler_sees_current_attempt_number():
    env = Env(default_policy=RetryPolicy(max_attempts=4, base_delay=1.0, factor=1.0))
    env.fail_times("mail", 2)
    job = env.queue.enqueue("mail")
    for _ in range(3):
        env.worker.run_once()
        env.clock.advance(1)
    assert [attempt for _, attempt in env.calls] == [1, 2, 3]
    assert env.get(job).status is JobStatus.SUCCEEDED


# --------------------------------------------------------------------------- R13


def test_R13_new_status_values():
    assert JobStatus("retry_scheduled") is JobStatus.RETRY_SCHEDULED
    assert JobStatus("dead_lettered") is JobStatus.DEAD_LETTERED
    assert JobStatus.RETRY_SCHEDULED.label == "Ожидает повтора"
    assert JobStatus.DEAD_LETTERED.label == "В dead-letter"


def test_R13_terminal_flags():
    assert JobStatus.DEAD_LETTERED.is_terminal is True
    assert JobStatus.RETRY_SCHEDULED.is_terminal is False
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    job = _dead_job(env)
    assert env.get(job).is_terminal


def test_R13_stats_and_list_jobs_include_new_statuses():
    env = Env(with_default=False)
    env.queue.set_retry_policy("retry", RetryPolicy(max_attempts=3, base_delay=10.0))
    env.queue.set_retry_policy("dead", RetryPolicy(max_attempts=1))
    env.always_fail("retry")
    env.always_fail("dead")
    r = env.queue.enqueue("retry")
    d = env.queue.enqueue("dead")
    env.queue.enqueue("retry", delay=100)
    env.worker.run_pending()

    stats = env.queue.stats()
    assert stats["retry_scheduled"] == 1
    assert stats["dead_lettered"] == 1
    assert stats["pending"] == 1
    assert stats["failed"] == 0
    assert sum(stats.values()) == 3
    assert [j.id for j in env.queue.list_jobs(JobStatus.RETRY_SCHEDULED)] == [r.id]
    assert [j.id for j in env.queue.list_jobs(JobStatus.DEAD_LETTERED)] == [d.id]


def test_R13_dashboard_shows_new_statuses():
    env = Env(with_default=False)
    env.queue.set_retry_policy("retry", RetryPolicy(max_attempts=3, base_delay=10.0))
    env.queue.set_retry_policy("dead", RetryPolicy(max_attempts=1))
    env.always_fail("retry")
    env.always_fail("dead")
    env.queue.enqueue("retry")
    env.queue.enqueue("dead")
    env.queue.enqueue("dead")
    env.worker.run_pending()

    report = render_report(env.queue)

    assert status_line(report, "Ожидает повтора").split()[-1] == "1"
    assert status_line(report, "В dead-letter").split()[-1] == "2"
    assert status_line(report, "Всего").split()[-1] == "3"
    assert "jobs.dead_lettered" in report
    assert "jobs.retried" in report


def test_R13_purge_keeps_dead_letters():
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    job = _dead_job(env)
    cancelled = env.queue.enqueue("mail", delay=1000)
    env.queue.cancel(cancelled.id)
    env.clock.advance(3600)

    assert env.queue.purge_finished(older_than=10) == 1

    assert env.get(job).status is JobStatus.DEAD_LETTERED
    assert [e.job_id for e in env.queue.dead_letters()] == [job.id]
    with pytest.raises(JobNotFoundError):
        env.queue.get(cancelled.id)
    env.queue.requeue_dead_letter(job.id)
    assert env.get(job).status is JobStatus.PENDING


# --------------------------------------------------------------------------- API compat


def _old_env():
    clock = ManualClock(START)
    queue = JobQueue(clock=clock)
    registry = HandlerRegistry()
    return clock, queue, registry


def test_API_enqueue_and_queue_constructor_unchanged():
    clock = ManualClock(START)
    queue = JobQueue(None, clock=clock)
    a = queue.enqueue("t", {"a": 1}, delay=5)
    b = queue.enqueue("t", run_at=START + timedelta(seconds=1))
    c = queue.enqueue("t")
    assert a.run_at == START + timedelta(seconds=5)
    assert b.run_at == START + timedelta(seconds=1)
    assert c.status is JobStatus.PENDING
    assert queue.next_due().id == c.id


def test_API_worker_construction_and_run_methods():
    clock, queue, registry = _old_env()
    registry.register("t", lambda job: job.payload.get("v"))
    registry.register("t", lambda job: "replaced", replace=True)
    Worker(queue, registry, name="named")
    worker = Worker(queue, registry)
    for _ in range(3):
        queue.enqueue("t")
    done = worker.run_once()
    assert done.status is JobStatus.SUCCEEDED
    assert done.result == "replaced"
    assert worker.run_pending(max_jobs=1) == 1
    assert worker.run_pending() == 1
    assert worker.run_once() is None


def test_API_failure_without_policy_is_failed():
    clock, queue, registry = _old_env()

    def boom(job):
        raise RuntimeError("disk is full")

    registry.register("boom", boom)
    job = queue.enqueue("boom")
    Worker(queue, registry).run_once()
    current = queue.get(job.id)
    assert current.status is JobStatus.FAILED
    assert current.error == "RuntimeError: disk is full"
    assert current.attempts == 1
    assert queue.metrics.get("jobs.failed") == 1


def test_API_cancel_stats_and_purge():
    clock, queue, registry = _old_env()
    a = queue.enqueue("t")
    queue.enqueue("t", delay=10)
    queue.cancel(a.id)
    with pytest.raises(InvalidTransitionError):
        queue.cancel(a.id)
    stats = queue.stats()
    for key in ("pending", "running", "succeeded", "failed", "cancelled"):
        assert key in stats
    assert stats["cancelled"] == 1
    assert stats["pending"] == 1
    clock.advance(100)
    assert queue.purge_finished(older_than=50) == 1
    assert queue.metrics.get("jobs.cancelled") == 1


def test_API_dashboard_old_statuses_still_rendered():
    clock, queue, registry = _old_env()
    registry.register("ok", lambda job: None)
    queue.enqueue("ok")
    Worker(queue, registry).run_pending()
    report = render_report(queue)
    for label in ("В очереди", "Выполняется", "Выполнено", "Ошибка", "Отменено"):
        status_line(report, label)
    assert status_line(report, "Выполнено").split()[-1] == "1"
