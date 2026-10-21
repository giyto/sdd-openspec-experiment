from datetime import timedelta

from jobq import JobStatus

from .conftest import START


def test_run_once_without_jobs(worker):
    assert worker.run_once() is None


def test_successful_job(queue, registry, worker, clock):
    registry.register("double", lambda job: job.payload["n"] * 2)
    job = queue.enqueue("double", {"n": 21})
    clock.advance(1)

    done = worker.run_once()

    assert done is job
    assert job.status is JobStatus.SUCCEEDED
    assert job.result == 42
    assert job.attempts == 1
    assert job.started_at == START + timedelta(seconds=1)
    assert job.finished_at == START + timedelta(seconds=1)
    assert queue.metrics.get("jobs.started") == 1
    assert queue.metrics.get("jobs.succeeded") == 1


def test_failing_handler_marks_job_failed(queue, registry, worker):
    def boom(job):
        raise RuntimeError("disk is full")

    registry.register("boom", boom)
    job = queue.enqueue("boom")

    worker.run_once()

    assert job.status is JobStatus.FAILED
    assert job.error == "RuntimeError: disk is full"
    assert job.attempts == 1
    assert queue.metrics.get("jobs.failed") == 1
    assert worker.run_once() is None


def test_unknown_job_type_fails(queue, worker):
    job = queue.enqueue("nobody-handles-this")
    worker.run_once()
    assert job.status is JobStatus.FAILED
    assert job.error.startswith("UnknownJobTypeError:")


def test_handler_sees_running_job(queue, registry, worker):
    seen = {}

    def spy(job):
        seen["status"] = job.status
        seen["attempts"] = job.attempts

    registry.register("spy", spy)
    queue.enqueue("spy")
    worker.run_once()
    assert seen == {"status": JobStatus.RUNNING, "attempts": 1}


def test_run_pending_respects_time(queue, registry, worker, clock):
    registry.register("echo", lambda job: job.payload.get("v"))
    queue.enqueue("echo", {"v": 1})
    queue.enqueue("echo", {"v": 2}, delay=10)

    assert worker.run_pending() == 1
    assert worker.run_pending() == 0
    clock.advance(10)
    assert worker.run_pending() == 1
    assert worker.processed == 2


def test_run_pending_max_jobs(queue, registry, worker):
    registry.register("echo", lambda job: None)
    for _ in range(5):
        queue.enqueue("echo")
    assert worker.run_pending(max_jobs=2) == 2
    assert len(queue.list_jobs(JobStatus.PENDING)) == 3


def test_jobs_run_in_run_at_order(queue, registry, worker, clock):
    order = []
    registry.register("rec", lambda job: order.append(job.payload["name"]))
    queue.enqueue("rec", {"name": "c"}, delay=3)
    queue.enqueue("rec", {"name": "a"}, delay=1)
    queue.enqueue("rec", {"name": "b"}, delay=2)
    clock.advance(5)
    worker.run_pending()
    assert order == ["a", "b", "c"]
