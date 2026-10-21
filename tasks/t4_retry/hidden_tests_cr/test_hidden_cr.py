"""Приёмочные тесты JOBQ-237: доработки повторов и dead-letter."""

from __future__ import annotations

import inspect
import random
from datetime import datetime, timedelta, timezone

import pytest

from jobq.clock import ManualClock
from jobq.dashboard import render_report
from jobq.errors import ConfigError, JobNotFoundError, JobqError
from jobq.models import JobStatus
from jobq.queue import JobQueue
from jobq.registry import HandlerRegistry
from jobq.worker import Worker

try:
    from jobq.retry import RetryPolicy
except ImportError:  # pragma: no cover
    RetryPolicy = None
try:
    from jobq.errors import PermanentJobError
except ImportError:  # pragma: no cover
    PermanentJobError = None
try:
    from jobq.errors import RetryLaterError
except ImportError:  # pragma: no cover
    RetryLaterError = None
try:
    from jobq.models import DeadLetterReason
except ImportError:  # pragma: no cover
    DeadLetterReason = None

START = datetime(2024, 11, 4, 8, 0, tzinfo=timezone.utc)


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

    def handler(self, job_type, behaviour):
        """behaviour(job) возвращает исключение (бросаем его) или результат."""

        def handler(job):
            self.calls.append((job.id, job.attempts))
            outcome = behaviour(job)
            if isinstance(outcome, BaseException):
                raise outcome
            return outcome

        self.registry.register(job_type, handler)

    def always_fail(self, job_type):
        self.handler(job_type, lambda job: RuntimeError(f"boom {job.attempts}"))

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


class BadInput(ValueError):
    pass


def close_to(actual, expected, tol=1e-3):
    return abs((actual - expected).total_seconds()) <= tol


def status_line(report, label):
    for line in report.splitlines():
        if line.strip().startswith(label):
            return line
    raise AssertionError(f"no line for {label!r} in report:\n{report}")


def dead_ids(env):
    return [entry.job_id for entry in env.queue.dead_letters()]


# --------------------------------------------------------------------------- C01


def test_C01_non_retryable_subclass_goes_to_dead_letter():
    env = Env(default_policy=RetryPolicy(max_attempts=5, non_retryable=(ValueError,)))
    env.handler("parse", lambda job: BadInput("broken csv"))
    job = env.queue.enqueue("parse")

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 1
    assert current.error == "BadInput: broken csv"
    assert dead_ids(env) == [job.id]
    assert env.queue.dead_letters()[0].error == "BadInput: broken csv"
    env.clock.advance(3600)
    assert env.worker.run_pending() == 0
    assert len(env.calls) == 1


def test_C01_permanent_error_goes_to_dead_letter():
    env = Env(default_policy=RetryPolicy(max_attempts=5))
    env.handler("charge", lambda job: PermanentJobError("card declined"))
    job = env.queue.enqueue("charge")

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 1
    assert dead_ids(env) == [job.id]


def test_C01_non_retryable_after_retry_goes_to_dead_letter():
    env = Env(default_policy=RetryPolicy(max_attempts=5, base_delay=1.0, non_retryable=(KeyError,)))
    env.handler("sync", lambda job: RuntimeError("temporary") if job.attempts == 1 else KeyError("customer"))
    job = env.queue.enqueue("sync")

    env.worker.run_once()
    assert env.get(job).status is JobStatus.RETRY_SCHEDULED
    env.clock.advance(1)
    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 2
    assert current.error.startswith("KeyError:")
    assert env.queue.dead_letters()[0].attempts == 2


def test_C01_type_policy_non_retryable_dead_letters_and_requeue_works():
    env = Env(with_default=False)
    env.queue.set_retry_policy("parse", RetryPolicy(max_attempts=3, non_retryable=(ValueError,)))
    env.handler("parse", lambda job: BadInput("bad") if job.payload.get("broken") else "ok")
    job = env.queue.enqueue("parse", {"broken": True})
    env.worker.run_once()
    assert env.get(job).status is JobStatus.DEAD_LETTERED

    env.queue.requeue_dead_letter(job.id)
    assert env.get(job).status is JobStatus.PENDING
    assert dead_ids(env) == []


# --------------------------------------------------------------------------- C02


