# job-retry Specification

## Purpose
Настраиваемая политика повторов для упавших заданий: сколько попыток сделать, как растёт задержка
между ними и какие ошибки повторять нельзя. Политика задаётся для очереди по умолчанию и для типа задания.

## Requirements

### Requirement: Retry policy parameters are validated
The system SHALL treat invalid retry policy parameters as configuration errors (`ConfigError`) at
construction time. A policy with `max_attempts < 1`, `base_delay < 0`, `factor < 1`,
`max_delay < base_delay`, `jitter` outside `[0, 1]`, a non-finite numeric value, or a
`non_retryable` element that is not an exception class MUST be rejected. `non_retryable` MUST be stored
as a tuple regardless of the type passed in.

#### Scenario: Invalid max_attempts is rejected
- **WHEN** a `RetryPolicy` is created with `max_attempts=0`
- **THEN** the system raises `ConfigError`

#### Scenario: Non-exception in non_retryable is rejected
- **WHEN** a `RetryPolicy` is created with `non_retryable=(ValueError, "timeout")`
- **THEN** the system raises `ConfigError`

#### Scenario: List is accepted for non_retryable and stored as tuple
- **WHEN** a `RetryPolicy` is created with `non_retryable=[ValueError]`
- **THEN** the policy's `non_retryable` attribute is `(ValueError,)`

### Requirement: Retry delay grows exponentially and is capped
The system SHALL compute `delay_for(attempt)` as `base_delay * factor ** (attempt - 1)` capped at
`max_delay`, where `attempt` is the 1-based number of the failed attempt. The result MUST be
within `[0, max_delay]` for every valid `attempt`, including very large values and `base_delay=0`.
`attempt < 1` MUST raise `ConfigError`.

#### Scenario: Delay grows by factor until the cap
- **WHEN** a policy has `base_delay=1.0`, `factor=2.0`, `max_delay=10.0`, `jitter=0.0`
- **THEN** `delay_for(1)` is `1.0`, `delay_for(2)` is `2.0`, `delay_for(4)` is `8.0`, and `delay_for(5)` is `10.0`

#### Scenario: Huge attempt number does not overflow
- **WHEN** `delay_for(10000)` is called on a policy with `factor=2.0` and `max_delay=60.0`
- **THEN** the system returns `60.0` without raising an error

#### Scenario: Zero base delay
- **WHEN** a policy has `base_delay=0.0` and `jitter=0.0`
- **THEN** `delay_for(n)` is `0.0` for every `n >= 1`

#### Scenario: Attempt below one is rejected
- **WHEN** `delay_for(0)` is called
- **THEN** the system raises `ConfigError`

### Requirement: Jitter randomizes delay within the cap
When `jitter > 0`, the system SHALL multiply the capped delay by a value drawn once with
`rng.uniform(1 - jitter, 1 + jitter)`, and then cap the result at `max_delay` again so that jitter never
exceeds the hard ceiling. When `jitter == 0`, the random generator MUST NOT be used. If `jitter > 0` and
no `rng` is passed, the system uses a default random generator.

#### Scenario: Jitter is applied to the capped delay
- **WHEN** a policy has `base_delay=10.0`, `factor=1.0`, `max_delay=10.0`, `jitter=0.5`
- **AND** `rng.uniform` returns `1.5` for the call
- **THEN** `delay_for(1, rng)` returns `10.0`, not `15.0`

#### Scenario: Jitter below one scales the delay down
- **WHEN** a policy has `base_delay=10.0`, `factor=1.0`, `max_delay=60.0`, `jitter=0.5`
- **AND** `rng.uniform` returns `0.5` for the call
- **THEN** `delay_for(1, rng)` returns `5.0`

#### Scenario: Zero jitter does not consume randomness
- **WHEN** `delay_for(3, rng)` is called on a policy with `jitter=0.0`
- **THEN** the random generator is not called

### Requirement: Retryability of an exception
The system SHALL report an exception as not retryable when it is an instance of any class in
`non_retryable` (subclasses included), and SHALL always report `PermanentJobError` as not retryable.
All other exceptions are retryable.

#### Scenario: Subclass of a non-retryable class is not retried
- **WHEN** a policy has `non_retryable=(ValueError,)` and the exception is a subclass of `ValueError`
- **THEN** `is_retryable` returns `False`

#### Scenario: PermanentJobError is never retried
- **WHEN** a policy with empty `non_retryable` is asked about `PermanentJobError("gateway rejected")`
- **THEN** `is_retryable` returns `False`

#### Scenario: Other exceptions are retried
- **WHEN** the exception is `TimeoutError` and the policy has `non_retryable=(ValueError,)`
- **THEN** `is_retryable` returns `True`

