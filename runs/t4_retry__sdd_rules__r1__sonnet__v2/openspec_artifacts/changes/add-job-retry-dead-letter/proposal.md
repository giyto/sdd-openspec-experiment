## Why

Любое исключение в обработчике сразу переводит задание в `FAILED`, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий. Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py` с `RetryPolicy` (frozen dataclass: `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`; методы `delay_for(attempt, rng=None) -> float` и `is_retryable(exc) -> bool`). Некорректные параметры дают `ConfigError`.
- `jobq/errors.py`: `PermanentJobError(JobqError)`. Обработчик бросает её, когда повтор точно не поможет.
- `jobq/models.py`: `JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`), `JobStatus.DEAD_LETTERED` (`"dead_lettered"`), подписи «Ожидает повтора» и «В dead-letter», `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`.
- `jobq/queue.py`: `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy=None)`, `set_retry_policy(job_type, policy)`, `retry_policy_for(job_type)`, `dead_letters()`, `requeue_dead_letter(job_id) -> Job`.
- `jobq/worker.py`: `Worker(queue, registry, *, name="worker", rng=None)`; при падении обработчика выбирает `FAILED`, `DEAD_LETTERED` или `RETRY_SCHEDULED`.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Задание в `RETRY_SCHEDULED` берётся воркером по `run_at` и может быть отменено; из `DEAD_LETTERED` выход один — `requeue_dead_letter`. `purge_finished` dead-letter не удаляет.
- Без политики (ни по умолчанию, ни для типа) поведение прежнее. Сигнатуры существующих методов не меняются, новые параметры только keyword-only.
- Вне границ: `jobq/dashboard.py` и `jobq/cli.py` не меняются (ими владеет другая команда). Подписи новых статусов попадают в отчёт через `JobStatus.label`, который отчёт уже использует.

## Capabilities

### New Capabilities
- `retry-policy`: значение `RetryPolicy` — валидация, расчёт задержки, классификация ошибок, `PermanentJobError`.
- `job-retry-handling`: выбор политики, исходы падения обработчика, повторы, dead-letter и `requeue_dead_letter`, отмена, purge, счётчики, подписи статусов.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций)

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/queue.py`, `jobq/store.py` (выборка готовых заданий включает `RETRY_SCHEDULED`), `jobq/metrics.py`, `jobq/worker.py`, `jobq/__init__.py` (экспорт), новые тесты.
- Публичный API расширяется, ломающих изменений нет. Зависимости не добавляются.
- `stats()` и отчёт дежурных получают две новые строки статусов.

## Допущения

- Допущение: `requeue_dead_letter` обнуляет `attempts` (так сказано в UPD тимлида; это отменяет раннее «attempts сохраняем» из описания).
- Допущение: `NaN` в числовых полях `RetryPolicy` считается некорректным и даёт `ConfigError`.
- Допущение: `attempts >= max_attempts` означает «попытки кончились».
