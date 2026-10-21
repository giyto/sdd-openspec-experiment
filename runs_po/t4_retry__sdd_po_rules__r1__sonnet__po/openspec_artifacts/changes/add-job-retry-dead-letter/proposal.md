## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий. Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py` с `RetryPolicy` (frozen dataclass: `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`), методами `delay_for(attempt, rng=None)` и `is_retryable(exc)`. Некорректные параметры — `ConfigError`.
- `jobq/errors.py`: `PermanentJobError(JobqError)` — обработчик бросает её, когда повтор точно не поможет.
- `jobq/models.py`: статусы `JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`, «Ожидает повтора») и `JobStatus.DEAD_LETTERED` (`"dead_lettered"`, «В dead-letter»); dataclass `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`.
- `jobq/queue.py`: `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy=None)`, `set_retry_policy(job_type, policy)`, `retry_policy_for(job_type)`, `dead_letters()`, `requeue_dead_letter(job_id)`; новые допустимые переходы статусов.
- `jobq/worker.py`: `Worker(queue, registry, *, name="worker", rng=None)`; при падении обработчика воркер выбирает `FAILED`, `DEAD_LETTERED` или `RETRY_SCHEDULED` по политике, действующей в момент ошибки.
- `jobq/store.py`: задания в `RETRY_SCHEDULED` с наступившим `run_at` считаются готовыми к запуску наравне с `PENDING`.
- `jobq/metrics.py`: счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Экспорт новых имён из `jobq/__init__.py`, обновление README.
- Без политики (ни дефолта очереди, ни политики типа) поведение прежнее. Существующие сигнатуры не меняются, новые параметры только keyword-only. Новых зависимостей нет.
- Не затрагиваются `jobq/dashboard.py` и `jobq/cli.py` (другая команда): отчёт перебирает `JobStatus`, поэтому подписи новых статусов попадают в него автоматически.

## Capabilities

### New Capabilities

- `retry-policy`: `RetryPolicy` — валидация параметров, расчёт задержки `delay_for` (без `OverflowError`), `is_retryable`, `PermanentJobError`.
- `job-retry`: назначение политик очереди и типов, решение воркера при падении обработчика (`FAILED` / `DEAD_LETTERED` / `RETRY_SCHEDULED`), повторный запуск по `run_at`, статусы, переходы и счётчики `jobs.retried`.
- `dead-letter`: `DeadLetterEntry`, `dead_letters()`, `requeue_dead_letter()`, счётчики `jobs.dead_lettered` и `jobs.requeued`.

### Modified Capabilities

<!-- В openspec/specs/ нет существующих спецификаций. -->

## Impact

- Код: `jobq/retry.py` (новый), `errors.py`, `models.py`, `queue.py`, `worker.py`, `store.py`, `metrics.py`, `__init__.py`, `README.md`; новые тесты в `tests/`.
- Публичный API расширяется; обратная совместимость сохраняется.
- `stats()` и отчёт дежурных получают две новые строки статусов (следствие перебора `JobStatus`).
- `purge_finished` не удаляет задания в `DEAD_LETTERED`: выход из dead-letter только через `requeue_dead_letter`.

## Допущения

- `retry_policy_for(job_type)` возвращает действующую политику: политику типа, а если её нет — дефолт очереди (или `None`).
- Попытки исчерпаны, когда `job.attempts >= policy.max_attempts`.
- `requeue_dead_letter` сбрасывает `attempts` в 0: у вернувшегося задания полный набор попыток, как у нового. Запись в `dead_letters()` при этом удаляется, история попыток сохраняется только в метриках.
- `max_delay` — жёсткий потолок: джиттер его не превышает, при превышении ожидание равно ровно `max_delay`.
- Отмена (`cancel`) допустима для `RETRY_SCHEDULED`, но не для `DEAD_LETTERED`.
- Если `rng` не передан и `jitter > 0`, используется собственный экземпляр `random.Random()` воркера.
- Dead-letter хранится в `JobQueue` (в памяти процесса, как и хранилище) и не восстанавливается из заданий уже заполненного `store`.