### Requirement: Retry policy assignment
The system SHALL accept an optional default retry policy for the queue, given as keyword-only argument
`default_retry_policy`. The system SHALL allow setting a retry policy per job type with
`set_retry_policy(job_type, policy)`; passing `None` removes the type policy. The effective policy for a
job type is the type policy if one is set, otherwise the queue default, otherwise none. A type policy
replaces the default as a whole and fields are not merged. `retry_policy_for(job_type)` returns the
effective policy. The policy in force is the one at the moment of failure, not at enqueue time.

#### Scenario: Type policy replaces the queue default entirely
- **WHEN** the queue default policy has `non_retryable=(ValueError,)` and the type policy is `RetryPolicy()`
- **THEN** `retry_policy_for(job_type)` returns the type policy, and its `non_retryable` is `()`

#### Scenario: Removing a type policy falls back to the default
- **WHEN** a type policy is set and then `set_retry_policy(job_type, None)` is called
- **THEN** `retry_policy_for(job_type)` returns the queue default policy

#### Scenario: No policy anywhere
- **WHEN** neither a queue default nor a type policy is set
- **THEN** `retry_policy_for(job_type)` returns `None`

#### Scenario: Policy changed after enqueue applies to the failure
- **WHEN** a job is enqueued, then a retry policy is set for its type, and then the job fails
- **THEN** the failure is handled according to the policy set at the moment of failure

### Requirement: Worker decides the outcome of a failed attempt
When a handler raises an exception, the worker SHALL record the error text in `job.error` in the
`"ИмяКласса: сообщение"` format and choose the next status as follows:

1. If no retry policy is in effect, or the exception is not retryable, the job becomes `FAILED`.
2. Otherwise, if `job.attempts >= policy.max_attempts`, the job becomes `DEAD_LETTERED`.
3. Otherwise, the job becomes `RETRY_SCHEDULED` with `run_at` equal to the current time plus
   `policy.delay_for(job.attempts, rng)`.

The random generator MUST be consulted only when a retry is actually scheduled. An unknown job type
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
- **THEN** the job status is `DEAD_LETTERED`

#### Scenario: max_attempts of one means no retries
- **WHEN** a policy has `max_attempts=1` and a retryable error occurs on the first attempt
- **THEN** the job status is `DEAD_LETTERED`, not `FAILED`

#### Scenario: Non-retryable error fails immediately even on the last attempt
- **WHEN** the exception is not retryable and `job.attempts` equals `max_attempts`
- **THEN** the job status is `FAILED` and the job does not appear among dead letters

#### Scenario: PermanentJobError fails the job
- **WHEN** a handler raises `PermanentJobError` on the first attempt of a job with a retry policy
- **THEN** the job status is `FAILED`

#### Scenario: Unknown job type fails without retry
- **WHEN** a job's type has no registered handler and the queue has a retry policy for it
- **THEN** the job status is `FAILED`

#### Scenario: No policy keeps the current behavior
- **WHEN** a handler raises and neither a default nor a type policy is set
- **THEN** the job status is `FAILED`, exactly as before this change

#### Scenario: Delay is computed only when a retry is scheduled
- **WHEN** a job fails with a non-retryable error or reaches `DEAD_LETTERED`
- **THEN** the random generator is not consulted for that failure

#### Scenario: Last error is kept across attempts
- **WHEN** a job fails with `TimeoutError` on attempt 1 and with `ValueError` on attempt 2
- **THEN** `job.error` contains the text of the `ValueError` failure

### Requirement: Retry-related counters
The system SHALL increment `jobs.retried` when a job enters `RETRY_SCHEDULED`, `jobs.dead_lettered`
when a job enters `DEAD_LETTERED`, and `jobs.requeued` when a dead-lettered job is requeued. These
counters follow the same rule as existing ones: each increments exactly once per transition.
`jobs.failed` continues to count only transitions to `FAILED`.

#### Scenario: Counters on a retry cycle
- **WHEN** a job with `max_attempts=2` fails twice and is then requeued
- **THEN** `jobs.retried` is 1, `jobs.dead_lettered` is 1, `jobs.requeued` is 1, and `jobs.failed` is 0

### Requirement: Retry-scheduled jobs can be cancelled
A job in `RETRY_SCHEDULED` SHALL be cancellable with `cancel(job_id)` exactly like a pending job, and
its status becomes `CANCELLED`.

#### Scenario: Cancel a job waiting for retry
- **WHEN** `cancel(job_id)` is called for a job in `RETRY_SCHEDULED`
- **THEN** the job status is `CANCELLED`

### Requirement: Status labels for reports
The statuses `RETRY_SCHEDULED` and `DEAD_LETTERED` SHALL have the labels "Ожидает повтора" and
"В dead-letter" respectively, with the values `"retry_scheduled"` and `"dead_lettered"`.

#### Scenario: New status labels
- **WHEN** the label of `JobStatus.RETRY_SCHEDULED` and `JobStatus.DEAD_LETTERED` is read
- **THEN** they are "Ожидает повтора" and "В dead-letter"
