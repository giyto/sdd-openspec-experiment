## Purpose

Повторы упавших заданий по настраиваемой политике с экспоненциальной задержкой: временные
ошибки обработчика не требуют ручного перезапуска, а повторы без политики не происходят.

## ADDED Requirements

### Requirement: Retry policy parameters are validated
`RetryPolicy` SHALL be an immutable value with fields `max_attempts` (default 3), `base_delay`
(default 1.0), `factor` (default 2.0), `max_delay` (default 60.0), `jitter` (default 0.0) and
`non_retryable` (default empty). Construction with an invalid value SHALL raise `ConfigError`.
Invalid values are: `max_attempts < 1`; `base_delay < 0`; `factor < 1`; `max_delay < base_delay`;
`jitter` outside `[0, 1]`; any non-finite numeric field; any element of `non_retryable` that is not
an exception class. A list passed as `non_retryable` SHALL be stored as a tuple.

#### Scenario: Non-exception class in non_retryable
- **WHEN** a `RetryPolicy` is created with `non_retryable=("ValueError",)`
- **THEN** construction raises `ConfigError`

#### Scenario: List is stored as tuple
- **WHEN** a `RetryPolicy` is created with `non_retryable=[ValueError]`
- **THEN** `policy.non_retryable` is `(ValueError,)`

### Requirement: Retry delay is exponential, capped and bounded
`delay_for(attempt)` SHALL return the delay before the next attempt after attempt number `attempt`
failed (numbering starts at 1). The uncapped delay is `base_delay * factor ** (attempt - 1)`, and it
SHALL be limited to `max_delay`. `attempt < 1` SHALL raise `ConfigError`. The method SHALL NOT raise
`OverflowError` or any other arithmetic error for any `attempt >= 1` (for example 10000), including
when `base_delay` is 0. The result SHALL always be within `[0, max_delay]`.

#### Scenario: Exponential growth until the cap
- **WHEN** a policy has `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`
- **THEN** `delay_for(1)` is 1.0, `delay_for(2)` is 2.0, `delay_for(3)` is 4.0, and `delay_for(10)` is 60.0

#### Scenario: Very large attempt number
- **WHEN** `delay_for(5000)` is called on a policy with `factor=2.0`
- **THEN** it returns `max_delay` and raises nothing

#### Scenario: Zero base delay
- **WHEN** a policy has `base_delay=0.0` and `delay_for(50)` is called
- **THEN** it returns 0.0

#### Scenario: Invalid attempt
- **WHEN** `delay_for(0)` is called
- **THEN** it raises `ConfigError`

### Requirement: Jitter is applied to the capped delay and never exceeds max_delay
When `jitter > 0`, `delay_for` SHALL multiply the already capped delay by `rng.uniform(1 - jitter, 1 + jitter)`,
using exactly one draw from `rng` per computed delay. The product SHALL then be limited to `max_delay`.
When `jitter == 0`, `rng` SHALL NOT be used. When `rng` is not given and jitter is positive, the
method SHALL still return a value in `[0, max_delay]`.

#### Scenario: Jitter with a predictable generator
- **WHEN** a policy has `base_delay=10.0`, `jitter=0.5`, and `rng` returns a uniform value of 1.2 for the single call
- **THEN** `delay_for(1, rng)` returns 12.0 and the generator was drawn exactly once

#### Scenario: Jitter does not break the cap
- **WHEN** the capped delay equals `max_delay` and the drawn factor is greater than 1
- **THEN** `delay_for` returns `max_delay`

#### Scenario: No jitter, no randomness
- **WHEN** a policy has `jitter=0.0` and `delay_for(2, rng)` is called
- **THEN** `rng` is not drawn from

### Requirement: Retryable decision
`RetryPolicy.is_retryable(exc)` SHALL return `False` when `exc` is an instance of any class in
`non_retryable` (including subclasses) and when `exc` is a `PermanentJobError` (including subclasses).
It SHALL return `True` otherwise. The decision does not depend on the number of attempts made.

#### Scenario: Subclass of a non-retryable class
- **WHEN** `non_retryable=(ValueError,)` and the handler raises a subclass of `ValueError`
- **THEN** `is_retryable` returns `False`

#### Scenario: Permanent error
- **WHEN** the handler raises `PermanentJobError("card declined")` and the policy has an empty `non_retryable`
- **THEN** `is_retryable` returns `False`

### Requirement: Retry policy assignment and resolution
A `JobQueue` SHALL accept an optional `default_retry_policy` keyword-only argument. `set_retry_policy(job_type, policy)`
SHALL set the policy for a job type; passing `None` SHALL remove the type policy. `retry_policy_for(job_type)`
SHALL return the policy in effect for that type: the type policy if one is set, otherwise the queue default,
otherwise `None`. A type policy SHALL replace the default completely and SHALL NOT be merged field by field with it.
An empty or non-string `job_type`, or a `policy` that is neither `RetryPolicy` nor `None`, SHALL raise `ConfigError`.
The policy used is the one in effect at the moment the handler fails, not the one that was in effect at enqueue time.

