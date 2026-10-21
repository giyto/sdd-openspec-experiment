# dead-letter Specification

## Purpose
Dead-letter очередь для заданий, которые исчерпали попытки повтора: они хранятся до осознанного
возврата в работу и не теряются при очистке завершённых заданий.

## Requirements

### Requirement: Dead-letter entries
When a job moves to `DEAD_LETTERED`, the queue SHALL add a `DeadLetterEntry` with `job_id`, `job_type`,
`attempts` (the number of attempts made), `error` (the last error text) and `dead_lettered_at` (the current
time of the queue clock). `dead_letters()` SHALL return all entries in the order they were added, as a new list.
A job that moves to `FAILED` SHALL NOT produce a dead-letter entry.

#### Scenario: Entries keep order
- **WHEN** job A is dead-lettered, then job B is dead-lettered
- **THEN** `dead_letters()` returns the entry for A followed by the entry for B

#### Scenario: Entry content
- **WHEN** a job of type `"send_email"` with `max_attempts=2` fails twice with `ConnectionError: timeout`
- **THEN** `dead_letters()` contains one entry with `job_type="send_email"`, `attempts=2`, `error="ConnectionError: timeout"`

### Requirement: Requeue returns the same job to work
`requeue_dead_letter(job_id)` SHALL move the existing job (no new job is created) to `PENDING`, set `run_at` to the
current time, set `error` to `None`, and set `attempts` to 0. It SHALL remove the job's dead-letter entry, and
increment `jobs.requeued` by 1. The number of attempts made before the requeue SHALL be written to the log.
It SHALL return the job. If the job is not in the dead-letter queue, it SHALL raise an error from the `JobqError`
hierarchy: `JobNotFoundError` for an unknown id, `InvalidTransitionError` for a job in another status.

#### Scenario: Requeued job runs again with a fresh attempt budget
- **WHEN** a dead-lettered job with `attempts=3` is requeued and `max_attempts=3`, and the worker runs it and it fails once
- **THEN** the job is `RETRY_SCHEDULED` (not dead-lettered again), because `attempts` restarted from 0

#### Scenario: Requeue clears the error and the entry
- **WHEN** a dead-lettered job is requeued
- **THEN** the job status is `PENDING`, `job.error` is `None`, `job.run_at` equals the current time, `dead_letters()` no longer contains it, and `jobs.requeued` is incremented by 1

#### Scenario: Requeue of a job not in dead-letter
- **WHEN** `requeue_dead_letter` is called for a job that is `FAILED`
- **THEN** it raises `InvalidTransitionError` and no counter changes

#### Scenario: Requeue of an unknown id
- **WHEN** `requeue_dead_letter("job-999999")` is called for an id that does not exist
- **THEN** it raises `JobNotFoundError`

### Requirement: Dead-letter jobs leave only through requeue
A `DEAD_LETTERED` job SHALL NOT be cancellable with `cancel`, SHALL NOT be picked up by the worker, and SHALL NOT be
removed by `purge_finished`, whatever its age. The only way out of the dead-letter queue is `requeue_dead_letter`.
`DEAD_LETTERED` SHALL be treated as a terminal status for the purposes of the worker (it is never run) but SHALL be
excluded from `purge_finished`.

#### Scenario: Purge leaves dead letters in place
- **WHEN** `purge_finished(older_than=0)` runs with one `FAILED` job, one `SUCCEEDED` job and one dead-lettered job
- **THEN** the `FAILED` and `SUCCEEDED` jobs are removed, the dead-lettered job remains, and `dead_letters()` still lists it

#### Scenario: Cancel is refused for a dead letter
- **WHEN** `cancel` is called on a `DEAD_LETTERED` job
- **THEN** it raises `InvalidTransitionError` and the job stays in the dead-letter queue

#### Scenario: Worker does not run a dead letter
- **WHEN** the worker runs after a job was dead-lettered and the clock moves past its former `run_at`
- **THEN** the job is not run and its attempts do not change

### Requirement: Dead-letter counters
`jobs.dead_lettered` SHALL be incremented once for each job that moves to `DEAD_LETTERED`, and `jobs.requeued` once for each
successful `requeue_dead_letter`. Existing counters keep their meaning.

#### Scenario: Counters after dead-letter and requeue
- **WHEN** one job is dead-lettered and then requeued
- **THEN** `jobs.dead_lettered` is 1, `jobs.requeued` is 1, and `jobs.failed` is 0
