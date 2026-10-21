## MODIFIED Requirements

### Requirement: Jitter is applied to the capped delay and never exceeds max_delay
When `jitter > 0`, `delay_for` SHALL multiply the already capped delay by `rng.uniform(1 - jitter, 1)`,
using exactly one draw from `rng` per computed delay. Jitter SHALL only shorten the delay: the result
SHALL NOT be later than the capped delay. The product SHALL then be limited to `max_delay`.
When `jitter == 0`, `rng` SHALL NOT be used. When `rng` is not given and jitter is positive, the
method SHALL still return a value in `[0, max_delay]`.

#### Scenario: Jitter with a predictable generator
- **WHEN** a policy has `base_delay=10.0`, `jitter=0.5`, and `rng.uniform(0.5, 1.0)` returns 0.8 for the single call
- **THEN** `delay_for(1, rng)` returns 8.0 and the generator was drawn exactly once

#### Scenario: Jitter does not break the cap
- **WHEN** a policy has `base_delay=1.0`, `max_delay=10.0`, `jitter=0.5`, the capped delay equals `max_delay` at `delay_for(20, rng)`, and `rng.uniform(0.5, 1.0)` returns 0.8
- **THEN** `delay_for` returns 8.0 and the generator was drawn exactly once

#### Scenario: Jitter never delays the retry
- **WHEN** a policy has `base_delay=10.0`, `jitter=0.5`, and `delay_for(1, rng)` is called with any `rng`
- **THEN** the returned value is within `[5.0, 10.0]`

#### Scenario: No jitter, no randomness
- **WHEN** a policy has `jitter=0.0` and `delay_for(2, rng)` is called
- **THEN** `rng` is not drawn from

### Requirement: Worker decides the outcome of a failed attempt
When a handler raises an exception, the worker SHALL use the policy in effect for the job type and make one of
the following decisions, in this order:
1. If there is no policy, the job SHALL move to `FAILED` with no dead-letter entry.
2. Otherwise, if the exception is not retryable (`PermanentJobError`, or an instance of a `non_retryable` class),
   the job SHALL move to `DEAD_LETTERED` with reason `non_retryable`, regardless of the number of attempts made.
3. Otherwise, if `job.attempts` has reached `max_attempts`, the job SHALL move to `DEAD_LETTERED` with reason `exhausted`.
4. Otherwise, the job SHALL move to `RETRY_SCHEDULED`. If the exception is a `RetryLaterError`, `run_at` SHALL be the
   current time plus the delay given by `RetryLaterError.retry_after` capped to `max_delay`, and `rng` SHALL NOT be drawn
   from. Otherwise `run_at` SHALL be the current time plus `delay_for(job.attempts, rng)`.

`job.attempts` counts the attempt that just failed. The delay SHALL be computed only in case 4, so `rng` is drawn only
when a retry is actually scheduled by the policy delay. `job.error` SHALL always hold the text of the most recent error in
the `"ИмяКласса: сообщение"` format. An unknown job type (no handler) SHALL move the job to `FAILED` with no retry
and no delay computation, even if a policy is set. With `max_attempts=1` a retryable error SHALL move the job to
`DEAD_LETTERED` with reason `exhausted`, not to `FAILED`.

#### Scenario: Retryable error with attempts left
- **WHEN** a job of a type with `max_attempts=3`, `base_delay=1.0`, `jitter=0.0` fails on its first attempt at time T
- **THEN** the job status is `RETRY_SCHEDULED`, `job.run_at` is T + 1 second, `job.error` is the failure text, and `jobs.retried` is incremented by 1

#### Scenario: Non-retryable error on the last attempt
- **WHEN** a job with `max_attempts=1` and a policy raises `PermanentJobError` on its only attempt
- **THEN** the job status is `DEAD_LETTERED`, its dead-letter entry has reason `non_retryable`, and `jobs.dead_lettered` is incremented by 1

#### Scenario: Non-retryable error with attempts left
- **WHEN** a job with `max_attempts=5` and `non_retryable=(KeyError,)` raises `KeyError` on its first attempt
- **THEN** the job status is `DEAD_LETTERED` with reason `non_retryable`, no retry is scheduled, and `rng` is not drawn from

#### Scenario: Attempts exhausted
- **WHEN** a job with `max_attempts=2` fails on its second attempt with a retryable error
- **THEN** the job status is `DEAD_LETTERED` with reason `exhausted` and `jobs.dead_lettered` is incremented by 1

#### Scenario: No policy keeps current behavior
- **WHEN** a job fails and neither a default nor a type policy is set
- **THEN** the job status is `FAILED` and no retry counter changes

#### Scenario: Unknown job type
- **WHEN** a job of a type with no registered handler is run and a policy is set for that type
- **THEN** the job status is `FAILED` and `rng` is not drawn from

## ADDED Requirements

### Requirement: Handler can set the next attempt time with RetryLaterError
`RetryLaterError(message="", *, retry_after: float)` SHALL be an error of the `JobqError` hierarchy that a handler raises
when an external service has named the time of the next attempt. Creating it with `retry_after < 0` SHALL raise
`ConfigError`. For a job whose policy is set and which raises `RetryLaterError` with attempts left, the worker SHALL
schedule the retry `min(retry_after, max_delay)` seconds after the current time. Jitter SHALL NOT be applied to this
delay, and `rng` SHALL NOT be drawn from. `RetryLaterError` is a temporary error: the retryable check and the attempt
limit apply to it as to any other error. Without a policy it moves the job to `FAILED`, as any error does.

#### Scenario: Retry-After larger than max_delay
- **WHEN** a policy has `base_delay=1.0`, `max_delay=60.0`, `jitter=0.5`, and the handler raises `RetryLaterError(retry_after=3600)` on the first attempt at time T
- **THEN** the job status is `RETRY_SCHEDULED`, `job.run_at` is T + 60 seconds, and `rng` was not drawn from

#### Scenario: Retry-After within the limit
- **WHEN** the handler raises `RetryLaterError(retry_after=12.5)` on the first attempt at time T with `max_delay=60.0`
- **THEN** the job status is `RETRY_SCHEDULED` and `job.run_at` is T + 12.5 seconds

#### Scenario: Retry-After on the last attempt
- **WHEN** a job with `max_attempts=2` raises `RetryLaterError(retry_after=5)` on its second attempt
- **THEN** the job status is `DEAD_LETTERED` with reason `exhausted`

#### Scenario: Negative Retry-After
- **WHEN** `RetryLaterError(retry_after=-1)` is constructed
- **THEN** it raises `ConfigError`

#### Scenario: No policy
- **WHEN** the handler raises `RetryLaterError(retry_after=5)` and no policy is set for the job type
- **THEN** the job status is `FAILED`
