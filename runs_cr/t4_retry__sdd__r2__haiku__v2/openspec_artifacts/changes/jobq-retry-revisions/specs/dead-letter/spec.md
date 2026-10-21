## MODIFIED Requirements

### Requirement: Dead-letter entries
The system SHALL keep an ordered list of dead-letter entries, one per job currently in
`DEAD_LETTERED`. Each `DeadLetterEntry` contains `job_id`, `job_type`, `attempts`, `error` (the last
error text), `dead_lettered_at`, and `reason`, a `DeadLetterReason` that is either `exhausted` (the
attempts ran out) or `non_retryable` (the error cannot be retried). `reason` is the last field and
defaults to `exhausted`. `dead_letters()` MUST return the entries in the order in which the jobs were
dead-lettered.

#### Scenario: Entries are listed in order of dead-lettering
- **WHEN** job A and then job B are dead-lettered
- **THEN** `dead_letters()` returns an entry for A followed by an entry for B

#### Scenario: Entry carries the last error and attempts
- **WHEN** a job of type `billing` fails with `"HTTPError: 503"` on its third attempt and is dead-lettered
- **THEN** its entry has `job_type="billing"`, `attempts=3`, `error="HTTPError: 503"`

#### Scenario: Entry carries the reason for dead-lettering
- **WHEN** a job is dead-lettered because its attempts ran out, and another job is dead-lettered by a non-retryable error
- **THEN** the first entry has `reason=DeadLetterReason.EXHAUSTED` and the second has `reason=DeadLetterReason.NON_RETRYABLE`

#### Scenario: Empty dead-letter queue
- **WHEN** no job has been dead-lettered
- **THEN** `dead_letters()` returns an empty list

### Requirement: Dead-letter queue is a part of the public API
`JobQueue.dead_letters()`, `JobQueue.requeue_dead_letter(job_id)`, and `JobQueue.requeue_all_dead_letters(job_type)`
SHALL be available with no change to the signatures of existing public methods. The `DeadLetterEntry`
is a frozen dataclass. `DeadLetterReason` is exported from the package.

#### Scenario: Existing calls keep working
- **WHEN** code written before this change calls `enqueue`, `cancel`, `purge_finished`, `dead_letters`, `requeue_dead_letter`, and `Worker(queue, registry)`
- **THEN** the calls succeed with the same results as before, except that dead letters older than the purge age are now removed by `purge_finished`

## REMOVED Requirements

### Requirement: Dead-lettered jobs are not run and not purged
**Reason**: JOBQ-237 — after a month of operation, 40 thousand dead-letter entries have accumulated, so
dead letters must age out like other finished jobs.
**Migration**: Dead-lettered jobs that are not wanted must be left for `purge_finished` once they are
older than the purge age, counted from the moment they were dead-lettered. Jobs that must be kept should
be requeued before the purge runs.

## ADDED Requirements

### Requirement: Dead-lettered jobs are not run and age out
A job in `DEAD_LETTERED` MUST NOT be picked up by the worker. A dead-lettered job MUST NOT be cancelled
with `cancel`; the only way out is `requeue_dead_letter` or `requeue_all_dead_letters`. `purge_finished`
MUST remove dead-lettered jobs by the same age rule as other finished jobs, counting from `dead_lettered_at`
of the entry. When it removes a job, it MUST also remove its dead-letter entry from `dead_letters()`.

#### Scenario: Dead letters younger than the purge age are kept
- **WHEN** a job was dead-lettered 10 seconds ago and `purge_finished(older_than=60)` is called
- **THEN** the job is still returned by `get` and `dead_letters()` still contains its entry

#### Scenario: Dead letters older than the purge age are removed
- **WHEN** a job was dead-lettered 120 seconds ago and `purge_finished(older_than=60)` is called
- **THEN** the method returns a count that includes the job, `get` raises `JobNotFoundError`, and `dead_letters()` no longer contains its entry

#### Scenario: Age is counted from dead-lettering, not from the last failure
- **WHEN** a job fails with `ValueError` at time T and is dead-lettered at time T+30, and `purge_finished(older_than=60)` is called at T+70
- **THEN** the job is kept, because it has been in dead-letter for 40 seconds

#### Scenario: Cancel is refused for a dead letter
- **WHEN** `cancel(job_id)` is called for a dead-lettered job
- **THEN** the system raises `InvalidTransitionError`

#### Scenario: Worker skips dead letters
- **WHEN** the worker runs and the only job is dead-lettered
- **THEN** no handler is called and `run_once` returns `None`

### Requirement: Requeue all dead letters
`JobQueue.requeue_all_dead_letters(job_type: str | None = None)` SHALL requeue every dead-letter entry, or
only the entries whose `job_type` equals the given value. Each job is requeued exactly as by
`requeue_dead_letter(job_id)`. The method returns the requeued jobs in the order of `dead_letters()`. When
there is nothing to requeue, it returns an empty list. An empty string as `job_type` MUST be rejected with
`ConfigError`.

#### Scenario: Requeue everything
- **WHEN** dead-letter contains jobs A (type `billing`) and B (type `email`), in that order, and `requeue_all_dead_letters()` is called
- **THEN** the result is `[A, B]`, both jobs are `PENDING`, and `dead_letters()` is empty

#### Scenario: Requeue only one job type
- **WHEN** dead-letter contains jobs A (type `billing`) and B (type `email`) and `requeue_all_dead_letters("billing")` is called
- **THEN** the result is `[A]`, A is `PENDING`, and B is still `DEAD_LETTERED` with an entry in `dead_letters()`

#### Scenario: Each job is requeued like requeue_dead_letter
- **WHEN** a dead-lettered job with `attempts=3` is requeued by `requeue_all_dead_letters()`
- **THEN** it keeps its `id`, its `attempts` is `0`, its `error` is `None`, and a log record states that it was requeued after 3 attempts

#### Scenario: Nothing to requeue
- **WHEN** dead-letter is empty, or contains no jobs of the given type, and `requeue_all_dead_letters("email")` is called
- **THEN** the result is an empty list

#### Scenario: Empty job type is refused
- **WHEN** `requeue_all_dead_letters("")` is called
- **THEN** the system raises `ConfigError`
