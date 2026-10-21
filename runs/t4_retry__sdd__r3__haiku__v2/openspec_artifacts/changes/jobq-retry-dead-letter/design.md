## Context

`jobq` is a synchronous, in-memory queue. `Worker.run_once` marks a job `RUNNING`, calls the handler and
on any `Exception` calls `JobQueue.mark_failed`. Status changes go through `JobQueue._transition` with the
table `_TRANSITIONS`. Time comes only from the injected clock, errors derive from `JobqError`, and
the package uses only the standard library. See `proposal.md` for motivation and `specs/` for the
required behavior. Existing public signatures stay unchanged and new parameters are keyword-only.

## Goals / Non-Goals

**Goals**
- Keep all policy logic in a pure value object (`RetryPolicy`) that is easy to test with a seeded `random.Random`.
- Keep every status change inside `JobQueue`, so `_TRANSITIONS` stays the single source of truth.
- Keep behavior identical when no policy is configured.

**Non-Goals**
- No persistence, no background scheduler, no change to `dashboard.py` or `cli.py`.
- No per-job policy (policy is per queue default and per job type only).
- No automatic dead-letter expiry or purge.

## Decisions

### D1. `RetryPolicy` lives in `jobq/retry.py` as a frozen dataclass with validation in `__post_init__`
Invalid values raise `ConfigError`, which is the project convention for configuration errors (not `ValueError`,
which the package does not expose). `non_retryable` is normalized to a tuple with `object.__setattr__`, because
the dataclass is frozen. Non-finite floats (`nan`, `inf`) are rejected too, since they would break the
`[0, max_delay]` bound. This is a decision not stated in the ticket.
*Alternative:* accept any iterable and store as-is. Rejected: a frozen policy must be hashable and immutable.

### D2. Exponential delay without overflow
`delay_for` computes the raw delay as `base_delay * factor ** (attempt - 1)`. If `base_delay == 0`, it returns `0.0`
without touching the power. Otherwise the power is computed inside `try/except OverflowError`, and an overflow is
treated as `inf`, so the result is `max_delay`. `min(raw, max_delay)` then gives the capped value. This is O(1) for any
`attempt`, with no loop, and handles `attempt=10000` and `factor=1.0` directly.
*Alternative:* loop with early exit. Rejected: with factor close to 1 the loop can run for millions of iterations.

### D3. Jitter after cap, then clamp
`delay = min(capped * rng.uniform(1 - jitter, 1 + jitter), max_delay)`. The clamp keeps `max_delay` a hard ceiling as
the ticket requires. `rng` is drawn only when `jitter > 0`, exactly once per call. When `rng is None`, the module-level
`random.Random()` instance is used. It is never seeded, so jitter is non-deterministic only in that case.

### D4. Policy resolution at failure time
`JobQueue` keeps `_default_policy` and `_type_policies: dict[str, RetryPolicy]`. `set_retry_policy(t, None)` removes the
key. `retry_policy_for(t)` returns `_type_policies.get(t, _default_policy)`. The type policy replaces the default
completely (no field merge, per the ticket). The worker asks the queue at the time of failure, so changes made while a
job waits in `RETRY_SCHEDULED` apply to its next failure.

### D5. The worker decides, the queue applies
`Worker` contains the decision (FAILED / DEAD_LETTERED / RETRY_SCHEDULED) and computes the delay with its `rng`.
It then calls one of three queue methods, all of which go through `_transition`:
- `mark_failed(job_id, error)`: existing, unchanged.
- `mark_retry_scheduled(job_id, error, delay)`: `RUNNING -> RETRY_SCHEDULED`, sets `error`, `run_at = clock.now() + delay`,
  increments `jobs.retried`.
- `mark_dead_lettered(job_id, error)`: `RUNNING -> DEAD_LETTERED`, sets `error`, `finished_at`, adds `DeadLetterEntry`,
  increments `jobs.dead_lettered`.
The worker never edits `job.status` directly. The queue never calls `rng`, which keeps the draw count under the
worker's control and makes it trivially true that a draw happens only when a retry is scheduled.
*Alternative:* put the decision in `JobQueue.fail(job_id, exc, rng)`. Rejected: it would make the queue depend on the handler
exception model and on randomness.