def test_C02_jitter_range_is_downward_only():
    policy = RetryPolicy(max_attempts=5, base_delay=10.0, factor=2.0, max_delay=100.0, jitter=0.25)
    rng = RecordingRng(0.9)
    assert policy.delay_for(1, rng) == pytest.approx(9.0)
    assert len(rng.calls) == 1
    low, high = rng.calls[0]
    assert low == pytest.approx(0.75)
    assert high == pytest.approx(1.0)


def test_C02_seeded_delay_never_above_computed():
    policy = RetryPolicy(max_attempts=100, base_delay=2.0, factor=2.0, max_delay=50.0, jitter=0.4)
    rng = random.Random(2024)
    for attempt in range(1, 60):
        capped = min(2.0 * 2.0 ** (attempt - 1), 50.0)
        delay = policy.delay_for(attempt, rng)
        assert capped * 0.6 - 1e-9 <= delay <= capped + 1e-9


def test_C02_worker_run_at_uses_downward_jitter():
    policy = RetryPolicy(max_attempts=4, base_delay=10.0, factor=2.0, max_delay=1000.0, jitter=0.2)
    env = Env(default_policy=policy, rng=random.Random(321))
    env.always_fail("sync")
    job = env.queue.enqueue("sync")

    expected_rng = random.Random(321)
    for attempt in (1, 2, 3):
        env.worker.run_once()
        delay = 10.0 * 2.0 ** (attempt - 1) * expected_rng.uniform(0.8, 1.0)
        current = env.get(job)
        assert current.status is JobStatus.RETRY_SCHEDULED
        assert close_to(current.run_at, env.clock.now() + timedelta(seconds=delay))
        env.clock.set(current.run_at)


# --------------------------------------------------------------------------- C03


def test_C03_purge_removes_old_dead_letters():
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    dead = env.queue.enqueue("mail")
    env.worker.run_once()
    cancelled = env.queue.enqueue("mail", delay=1000)
    env.queue.cancel(cancelled.id)
    env.clock.advance(3600)

    assert env.queue.purge_finished(older_than=10) == 2

    assert env.queue.dead_letters() == []
    with pytest.raises(JobNotFoundError):
        env.queue.get(dead.id)
    assert env.metric("jobs.purged") == 2
    assert env.queue.stats()["dead_lettered"] == 0


def test_C03_age_counted_from_dead_letter_moment():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=100.0, factor=1.0, max_delay=100.0))
    env.always_fail("mail")
    job = env.queue.enqueue("mail")
    env.worker.run_once()
    env.clock.advance(100)
    env.worker.run_once()
    env.clock.advance(100)
    env.worker.run_once()  # dead-letter на START+200
    assert env.get(job).status is JobStatus.DEAD_LETTERED

    env.clock.advance(5)  # START+205: задание создано давно, но в dead-letter всего 5 секунд
    assert env.queue.purge_finished(older_than=10) == 0
    assert dead_ids(env) == [job.id]

    env.clock.advance(5)  # ровно 10 секунд в dead-letter
    assert env.queue.purge_finished(older_than=10) == 1
    assert dead_ids(env) == []


def test_C03_purge_keeps_fresh_dead_letters_and_non_terminal_jobs():
    env = Env(default_policy=RetryPolicy(max_attempts=2, base_delay=10_000.0, max_delay=10_000.0))
    env.always_fail("mail")
    old = env.queue.enqueue("mail")
    env.queue.set_retry_policy("once", RetryPolicy(max_attempts=1))
    env.always_fail("once")
    old_dead = env.queue.enqueue("once")
    env.worker.run_pending()  # old -> retry_scheduled, old_dead -> dead-letter
    env.clock.advance(500)
    fresh_dead = env.queue.enqueue("once")
    env.worker.run_once()

    assert env.queue.purge_finished(older_than=100) == 1

    assert dead_ids(env) == [fresh_dead.id]
    assert env.get(old).status is JobStatus.RETRY_SCHEDULED
    with pytest.raises(JobNotFoundError):
        env.queue.get(old_dead.id)


# --------------------------------------------------------------------------- C04


def test_C04_reason_enum_values():
    assert DeadLetterReason("exhausted") is DeadLetterReason.EXHAUSTED
    assert DeadLetterReason("non_retryable") is DeadLetterReason.NON_RETRYABLE
    assert DeadLetterReason.EXHAUSTED == "exhausted"


