## MODIFIED Requirements

### Requirement: Dead-letter entries
When a job moves to `DEAD_LETTERED`, the queue SHALL add a `DeadLetterEntry` with `job_id`, `job_type`,
`attempts` (the number of attempts made), `error` (the last error text), `dead_lettered_at` (the current
time of the queue clock) and `reason`, a `DeadLetterReason`: `EXHAUSTED` (the attempts ran out, value
`"exhausted"`) or `NON_RETRYABLE` (the error is not retryable, value `"non_retryable"`). `reason` is the last
field of the entry. A non-retryable error SHALL give `NON_RETRYABLE` even when it happens on the last attempt.
`dead_letters()` SHALL return all entries in the order they were added, as a new list.
A job that moves to `FAILED` SHALL NOT produce a dead-letter entry.

#### Scenario: Entries keep order
- **WHEN** job A is dead-lettered, then job B is dead-lettered
- **THEN** `dead_letters()` returns the entry for A followed by the entry for B

#### Scenario: Entry content
- **WHEN** a job of type `"send_email"` with `max_attempts=2` fails twice with `ConnectionError: timeout`
- **THEN** `dead_letters()` contains one entry with `job_type="send_email"`, `attempts=2`, `error="ConnectionError: timeout"`, `reason=DeadLetterReason.EXHAUSTED`

#### Scenario: Non-retryable reason
- **WHEN** a job of type `"charge"` with `max_attempts=1` raises `PermanentJobError("card declined")`
- **THEN** `dead_letters()` contains one entry with `reason=DeadLetterReason.NON_RETRYABLE` and `reason.value == "non_retryable"`

## MODIFIED Requirements

### Requirement: Dead-letter jobs leave only through requeue or purge
A `DEAD_LETTERED` job SHALL NOT be cancellable with `cancel`, SHALL NOT be picked up by the worker, and SHALL NOT be
removed by `purge_finished` unless it is older than the purge age. The job leaves the dead-letter queue in one of two ways:
`requeue_dead_letter` or `requeue_all_dead_letters` returns it to work, and `purge_finished` removes it. `purge_finished`
SHALL use the same age rule as for other finished jobs, counting from `dead_lettered_at` of the entry: a dead letter is
removed when `dead_lettered_at <= now - older_than`. A removed dead letter SHALL also be removed from `dead_letters()`,
and the job SHALL be removed from the store. `DEAD_LETTERED` SHALL be treated as a terminal status for the purposes of the
worker (it is never run).

#### Scenario: Purge removes old dead letters
- **WHEN** a job is dead-lettered at time T and `purge_finished(older_than=0)` runs at time T + 1
- **THEN** the job is removed from the store, `dead_letters()` no longer lists it, and the returned count includes it

#### Scenario: Purge keeps young dead letters
- **WHEN** a job is dead-lettered at time T and `purge_finished(older_than=100)` runs at time T + 50
- **THEN** the job remains in the store and in `dead_letters()`

#### Scenario: Purge of finished jobs alongside dead letters
- **WHEN** `purge_finished(older_than=0)` runs with one `FAILED` job, one `SUCCEEDED` job and one dead-lettered job that is older than the age
- **THEN** all three jobs are removed and `dead_letters()` is empty

#### Scenario: Cancel is refused for a dead letter
- **WHEN** `cancel` is called on a `DEAD_LETTERED` job
- **THEN** it raises `InvalidTransitionError` and the job stays in the dead-letter queue

#### Scenario: Worker does not run a dead letter
- **WHEN** the worker runs after a job was dead-lettered and the clock moves past its former `run_at`
- **THEN** the job is not run and its attempts do not change

## ADDED Requirements

### Requirement: Requeue of all dead letters
`JobQueue.requeue_all_dead_letters(job_type: str | None = None)` SHALL requeue every dead-letter entry in the order of
`dead_letters()`, each one exactly as `requeue_dead_letter` does: the same job, status `PENDING`, `run_at` equal to the
current time, `error` `None`, `attempts` 0, entry removed, `jobs.requeued` incremented by 1 per job. When `job_type` is
given, only entries of that type SHALL be requeued. It SHALL return the list of requeued jobs in the same order. When there
is nothing to requeue (the dead-letter queue is empty or has no entries of that type), it SHALL return an empty list and
change nothing. It SHALL NOT raise for that case.

#### Scenario: Requeue everything
- **WHEN** dead-letter contains job A (`"send_email"`), then job B (`"charge"`), and `requeue_all_dead_letters()` is called
- **THEN** the returned list is `[A, B]`, both are `PENDING`, `dead_letters()` is empty, and `jobs.requeued` is 2

#### Scenario: Requeue by type
- **WHEN** dead-letter contains job A (`"send_email"`) and job B (`"charge"`), and `requeue_all_dead_letters("charge")` is called
- **THEN** the returned list is `[B]`, A remains in `dead_letters()` as `DEAD_LETTERED`, and `jobs.requeued` is 1

#### Scenario: Nothing to requeue
- **WHEN** dead-letter is empty, or has no entries of the given type, and `requeue_all_dead_letters` is called
- **THEN** it returns an empty list and no counter changes
