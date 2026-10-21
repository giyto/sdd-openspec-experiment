## Why

Любое исключение в обработчике сразу переводит задание в `FAILED`, а почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий (JOBQ-212). Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились.

## What Changes

- Новый модуль `jobq/retry.py` с `RetryPolicy` (frozen dataclass: `max_attempts`, `base_delay`, `factor`, `max_delay`, `jitter`, `non_retryable`) и методами `delay_for(attempt, rng=None)` и `is_retryable(exc)`.
- `jobq/errors.py`: новое исключение `PermanentJobError(JobqError)` — обработчик бросает его, когда повтор точно не поможет.
- `jobq/models.py`: статусы `JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`, подпись «Ожидает повтора») и `JobStatus.DEAD_LETTERED` (`"dead_lettered"`, подпись «В dead-letter»); dataclass `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`.
- `jobq/queue.py`: `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy=None)`, `set_retry_policy(job_type, policy)`, `retry_policy_for(job_type)`, `dead_letters()`, `requeue_dead_letter(job_id)`.
- `jobq/worker.py`: `Worker(queue, registry, *, name="worker", rng=None)`; при падении обработчика выбирает `FAILED` / `RETRY_SCHEDULED` / `DEAD_LETTERED`.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Поведение без политики не меняется; сигнатуры существующих публичных методов не меняются, новые параметры только keyword-only. `jobq/dashboard.py` и `jobq/cli.py` не изменяются (новые подписи попадают в отчёт через `JobStatus.label`).

## Capabilities

### New Capabilities
- `job-retry-policy`: политика повторов (параметры, валидация, расчёт задержки, классификация ошибок), её назначение очереди/типу задания и выбор исхода упавшего задания воркером.
- `dead-letter-queue`: статусы `RETRY_SCHEDULED`/`DEAD_LETTERED`, dead-letter очередь, возврат в работу, отмена, взаимодействие с `purge_finished`, счётчики и подписи отчёта.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций)

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/queue.py`, `jobq/worker.py`, `jobq/metrics.py`, `jobq/store.py` (выборка готовых заданий должна учитывать `RETRY_SCHEDULED`), `jobq/__init__.py` (экспорт), `README.md`.
- Не затрагиваются: `jobq/dashboard.py`, `jobq/cli.py`, существующие тесты. Новые зависимости не добавляются (только стандартная библиотека).
- `JobQueue.stats()` и отчёт дежурных получают две новые строки статусов (следствие перечисления `JobStatus`).