def test_C04_exhausted_reason():
    env = Env(default_policy=RetryPolicy(max_attempts=2, base_delay=1.0))
    env.always_fail("mail")
    env.queue.enqueue("mail")
    env.worker.run_once()
    env.clock.advance(1)
    env.worker.run_once()
    (entry,) = env.queue.dead_letters()
    assert entry.reason is DeadLetterReason.EXHAUSTED
    assert entry.attempts == 2


def test_C04_non_retryable_reason():
    env = Env(default_policy=RetryPolicy(max_attempts=5, non_retryable=(ValueError,)))
    env.handler("parse", lambda job: BadInput("x"))
    env.handler("charge", lambda job: PermanentJobError("declined"))
    env.queue.enqueue("parse")
    env.queue.enqueue("charge")
    env.worker.run_pending()
    assert [e.reason for e in env.queue.dead_letters()] == [
        DeadLetterReason.NON_RETRYABLE,
        DeadLetterReason.NON_RETRYABLE,
    ]


def test_C04_non_retryable_on_last_attempt_has_non_retryable_reason():
    env = Env(default_policy=RetryPolicy(max_attempts=2, base_delay=1.0, non_retryable=(KeyError,)))
    env.handler("sync", lambda job: RuntimeError("temporary") if job.attempts == 1 else KeyError("x"))
    job = env.queue.enqueue("sync")
    env.worker.run_once()
    env.clock.advance(1)
    env.worker.run_once()
    (entry,) = env.queue.dead_letters()
    assert entry.job_id == job.id
    assert entry.attempts == 2
    assert entry.reason is DeadLetterReason.NON_RETRYABLE


# --------------------------------------------------------------------------- C05


def _three_dead(env):
    """Три задания попадают в dead-letter в порядке b, c, a (не совпадает с порядком постановки)."""
    env.queue.set_retry_policy("slow", RetryPolicy(max_attempts=2, base_delay=5.0))
    env.queue.set_retry_policy("fast", RetryPolicy(max_attempts=1))
    env.always_fail("slow")
    env.always_fail("fast")
    a = env.queue.enqueue("slow")
    b = env.queue.enqueue("fast")
    c = env.queue.enqueue("fast")
    env.worker.run_pending()  # a -> retry, b, c -> dead
    env.clock.advance(5)
    env.worker.run_pending()  # a -> dead
    assert dead_ids(env) == [b.id, c.id, a.id]
    return a, b, c


def test_C05_requeue_all_in_dead_letter_order():
    env = Env(with_default=False)
    a, b, c = _three_dead(env)

    requeued = env.queue.requeue_all_dead_letters()

    assert [job.id for job in requeued] == [b.id, c.id, a.id]
    assert all(env.get(job).status is JobStatus.PENDING for job in (a, b, c))
    assert env.queue.dead_letters() == []


def test_C05_requeue_all_filtered_by_type():
    env = Env(with_default=False)
    a, b, c = _three_dead(env)

    requeued = env.queue.requeue_all_dead_letters("fast")

    assert [job.id for job in requeued] == [b.id, c.id]
    assert dead_ids(env) == [a.id]
    assert env.get(a).status is JobStatus.DEAD_LETTERED
    assert env.get(b).status is JobStatus.PENDING


def test_C05_nothing_to_requeue_returns_empty_list():
    env = Env(default_policy=RetryPolicy(max_attempts=1))
    assert env.queue.requeue_all_dead_letters() == []
    env.always_fail("mail")
    env.queue.enqueue("mail")
    env.worker.run_once()
    assert env.queue.requeue_all_dead_letters("other") == []
    assert len(env.queue.dead_letters()) == 1
    assert env.metric("jobs.requeued") == 0


# --------------------------------------------------------------------------- C06


def test_C06_retry_after_replaces_policy_delay():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=5.0))
    env.handler("bill", lambda job: RetryLaterError("billing busy", retry_after=17))
    job = env.queue.enqueue("bill")
    env.clock.advance(3)

    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.RETRY_SCHEDULED
    assert current.run_at == START + timedelta(seconds=3 + 17)
    assert current.error == "RetryLaterError: billing busy"


