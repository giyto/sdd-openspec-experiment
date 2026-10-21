## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, поэтому дежурные каждое утро вручную перезапускают десятки заданий, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Нужны настраиваемые повторы с экспоненциальной задержкой и отдельное место (dead-letter) для заданий, которые так и не выполнились, откуда их можно осознанно вернуть в работу (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py` с `RetryPolicy` (frozen dataclass): `delay_for`, `is_retryable`, валидация параметров через `ConfigError`.
- Новое исключение `PermanentJobError` — обработчик бросает его, когда повтор точно не поможет.
- Новые статусы `RETRY_SCHEDULED` («Ожидает повтора») и `DEAD_LETTERED` («В dead-letter»), оба нетерминальные; новая модель `DeadLetterEntry`.
- `JobQueue`: параметр `default_retry_policy` (keyword-only), `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`, переходы `mark_retry_scheduled` / `mark_dead_lettered`.
- `Worker`: keyword-only `rng`; после ошибки обработчика выбирает `FAILED`, `RETRY_SCHEDULED` или `DEAD_LETTERED` по политике, действующей в момент ошибки.
- Выборка готовых заданий в хранилище учитывает `RETRY_SCHEDULED` с наступившим `run_at`.
- Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Экспорт новых имён из `jobq/__init__.py`, обновление README.
- Без политики поведение не меняется; сигнатуры существующих методов не меняются. `jobq/dashboard.py` и `jobq/cli.py` не изменяются: отчёт получает новые строки и подписи автоматически, т.к. перебирает `JobStatus`.

## Capabilities

### New Capabilities
- `retry-policy`: параметры и валидация `RetryPolicy`, расчёт задержки, классификация ошибок, назначение политики очереди и типу задания.
- `job-retry-handling`: поведение воркера при ошибке обработчика, новые статусы и переходы, rng, счётчики, подписи в отчёте.
- `dead-letter-queue`: список dead-letter, возврат в работу, взаимодействие с отменой и `purge_finished`.

### Modified Capabilities

Нет: в `openspec/specs/` пока нет спецификаций, существующее поведение без политики сохраняется.

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/store.py`, `jobq/queue.py`, `jobq/worker.py`, `jobq/metrics.py`, `jobq/__init__.py`, `README.md`; новые тесты.
- Не затрагивается: `jobq/dashboard.py`, `jobq/cli.py`, существующие тесты.
- Зависимости: новых нет (стандартная библиотека).
- Риск для чужого кода: `stats()` и отчёт теперь содержат две новые строки статусов.
