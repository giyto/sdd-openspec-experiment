# dead-letter Specification

## Purpose
Очередь dead-letter для заданий, которые исчерпали попытки повтора или упали с ошибкой, которую
повторять нельзя. Задания лежат там до осознанного возврата в работу через `requeue_dead_letter`.

## Requirements

### Requirement: Dead-letter entries
The system SHALL keep an ordered list of dead-letter entries, one per job currently in
`DEAD_LETTERED`. Each `DeadLetterEntry` contains `job_id`, `job_type`, `attempts`, `error` (the last
error text), and `dead_lettered_at`. `dead_letters()` MUST return the entries in the order in which
the jobs were dead-lettered.

#### Scenario: Entries are listed in order of dead-lettering
- **WHEN** job A and then job B are dead-lettered
- **THEN** `dead_letters()` returns an entry for A followed by an entry for B

#### Scenario: Entry carries the last error and attempts
- **WHEN** a job of type `billing` fails with `"HTTPError: 503"` on its third attempt and is dead-lettered
- **THEN** its entry has `job_type="billing"`, `attempts=3`, `error="HTTPError: 503"`

#### Scenario: Empty dead-letter queue
- **WHEN** no job has been dead-lettered
- **THEN** `dead_letters()` returns an empty list

### Requirement: Dead-lettered jobs are not run and not purged
A job in `DEAD_LETTERED` MUST NOT be picked up by the worker. `purge_finished` MUST NOT remove
dead-lettered jobs, and they remain until requeued. A dead-lettered job MUST NOT be cancelled with
`cancel`; the only way out is `requeue_dead_letter`.

#### Scenario: Purge leaves dead letters alone
- **WHEN** a dead-lettered job exists and `purge_finished(older_than=0)` is called
- **THEN** the job is still returned by `get` and `dead_letters()` still contains its entry

#### Scenario: Cancel is refused for a dead letter
- **WHEN** `cancel(job_id)` is called for a dead-lettered job
- **THEN** the system raises `InvalidTransitionError`

#### Scenario: Worker skips dead letters
- **WHEN** the worker runs and the only job is dead-lettered
- **THEN** no handler is called and `run_once` returns `None`

### Requirement: Requeue a dead letter
`requeue_dead_letter(job_id)` SHALL return the same job to work without creating a new one. The job
status becomes `PENDING`, `run_at` becomes the current time, `error` is cleared, and the dead-letter
entry is removed. `attempts` is reset to zero so that the restarted job gets a full set of attempts;
the number of attempts before the requeue is written to the log. The returned job has the same `id`.

#### Scenario: Requeued job keeps its identity and gets fresh attempts
- **WHEN** job `job-000007` with `attempts=3` is dead-lettered and `requeue_dead_letter("job-000007")` is called
- **THEN** the returned job has `id="job-000007"`, status `PENDING`, `error=None`, `attempts=0`, and `run_at` equal to the current time

#### Scenario: Requeued job is removed from dead letters
- **WHEN** a job is requeued
- **THEN** `dead_letters()` no longer contains an entry for it and the worker can run it

#### Scenario: Previous attempts are logged on requeue
- **WHEN** a dead-lettered job with `attempts=3` is requeued
- **THEN** a log record states that the job was requeued after 3 attempts

#### Scenario: Requeued job that fails again is not dead-lettered at once
- **WHEN** a requeued job with `max_attempts=3` fails once
- **THEN** its status is `RETRY_SCHEDULED`, not `DEAD_LETTERED`

#### Scenario: Requeue of a job that is not dead-lettered is refused
- **WHEN** `requeue_dead_letter` is called for a job in `FAILED` status
- **THEN** the system raises `InvalidTransitionError`

#### Scenario: Requeue of an unknown job is refused
- **WHEN** `requeue_dead_letter` is called with an id that does not exist
- **THEN** the system raises `JobNotFoundError`

### Requirement: Dead-letter queue is a part of the public API
`JobQueue.dead_letters()` and `JobQueue.requeue_dead_letter(job_id)` SHALL be available with no
change to the signatures of existing public methods. The new `DeadLetterEntry` is a frozen dataclass.

#### Scenario: Existing calls keep working
- **WHEN** code written before this change calls `enqueue`, `cancel`, `purge_finished`, and `Worker(queue, registry)`
- **THEN** the calls succeed with the same results as before