def test_C06_retry_after_capped_by_max_delay():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=60.0))
    env.handler("bill", lambda job: RetryLaterError("slow down", retry_after=3600))
    job = env.queue.enqueue("bill")
    env.worker.run_once()
    assert env.get(job).run_at == START + timedelta(seconds=60)


def test_C06_retry_after_has_no_jitter_and_keeps_rng_untouched():
    policy = RetryPolicy(max_attempts=3, base_delay=1.0, max_delay=100.0, jitter=0.5)
    env = Env(default_policy=policy, rng=ExplodingRng())
    env.handler("bill", lambda job: RetryLaterError("busy", retry_after=40))
    job = env.queue.enqueue("bill")
    env.worker.run_once()
    assert env.get(job).run_at == START + timedelta(seconds=40)


def test_C06_error_class_contract():
    exc = RetryLaterError("busy", retry_after=2.5)
    assert isinstance(exc, JobqError)
    assert exc.retry_after == 2.5
    assert str(exc) == "busy"
    assert RetryLaterError(retry_after=0).retry_after == 0
    with pytest.raises(ConfigError):
        RetryLaterError("bad", retry_after=-1)


# --------------------------------------------------------------------------- C07


def test_C07_retry_later_counts_attempts_and_exhausts():
    env = Env(default_policy=RetryPolicy(max_attempts=2, base_delay=1.0))
    env.handler("bill", lambda job: RetryLaterError(f"busy {job.attempts}", retry_after=7))
    job = env.queue.enqueue("bill")
    env.worker.run_once()
    env.clock.advance(7)
    env.worker.run_once()

    current = env.get(job)
    assert current.status is JobStatus.DEAD_LETTERED
    assert current.attempts == 2
    (entry,) = env.queue.dead_letters()
    assert entry.reason is DeadLetterReason.EXHAUSTED
    assert entry.error == "RetryLaterError: busy 2"
    assert env.metric("jobs.retried") == 1
    assert env.metric("jobs.dead_lettered") == 1
    assert env.metric("jobs.failed") == 0


def test_C07_retry_later_without_policy_fails_as_before():
    env = Env(with_default=False)
    env.handler("bill", lambda job: RetryLaterError("busy", retry_after=7))
    job = env.queue.enqueue("bill")
    env.worker.run_once()
    current = env.get(job)
    assert current.status is JobStatus.FAILED
    assert current.error == "RetryLaterError: busy"
    assert env.metric("jobs.failed") == 1
    assert env.queue.dead_letters() == []


def test_C07_retry_later_then_success():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=1.0))
    env.handler("bill", lambda job: RetryLaterError("busy", retry_after=7) if job.attempts == 1 else "paid")
    job = env.queue.enqueue("bill")
    env.worker.run_once()
    assert env.metric("jobs.retried") == 1
    env.clock.advance(6.5)
    assert env.worker.run_once() is None
    env.clock.advance(0.5)
    env.worker.run_once()
    current = env.get(job)
    assert current.status is JobStatus.SUCCEEDED
    assert current.result == "paid"
    assert current.error is None
    assert current.attempts == 2


# --------------------------------------------------------------------------- C08


def test_C08_bulk_requeue_resets_like_single_requeue():
    env = Env(with_default=False)
    a, b, c = _three_dead(env)
    enqueued = env.metric("jobs.enqueued")
    total = len(env.queue.list_jobs())
    env.clock.advance(30)

    env.queue.requeue_all_dead_letters()

    for job in (a, b, c):
        current = env.get(job)
        assert current.attempts == 0
        assert current.error is None
        assert current.run_at == env.clock.now()
    assert env.metric("jobs.requeued") == 3
    assert env.metric("jobs.enqueued") == enqueued
    assert len(env.queue.list_jobs()) == total


def test_C08_bulk_requeued_job_gets_full_attempts():
    env = Env(with_default=False)
    a, b, c = _three_dead(env)
    env.queue.requeue_all_dead_letters("slow")

    env.worker.run_once()
    current = env.get(a)
    assert current.status is JobStatus.RETRY_SCHEDULED
    assert current.attempts == 1


