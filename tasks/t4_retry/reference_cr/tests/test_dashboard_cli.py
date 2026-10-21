from jobq import JobStatus
from jobq.cli import main
from jobq.dashboard import failure_rate, render_report


def _status_line(report: str, label: str) -> str:
    for line in report.splitlines():
        if line.strip().startswith(label):
            return line
    raise AssertionError(f"no line for {label!r} in report:\n{report}")


def test_report_shows_all_statuses(queue, registry, worker):
    registry.register("ok", lambda job: None)
    queue.enqueue("ok")
    queue.enqueue("ok", delay=60)
    worker.run_once()

    report = render_report(queue)

    for status in JobStatus:
        _status_line(report, status.label)
    assert _status_line(report, "Выполнено").split()[-1] == "1"
    assert _status_line(report, "В очереди").split()[-1] == "1"
    assert _status_line(report, "Всего").split()[-1] == "2"
    assert "jobs.succeeded" in report


def test_report_lists_recent_errors(queue, registry, worker):
    def bad(job):
        raise ValueError("bad input")

    registry.register("bad", bad)
    job = queue.enqueue("bad")
    worker.run_once()

    report = render_report(queue)
    assert "Последние ошибки:" in report
    assert f"{job.id} [bad] попыток=1: ValueError: bad input" in report


def test_failure_rate(queue, registry, worker):
    assert failure_rate(queue) == 0.0
    registry.register("ok", lambda job: None)
    registry.register("bad", lambda job: 1 / 0)
    queue.enqueue("ok")
    queue.enqueue("bad")
    queue.enqueue("ok")
    worker.run_pending()
    assert failure_rate(queue) == 1 / 3


def test_cli_demo_runs(capsys):
    assert main(["--fail-every", "2", "demo", "--jobs", "4"]) == 0
    out = capsys.readouterr().out
    assert "Статусы:" in out
    assert "flaky job #2 failed" in out


def test_cli_types(capsys):
    assert main(["types"]) == 0
    assert capsys.readouterr().out.split() == ["echo", "flaky"]
