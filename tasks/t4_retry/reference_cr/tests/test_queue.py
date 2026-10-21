from datetime import timedelta

import pytest

from jobq import InvalidJobError, InvalidTransitionError, JobNotFoundError, JobStatus

from .conftest import START


def test_enqueue_defaults(queue):
    job = queue.enqueue("echo", {"x": 1})
    assert job.status is JobStatus.PENDING
    assert job.run_at == START
    assert job.created_at == START
    assert job.attempts == 0
    assert job.payload == {"x": 1}
    assert queue.metrics.get("jobs.enqueued") == 1


def test_enqueue_with_delay_and_run_at(queue):
    delayed = queue.enqueue("echo", delay=90)
    exact = queue.enqueue("echo", run_at=START + timedelta(hours=1))
    assert delayed.run_at == START + timedelta(seconds=90)
    assert exact.run_at == START + timedelta(hours=1)


def test_enqueue_ids_are_unique_and_ordered(queue):
    ids = [queue.enqueue("echo").id for _ in range(3)]
    assert ids == sorted(ids)
    assert len(set(ids)) == 3


@pytest.mark.parametrize(
    "kwargs",
    [
        {"job_type": ""},
        {"job_type": "echo", "delay": -1},
        {"job_type": "echo", "delay": 1, "run_at": START},
        {"job_type": "echo", "run_at": START.replace(tzinfo=None)},
    ],
)
def test_enqueue_rejects_bad_arguments(queue, kwargs):
    with pytest.raises(InvalidJobError):
        queue.enqueue(**kwargs)


def test_payload_is_copied(queue):
    payload = {"a": 1}
    job = queue.enqueue("echo", payload)
    payload["a"] = 2
    assert job.payload == {"a": 1}


def test_next_due_orders_by_run_at_then_enqueue_order(queue, clock):
    late = queue.enqueue("echo", delay=10)
    first = queue.enqueue("echo", delay=5)
    second = queue.enqueue("echo", delay=5)
    assert queue.next_due() is None
    clock.advance(5)
    assert queue.next_due() is first
    queue.cancel(first.id)
    assert queue.next_due() is second
    clock.advance(5)
    queue.cancel(second.id)
    assert queue.next_due() is late


def test_cancel_pending_job(queue, clock):
    job = queue.enqueue("echo")
    clock.advance(3)
    queue.cancel(job.id)
    assert job.status is JobStatus.CANCELLED
    assert job.finished_at == START + timedelta(seconds=3)
    assert queue.metrics.get("jobs.cancelled") == 1
    assert queue.next_due() is None


def test_cancel_finished_job_is_rejected(queue):
    job = queue.enqueue("echo")
    queue.cancel(job.id)
    with pytest.raises(InvalidTransitionError):
        queue.cancel(job.id)


def test_get_unknown_job(queue):
    with pytest.raises(JobNotFoundError):
        queue.get("job-999999")


def test_stats_lists_every_status(queue):
    queue.enqueue("echo")
    cancelled = queue.enqueue("echo")
    queue.cancel(cancelled.id)
    stats = queue.stats()
    assert set(stats) == {status.value for status in JobStatus}
    assert stats["pending"] == 1
    assert stats["cancelled"] == 1
    assert stats["failed"] == 0


def test_list_jobs_by_status(queue):
    a = queue.enqueue("echo")
    b = queue.enqueue("echo")
    queue.cancel(b.id)
    assert queue.list_jobs() == [a, b]
    assert queue.list_jobs(JobStatus.PENDING) == [a]
    assert queue.list_jobs(JobStatus.CANCELLED) == [b]


def test_purge_finished_respects_age(queue, clock):
    old = queue.enqueue("echo")
    queue.cancel(old.id)
    clock.advance(100)
    fresh = queue.enqueue("echo")
    queue.cancel(fresh.id)
    pending = queue.enqueue("echo")

    assert queue.purge_finished(older_than=50) == 1
    assert [job.id for job in queue.list_jobs()] == [fresh.id, pending.id]
    assert queue.metrics.get("jobs.purged") == 1