def test_C08_bulk_requeue_includes_non_retryable_entries():
    env = Env(default_policy=RetryPolicy(max_attempts=3, base_delay=1.0, non_retryable=(ValueError,)))
    env.handler("parse", lambda job: BadInput("bad row"))
    env.queue.set_retry_policy("mail", RetryPolicy(max_attempts=1))
    env.always_fail("mail")
    p = env.queue.enqueue("parse")
    m = env.queue.enqueue("mail")
    env.worker.run_pending()
    assert dead_ids(env) == [p.id, m.id]

    assert [job.id for job in env.queue.requeue_all_dead_letters()] == [p.id, m.id]

    env.worker.run_once()  # parse снова падает с неповторяемой ошибкой
    assert dead_ids(env) == [p.id]
    assert env.queue.dead_letters()[0].attempts == 1


# --------------------------------------------------------------------------- C09


def test_C09_non_retryable_dead_letter_metrics():
    env = Env(default_policy=RetryPolicy(max_attempts=5, non_retryable=(ValueError,)))
    env.handler("parse", lambda job: BadInput("bad"))
    env.queue.enqueue("parse")
    env.worker.run_once()
    assert env.metric("jobs.dead_lettered") == 1
    assert env.metric("jobs.failed") == 0
    assert env.metric("jobs.retried") == 0


def test_C09_non_retryable_dead_letter_does_not_touch_rng():
    policy = RetryPolicy(max_attempts=5, jitter=0.5, non_retryable=(ValueError,))
    env = Env(default_policy=policy, rng=ExplodingRng())
    env.handler("parse", lambda job: BadInput("bad"))
    job = env.queue.enqueue("parse")
    env.worker.run_once()
    assert env.get(job).status is JobStatus.DEAD_LETTERED


def test_C09_missing_handler_and_missing_policy_still_fail():
    env = Env(with_default=False)
    env.queue.set_retry_policy("ghost", RetryPolicy(max_attempts=5))
    ghost = env.queue.enqueue("ghost")  # обработчика нет
    env.handler("plain", lambda job: PermanentJobError("nope"))  # политики нет
    plain = env.queue.enqueue("plain")

    env.worker.run_pending()

    assert env.get(ghost).status is JobStatus.FAILED
    assert env.get(ghost).error.startswith("UnknownJobTypeError:")
    assert env.get(plain).status is JobStatus.FAILED
    assert env.queue.dead_letters() == []
    assert env.metric("jobs.failed") == 2


def test_C09_report_counts_non_retryable_as_dead_letter():
    env = Env(default_policy=RetryPolicy(max_attempts=5, non_retryable=(ValueError,)))
    env.handler("parse", lambda job: BadInput("bad"))
    env.queue.enqueue("parse")
    env.queue.enqueue("parse")
    env.worker.run_pending()

    report = render_report(env.queue)

    assert status_line(report, "В dead-letter").split()[-1] == "2"
    assert status_line(report, "Ошибка").split()[-1] == "0"
    assert env.queue.stats()["dead_lettered"] == 2


# --------------------------------------------------------------------------- C10


def test_C10_existing_signatures_unchanged():
    assert list(inspect.signature(JobQueue.requeue_dead_letter).parameters)[:2] == ["self", "job_id"]
    assert list(inspect.signature(JobQueue.purge_finished).parameters)[:2] == ["self", "older_than"]
    params = inspect.signature(RetryPolicy.delay_for).parameters
    assert list(params)[:3] == ["self", "attempt", "rng"]
    worker_params = inspect.signature(Worker).parameters
    assert list(worker_params)[:2] == ["queue", "registry"]
    assert worker_params["rng"].kind is inspect.Parameter.KEYWORD_ONLY


def test_C10_old_calls_still_work():
    clock = ManualClock(START)
    queue = JobQueue(clock=clock, default_retry_policy=RetryPolicy(max_attempts=1))
    registry = HandlerRegistry()
    registry.register("mail", lambda job: 1 / 0)
    job = queue.enqueue("mail", {"to": "ops"}, delay=0)
    assert Worker(queue, registry).run_pending(max_jobs=5) == 1
    assert queue.requeue_dead_letter(job.id).status is JobStatus.PENDING
    assert RetryPolicy(max_attempts=3, base_delay=2.0).delay_for(2) == pytest.approx(4.0)
    assert queue.purge_finished() == 0
