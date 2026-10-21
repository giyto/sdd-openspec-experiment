## 1. Models, errors and metrics

- [x] 1.1 Add `PermanentJobError(JobqError)` to `jobq/errors.py` and verify `issubclass(PermanentJobError, JobqError)` in a unit test
- [x] 1.2 Add `RETRY_SCHEDULED` ("retry_scheduled", «Ожидает повтора», non-terminal) and `DEAD_LETTERED` ("dead_lettered", «В dead-letter», terminal) to `JobStatus` in `jobq/models.py` and verify labels and `is_terminal` with a test
- [x] 1.3 Add the frozen `DeadLetterEntry` dataclass (`job_id`, `job_type`, `attempts`, `error`, `dead_lettered_at`) to `jobq/models.py` and verify it is immutable with a test
- [x] 1.4 Add `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` constants to `jobq/metrics.py` and verify their values are `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`

## 2. RetryPolicy

- [x] 2.1 Create `jobq/retry.py` with the frozen `RetryPolicy` dataclass, defaults from the spec, and `__post_init__` validation that raises `ConfigError` (including non-finite floats and non-class `non_retryable` elements); verify with parametrized tests for each invalid case and for list-to-tuple normalization
- [x] 2.2 Implement `delay_for(attempt, rng=None)` per design D2 and D3 (O(1) power with `OverflowError` handling, cap, jitter via one `rng.uniform` call only when `jitter > 0`, final clamp to `max_delay`); verify the example values from the spec, `attempt=5000` with no exception, `base_delay=0`, and that a predictable `rng` is drawn exactly once
- [x] 2.3 Implement `is_retryable(exc)` (False for `non_retryable` subclasses and `PermanentJobError`); verify with a subclass test and a `PermanentJobError` test

## 3. Queue: policies, transitions and dead-letter

- [x] 3.1 Add keyword-only `default_retry_policy` to `JobQueue.__init__`, the `_type_policies` dict, `set_retry_policy` (ConfigError on bad input, `None` removes) and `retry_policy_for` (type policy, else default, else `None`); verify replacement without field merge and fallback after removal
- [x] 3.2 Extend `_TRANSITIONS` per design D6 and allow `mark_running` from `RETRY_SCHEDULED`; verify with tests that illegal transitions (e.g. `SUCCEEDED → RUNNING`, `DEAD_LETTERED → RUNNING`) still raise `InvalidTransitionError`
- [x] 3.3 Add `mark_retry_scheduled(job_id, error, delay)` (sets `error`, `run_at = now + delay`, increments `jobs.retried`) and `mark_dead_lettered(job_id, error)` (sets `error` and `finished_at`, stores a `DeadLetterEntry`, increments `jobs.dead_lettered`); verify field values and counters
- [x] 3.4 Update `InMemoryJobStore.due` (in `jobq/store.py`) to include `RETRY_SCHEDULED` jobs with `run_at <= now`; verify that a retry is returned by `next_due` only after its `run_at`
- [x] 3.5 Implement `dead_letters()` (insertion order, new list) and `requeue_dead_letter(job_id)` per design D8 (pop entry, `PENDING`, `run_at = now`, `error = None`, `finished_at = None`, `attempts = 0`, log previous attempts, increment `jobs.requeued`, `JobNotFoundError` / `InvalidTransitionError` for bad ids); verify the spec scenarios including the retry-after-requeue case
- [x] 3.6 Make `purge_finished` skip `DEAD_LETTERED` jobs explicitly; verify that dead letters survive `purge_finished(older_than=0)` and remain in `dead_letters()`
- [x] 3.7 Verify `cancel` works for `RETRY_SCHEDULED` and is refused for `DEAD_LETTERED` (test both)

## 4. Worker

- [x] 4.1 Add keyword-only `rng: random.Random | None = None` to `Worker.__init__` and store it; verify the default constructor still works
- [x] 4.2 Implement the failure dispatch from design D9 in `Worker.run_once` (no policy or non-retryable → `mark_failed`; attempts exhausted → `mark_dead_lettered`; otherwise `delay_for(job.attempts, rng)` → `mark_retry_scheduled`); keep the `UnknownJobTypeError` branch unchanged; verify each branch with a scenario test, including `max_attempts=1` going to `DEAD_LETTERED`
- [x] 4.3 Verify that `rng` is never drawn for `FAILED`, `DEAD_LETTERED`, or unknown-type outcomes, using a recording `random.Random` subclass in a test
- [x] 4.4 Verify that `job.error` always holds the latest error across several failed attempts (test with a handler that raises a different error each time)

## 5. Public API and documentation

- [x] 5.1 Export `RetryPolicy`, `PermanentJobError`, and `DeadLetterEntry` from `jobq/__init__.py` and update `__all__`; verify with an import test
- [x] 5.2 Update the `Job` docstring in `jobq/models.py` (`attempts` is reset by requeue; `error` holds the last error) and the module docstring of `jobq/queue.py` (new transitions); verify by reading the diff
- [x] 5.3 Add a short README section for retry policies and the dead-letter queue (setting a policy, `dead_letters()`, `requeue_dead_letter()`); verify the example runs in a test or by hand

## 6. Verification

- [x] 6.1 Run `python -m pytest -q` and verify that all existing tests pass unchanged and all new tests pass
- [x] 6.2 Confirm with `git diff --stat` that `jobq/dashboard.py`, `jobq/cli.py`, and existing test files are unchanged, and that no new dependency was added
- [x] 6.3 Run `openspec validate jobq-retry-dead-letter` and verify it reports no errors