#### Scenario: Type policy replaces the default
- **WHEN** the queue default has `max_attempts=5` and `non_retryable=(KeyError,)`, and the type policy is `RetryPolicy(max_attempts=2)`
- **THEN** `retry_policy_for(job_type)` returns the type policy, whose `non_retryable` is empty

#### Scenario: Removing a type policy falls back to the default
- **WHEN** a type policy is set and then `set_retry_policy(job_type, None)` is called on a queue with a default policy
- **THEN** `retry_policy_for(job_type)` returns the default policy

#### Scenario: No policy anywhere
- **WHEN** neither a default nor a type policy is set
- **THEN** `retry_policy_for(job_type)` returns `None`

### Requirement: Worker decides the outcome of a failed attempt
When a handler raises an exception, the worker SHALL use the policy in effect for the job type and make one of
three decisions, in this order:
1. If there is no policy, or the exception is not retryable, the job SHALL move to `FAILED`.
2. Otherwise, if `job.attempts` has reached `max_attempts`, the job SHALL move to `DEAD_LETTERED`.
3. Otherwise, the job SHALL move to `RETRY_SCHEDULED` with `run_at` equal to the current time plus `delay_for(job.attempts, rng)`.

`job.attempts` counts the attempt that just failed. The delay SHALL be computed only in case 3, so `rng` is drawn only
when a retry is actually scheduled. `job.error` SHALL always hold the text of the most recent error in the
`"ИмяКласса: сообщение"` format. An unknown job type (no handler) SHALL move the job to `FAILED` with no retry
and no delay computation, even if a policy is set. With `max_attempts=1` a retryable error SHALL move the job to
`DEAD_LETTERED`, not to `FAILED`.

#### Scenario: Retryable error with attempts left
- **WHEN** a job of a type with `max_attempts=3`, `base_delay=1.0`, `jitter=0.0` fails on its first attempt at time T
- **THEN** the job status is `RETRY_SCHEDULED`, `job.run_at` is T + 1 second, `job.error` is the failure text, and `jobs.retried` is incremented by 1

#### Scenario: Non-retryable error on the last attempt
- **WHEN** a job with `max_attempts=1` raises `PermanentJobError` on its only attempt
- **THEN** the job status is `FAILED`, no dead-letter entry is created, and `jobs.failed` is incremented by 1

#### Scenario: Attempts exhausted
- **WHEN** a job with `max_attempts=2` fails on its second attempt with a retryable error
- **THEN** the job status is `DEAD_LETTERED` and `jobs.dead_lettered` is incremented by 1

#### Scenario: No policy keeps current behavior
- **WHEN** a job fails and neither a default nor a type policy is set
- **THEN** the job status is `FAILED` and no retry counter changes

#### Scenario: Unknown job type
- **WHEN** a job of a type with no registered handler is run and a policy is set for that type
- **THEN** the job status is `FAILED` and `rng` is not drawn from

### Requirement: Retry scheduling and execution
A job in `RETRY_SCHEDULED` SHALL be picked up by the worker when its `run_at` is not later than the current time,
in the same order as pending jobs. Starting such a job SHALL increase `attempts` by one, as for any run.
A job in `RETRY_SCHEDULED` SHALL be cancellable with `cancel`, with the same result as a pending job
(`CANCELLED`, `finished_at` set, `jobs.cancelled` incremented). `RETRY_SCHEDULED` is not a terminal status.

#### Scenario: Retry is picked up when due
- **WHEN** a job is `RETRY_SCHEDULED` with `run_at` = T + 1 and the clock is advanced to T + 1
- **THEN** `worker.run_once()` runs that job again and `job.attempts` increases by 1

#### Scenario: Cancelling a waiting retry
- **WHEN** `cancel` is called on a `RETRY_SCHEDULED` job
- **THEN** the job status is `CANCELLED` and the job is never run again

### Requirement: Retry and dead-letter statuses and counters
`JobStatus` SHALL contain `RETRY_SCHEDULED` (value `"retry_scheduled"`, label «Ожидает повтора», not terminal)
and `DEAD_LETTERED` (value `"dead_lettered"`, label «В dead-letter»). The counters `jobs.retried`,
`jobs.dead_lettered` and `jobs.requeued` SHALL follow the same rule as existing counters: each is incremented
exactly once at the moment of the corresponding transition or action.

#### Scenario: Labels in the report
- **WHEN** the operator report is rendered for a queue that contains retry-scheduled and dead-lettered jobs
- **THEN** the status rows are labelled «Ожидает повтора» and «В dead-letter» with their counts
