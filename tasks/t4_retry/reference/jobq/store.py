"""Хранилище заданий в памяти."""

from __future__ import annotations

import logging
from datetime import datetime

from .errors import JobNotFoundError, JobqError
from .models import RUNNABLE, Job, JobStatus

logger = logging.getLogger(__name__)


class InMemoryJobStore:
    """Хранит задания в словаре; порядок вставки сохраняется."""

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}

    def __len__(self) -> int:
        return len(self._jobs)

    def __contains__(self, job_id: object) -> bool:
        return job_id in self._jobs

    def add(self, job: Job) -> None:
        if job.id in self._jobs:
            raise JobqError(f"job {job.id!r} already stored")
        self._jobs[job.id] = job
        logger.debug("stored job %s (%s)", job.id, job.job_type)

    def get(self, job_id: str) -> Job:
        try:
            return self._jobs[job_id]
        except KeyError:
            raise JobNotFoundError(job_id) from None

    def remove(self, job_id: str) -> Job:
        job = self.get(job_id)
        del self._jobs[job_id]
        return job

    def all(self) -> list[Job]:
        return list(self._jobs.values())

    def by_status(self, status: JobStatus) -> list[Job]:
        return [job for job in self._jobs.values() if job.status is status]

    def due(self, now: datetime) -> list[Job]:
        """Задания, готовые к запуску: PENDING/RETRY_SCHEDULED с ``run_at <= now``.

        Отсортированы по ``run_at``, при равенстве — по порядку постановки (``seq``).
        """
        ready = [
            job
            for job in self._jobs.values()
            if job.status in RUNNABLE and job.run_at <= now
        ]
        ready.sort(key=lambda job: (job.run_at, job.seq))
        return ready

    def count_by_status(self) -> dict[JobStatus, int]:
        counts = {status: 0 for status in JobStatus}
        for job in self._jobs.values():
            counts[job.status] += 1
        return counts
