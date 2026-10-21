## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, и дежурные каждое утро вручную перезапускают десятки заданий, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились.

## What Changes

- Новый модуль `jobq/retry.py`: `RetryPolicy` (frozen dataclass) с `delay_for` и `is_retryable`; валидация параметров через `ConfigError`.
- Новая ошибка `PermanentJobError(JobqError)` — обработчик бросает её, когда повтор точно не поможет.
- Новые статусы `RETRY_SCHEDULED` («Ожидает повтора») и `DEAD_LETTERED` («В dead-letter»), модель `DeadLetterEntry`.
- `JobQueue`: параметр `default_retry_policy` (keyword-only), `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`, новые переходы статусов.
- `Worker`: keyword-only параметр `rng`; при падении обработчика выбирает `FAILED`, `RETRY_SCHEDULED` или `DEAD_LETTERED` по политике, действующей в момент ошибки.
- `InMemoryJobStore.due` отдаёт также `RETRY_SCHEDULED`-задания с наступившим `run_at`.
- Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Без политики (ни для типа, ни по умолчанию) поведение не меняется. Сигнатуры существующих методов не меняются, новые зависимости не добавляются, `jobq/dashboard.py` и `jobq/cli.py` не трогаем (отчёт подхватит подписи новых статусов через `JobStatus.label`).

## Capabilities

### New Capabilities
- `retry-policy`: `RetryPolicy`, расчёт задержки, классификация ошибок, `PermanentJobError`, назначение политик очереди/типа.
- `job-retry-flow`: что делает воркер при падении обработчика, новые статусы и переходы, выборка заданий к повтору, счётчики, подписи в отчёте.
- `dead-letter-queue`: `DeadLetterEntry`, `dead_letters()`, `requeue_dead_letter()`.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций, существующее поведение сохраняется)

## Impact

- Код: `jobq/retry.py` (новый), `errors.py`, `models.py`, `queue.py`, `store.py`, `worker.py`, `metrics.py`, `__init__.py` (экспорт), `README.md`.
- Публичный API расширяется только добавлениями; `JobStatus` получает два члена, поэтому `stats()` и отчёт содержат две новые строки.
- Новые тесты добавляются, существующие не меняются.