### D6. State machine
`_TRANSITIONS` becomes:
- `PENDING` → `RUNNING`, `CANCELLED`
- `RETRY_SCHEDULED` → `RUNNING`, `CANCELLED`
- `RUNNING` → `SUCCEEDED`, `FAILED`, `RETRY_SCHEDULED`, `DEAD_LETTERED`
- `DEAD_LETTERED` → `PENDING` (the only caller is `requeue_dead_letter`, which goes through `_transition` like every other change)

`mark_running` already accepts only the `RUNNING` target, so it works from `RETRY_SCHEDULED` with no change in logic.
`JobStatus.is_terminal` = `{SUCCEEDED, FAILED, CANCELLED, DEAD_LETTERED}`. `RETRY_SCHEDULED` is not terminal.

### D7. Dead-letter storage and purge
`JobQueue._dead_letters: dict[str, DeadLetterEntry]` keyed by job id. Python dicts keep insertion order, so
`dead_letters()` returns `list(self._dead_letters.values())`. `DeadLetterEntry` is a frozen dataclass in `models.py`,
as the ticket specifies. `purge_finished` skips jobs in `DEAD_LETTERED` explicitly, because `is_terminal` is true for them.
Excluding them in the loop is simpler than making the status non-terminal, which would change what the worker and
reports consider finished.

### D8. Requeue
`requeue_dead_letter(job_id)`:
1. Pop the entry (if the id is not in the dead-letter dict: `JobNotFoundError` when the store does not know the id, otherwise
   `InvalidTransitionError(job_id, job.status.value, PENDING)`).
2. `_transition(job, PENDING)`.
3. Set `run_at = now`, `error = None`, `finished_at = None`, `attempts = 0`. The pre-requeue attempt count is logged with
   `logger.info`, and it is also available in the entry that was removed.
4. Increment `jobs.requeued`.
The UPD in the ticket overrides the earlier "keep attempts" line, so attempts are reset. The ticket says attempts are kept
for visibility, but it also says a requeued job must not go to dead-letter after its first error. Resetting is the only
option that satisfies both, and visibility is preserved through the log.

### D9. Dispatch in `Worker.run_once`
```
except Exception as exc:
    policy = self._queue.retry_policy_for(job.job_type)
    error = format_error(exc)
    if policy is None or not policy.is_retryable(exc):
        return self._queue.mark_failed(job.id, error)
    if job.attempts >= policy.max_attempts:
        return self._queue.mark_dead_lettered(job.id, error)
    delay = policy.delay_for(job.attempts, self._rng)
    return self._queue.mark_retry_scheduled(job.id, error, delay)
```
The `UnknownJobTypeError` branch stays as it is: `FAILED`, no policy lookup.

### D10. Public surface
- `jobq/__init__.py` exports `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry`.
- `jobq/metrics.py` adds `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`.
- `JobQueue.__init__` gets `default_retry_policy` after `*`. `Worker.__init__` gets `rng` after `*`.

## Risks / Trade-offs

- **[Dead-letter entries are not visible in the operator report]** The dashboard "Последние ошибки" block lists only `FAILED`,
  so dead-lettered jobs are not shown there. Status rows do show them, because `dashboard.py` iterates `JobStatus`.
  → Documented in the proposal as a follow-up for the dashboard owners. No change in this change.
- **[`is_terminal` is true for `DEAD_LETTERED` but it is not "finished"]** Code that treats `is_terminal` as "safe to delete"
  would delete dead letters. → Only `purge_finished` uses it in the package, and D7 excludes the status there. A test covers it.
- **[Attempts reset on requeue]** Operators lose the total count in the job object. → Count is logged at requeue, and the entry
  keeps the count at dead-letter time until requeue.
- **[Policy changes apply at failure time]** A job waiting for a retry can be retried under a new policy. This is what the ticket asks
  for; it is recorded as the rule, not as a surprise.
- **[Non-deterministic default rng]** Only when `jitter > 0` and no `rng` is passed. Tests pass an `rng`.

## Migration Plan

No data migration: the store is in memory. Deploy as a library release. Rollback is a revert: no persisted state uses the new statuses.
Existing callers see no change while no policy is configured, because the decision in D9 then always selects `FAILED`.

## Open Questions

None that change specs or tasks. The dashboard follow-up is outside this change.
