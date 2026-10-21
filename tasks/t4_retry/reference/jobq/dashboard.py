"""Текстовый отчёт о состоянии очереди для дежурных."""

from __future__ import annotations

from .models import JobStatus
from .queue import JobQueue

LABEL_WIDTH = 18


def render_report(queue: JobQueue, *, recent_errors: int = 5) -> str:
    """Сформировать многострочный отчёт: статусы, последние ошибки, счётчики."""
    now = queue.clock.now()
    stats = queue.stats()

    lines = [f"Очередь заданий на {now:%Y-%m-%d %H:%M:%S} UTC", "", "Статусы:"]
    for status in JobStatus:
        lines.append(f"  {status.label:<{LABEL_WIDTH}} {stats.get(status.value, 0):>5}")
    lines.append(f"  {'Всего':<{LABEL_WIDTH}} {sum(stats.values()):>5}")

    failed = queue.list_jobs(JobStatus.FAILED)
    if failed and recent_errors > 0:
        lines.append("")
        lines.append("Последние ошибки:")
        for job in failed[-recent_errors:]:
            lines.append(f"  {job.id} [{job.job_type}] попыток={job.attempts}: {job.error}")

    snapshot = queue.metrics.snapshot()
    if snapshot:
        lines.append("")
        lines.append("Счётчики:")
        for name, value in snapshot.items():
            lines.append(f"  {name:<{LABEL_WIDTH + 4}} {value:>7}")

    return "\n".join(lines)


def failure_rate(queue: JobQueue) -> float:
    """Доля упавших среди завершившихся (успешно или с ошибкой) заданий."""
    stats = queue.stats()
    failed = stats.get(JobStatus.FAILED.value, 0)
    done = failed + stats.get(JobStatus.SUCCEEDED.value, 0)
    return failed / done if done else 0.0
