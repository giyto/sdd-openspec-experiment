## MODIFIED Requirements

### Requirement: Jitter randomizes delay within the cap
When `jitter > 0`, the system SHALL multiply the capped delay by a value drawn once with
`rng.uniform(1 - jitter, 1)`. Jitter MUST only shorten the delay: the result never exceeds the capped
delay and never exceeds `max_delay`. When `jitter == 0`, the random generator MUST NOT be used. If
`jitter > 0` and no `rng` is passed, the system uses a default random generator.

#### Scenario: Jitter is applied to the capped delay
- **WHEN** a policy has `base_delay=10.0`, `factor=1.0`, `max_delay=10.0`, `jitter=0.5`
- **AND** `rng.uniform` returns `0.8` for the call
- **THEN** `delay_for(1, rng)` returns `8.0`, and `rng.uniform` was called with the arguments `0.5` and `1`

#### Scenario: Jitter below one scales the delay down
- **WHEN** a policy has `base_delay=10.0`, `factor=1.0`, `max_delay=60.0`, `jitter=0.5`
- **AND** `rng.uniform` returns `0.5` for the call
- **THEN** `delay_for(1, rng)` returns `5.0`

#### Scenario: Zero jitter does not consume randomness
- **WHEN** `delay_for(3, rng)` is called on a policy with `jitter=0.0`
- **THEN** the random generator is not called

### Requirement: Worker decides the outcome of a failed attempt
When a handler raises an exception, the worker SHALL record the error text in `job.error` in the
`"ИмяКласса: сообщение"` format and choose the next status as follows:

1. If no retry policy is in effect, the job becomes `FAILED`.
2. Otherwise, if the exception is not retryable (`PermanentJobError`, or an instance of a class in
   `non_retryable`), the job becomes `DEAD_LETTERED` with reason `non_retryable`, regardless of how many
   attempts have been made.
3. Otherwise, if `job.attempts >= policy.max_attempts`, the job becomes `DEAD_LETTERED` with reason
   `exhausted`.
4. Otherwise, if the exception is `RetryLaterError`, the job becomes `RETRY_SCHEDULED` with `run_at`
   equal to the current time plus `min(exc.retry_after, policy.max_delay)` seconds. The random generator
   MUST NOT be consulted.
5. Otherwise, the job becomes `RETRY_SCHEDULED` with `run_at` equal to the current time plus
   `policy.delay_for(job.attempts, rng)`.

The random generator MUST be consulted only when a retry is scheduled by rule 5. An unknown job type
(no handler) MUST result in `FAILED` regardless of policy. The `Worker` accepts an optional keyword-only
`rng` argument.

#### Scenario: Retryable error schedules a retry
- **WHEN** a job of a type with `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `jitter=0.0` fails on its first attempt
- **THEN** the job status is `RETRY_SCHEDULED`, `job.error` is the error text, and `run_at` is the current time plus `1.0` seconds

#### Scenario: Retry becomes due and runs again
- **WHEN** the clock reaches the job's `run_at` and the worker runs
- **THEN** the job is executed again like any other pending job, and its `attempts` counter increases

#### Scenario: Last allowed attempt goes to dead letter
- **WHEN** a retryable error occurs and `job.attempts` equals `max_attempts`
- **THEN** the job status is `DEAD_LETTERED` with reason `exhausted`

#### Scenario: max_attempts of one means no retries
- **WHEN** a policy has `max_attempts=1` and a retryable error occurs on the first attempt
- **THEN** the job status is `DEAD_LETTERED`, not `FAILED`

#### Scenario: Non-retryable error fails immediately even on the last attempt
- **WHEN** the exception is not retryable and `job.attempts` equals `max_attempts`
- **THEN** the job status is `DEAD_LETTERED` with reason `non_retryable` (the reason takes priority over the attempt count), and no retry is scheduled

#### Scenario: Non-retryable error goes to dead letter without retry
- **WHEN** a policy is in effect, the exception is not retryable, and `job.attempts` is less than `max_attempts`
- **THEN** the job status is `DEAD_LETTERED` with reason `non_retryable`, and the random generator is not consulted

#### Scenario: PermanentJobError fails the job
- **WHEN** a handler raises `PermanentJobError` on the first attempt of a job whose type has a retry policy
- **THEN** the job status is `DEAD_LETTERED` with reason `non_retryable`, not `FAILED`

#### Scenario: PermanentJobError without a policy still fails the job
- **WHEN** a handler raises `PermanentJobError` and no retry policy is in effect for the job type
- **THEN** the job status is `FAILED`

#### Scenario: Unknown job type fails without retry
- **WHEN** a job's type has no registered handler and the queue has a retry policy for it
- **THEN** the job status is `FAILED`

#### Scenario: No policy keeps the current behavior
- **WHEN** a handler raises and neither a default nor a type policy is set
- **THEN** the job status is `FAILED`

#### Scenario: Delay is computed only when a retry is scheduled
- **WHEN** a job fails with a non-retryable error or reaches `DEAD_LETTERED`
- **THEN** the random generator is not consulted for that failure

#### Scenario: Last error is kept across attempts
- **WHEN** a job fails with `TimeoutError` on attempt 1 and with `ValueError` on attempt 2
- **THEN** `job.error` contains the text of the `ValueError` failure

## ADDED Requirements

### Requirement: Retry after a server-given delay
The system SHALL provide `RetryLaterError(message="", *, retry_after)`, a subclass of `JobqError`, that a
handler raises when an external service has stated when the job should be retried. `retry_after` is a
number of seconds. A `RetryLaterError` is retryable: it is a temporary error, and only its next delay
differs from the policy delay. `retry_after` MUST be a finite number not less than zero; any other value
MUST be rejected with `ConfigError` when the exception is constructed. The delay before the next attempt
is `min(retry_after, max_delay)`: `max_delay` remains the ceiling. Jitter MUST NOT be applied to this
delay.

#### Scenario: Retry-After is used as the delay
- **WHEN** a handler raises `RetryLaterError(retry_after=20.0)` on the first attempt of a job whose policy has `max_delay=60.0`
- **THEN** the job status is `RETRY_SCHEDULED` and `run_at` is the current time plus `20.0` seconds

#### Scenario: Retry-After above max_delay is capped
- **WHEN** a handler raises `RetryLaterError(retry_after=3600.0)` and the policy has `max_delay=60.0`
- **THEN** `run_at` is the current time plus `60.0` seconds

#### Scenario: Retry-After ignores jitter and does not use the random generator
- **WHEN** the policy has `jitter=0.5`, the worker's random generator is a generator that fails on any call, and a handler raises `RetryLaterError(retry_after=20.0)` on the first attempt
- **THEN** `run_at` is the current time plus `20.0` seconds and the random generator is not called

#### Scenario: Negative Retry-After is a configuration error
- **WHEN** `RetryLaterError(retry_after=-1.0)` is constructed
- **THEN** the system raises `ConfigError`

#### Scenario: Non-finite Retry-After is a configuration error
- **WHEN** `RetryLaterError(retry_after=float("nan"))` is constructed
- **THEN** the system raises `ConfigError`

#### Scenario: RetryLaterError on the last allowed attempt is exhausted
- **WHEN** a handler raises `RetryLaterError` and `job.attempts` equals `max_attempts`
- **THEN** the job status is `DEAD_LETTERED` with reason `exhausted`

#### Scenario: RetryLaterError without a policy fails the job
- **WHEN** a handler raises `RetryLaterError` and no retry policy is in effect for the job type
- **THEN** the job status is `FAILED`
