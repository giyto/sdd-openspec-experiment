## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий. Нужны настраиваемые повторы с экспоненциальной задержкой и отдельное место (dead-letter) для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль с неизменяемой `RetryPolicy` (max_attempts, base_delay, factor, max_delay, jitter, non_retryable), расчётом задержки `delay_for` и проверкой `is_retryable`; некорректные параметры — `ConfigError`.
- Новая ошибка `PermanentJobError`: обработчик бросает её, когда повтор заведомо не поможет.
- Новые статусы `RETRY_SCHEDULED` («Ожидает повтора») и `DEAD_LETTERED` («В dead-letter»), модель `DeadLetterEntry`.
- `JobQueue`: политика по умолчанию (`default_retry_policy`) и по типу задания (`set_retry_policy`, `retry_policy_for`), `dead_letters()`, `requeue_dead_letter()`.
- `Worker`: при падении обработчика выбирает между `FAILED`, `RETRY_SCHEDULED` и `DEAD_LETTERED`; необязательный `rng` для jitter.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Не меняются `jobq/dashboard.py` и `jobq/cli.py` (чужие). Подписи новых статусов попадают в отчёт через `JobStatus.label`. Сигнатуры существующих методов не меняются, без политики поведение прежнее. Не **BREAKING**, но в `stats()` и отчёте появляются два новых статуса.

## Capabilities

### New Capabilities
- `retry-policy`: параметры и валидация `RetryPolicy`, расчёт задержки, классификация ошибок, назначение политики очереди и типу задания.
- `job-retry`: что делает воркер при падении обработчика, новые статусы и переходы, срок запуска повтора, счётчики и подписи в отчёте.
- `dead-letter`: журнал заданий, исчерпавших попытки, и их осознанный возврат в работу.

### Modified Capabilities

(нет: в `openspec/specs/` спецификаций ещё нет, существующее поведение без политики не меняется)

## Impact

- Код: новый `jobq/retry.py`; правки `errors.py`, `models.py`, `metrics.py`, `store.py` (выборка готовых), `queue.py`, `worker.py`, `__init__.py`, README.
- Публичный API: только добавления, новые параметры keyword-only. Зависимости не добавляются.
- Побочный эффект: `stats()` содержит ключи `retry_scheduled` и `dead_lettered`; отчёт дежурных получает две новые строки без правок `dashboard.py`.
