## Why

Любое исключение в обработчике сразу переводит задание в `FAILED`, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий. Нужны настраиваемые повторы с экспоненциальной задержкой и отдельное место (dead-letter) для заданий, которые так и не выполнились, откуда их можно осознанно вернуть в работу (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py`: `RetryPolicy` (число попыток, экспоненциальная задержка с потолком и джиттером, список неповторяемых исключений) с валидацией параметров как `ConfigError`.
- Новое исключение `PermanentJobError` — обработчик бросает его, когда повтор точно не поможет.
- Новые статусы `RETRY_SCHEDULED` («Ожидает повтора») и `DEAD_LETTERED` («В dead-letter»), датакласс `DeadLetterEntry`.
- `JobQueue`: параметр `default_retry_policy`, политика по типу задания (`set_retry_policy` / `retry_policy_for`), `dead_letters()`, `requeue_dead_letter()`.
- `Worker`: при падении обработчика выбирает между `FAILED`, `RETRY_SCHEDULED` и `DEAD_LETTERED`; новый keyword-only параметр `rng` для предсказуемого джиттера.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- `purge_finished` не удаляет задания в dead-letter; отмена доступна для `RETRY_SCHEDULED`, но не для `DEAD_LETTERED`.
- Без политики поведение не меняется. Существующие сигнатуры не меняются, новые параметры только keyword-only. Не breaking.

## Capabilities

### New Capabilities
- `retry-policy`: `RetryPolicy` — расчёт задержки, классификация ошибок на повторяемые и нет, валидация конфигурации.
- `job-retry`: настройка политик в очереди и поведение воркера при падении обработчика (статусы, `run_at`, `error`, счётчики, отмена, отчёт).
- `dead-letter`: список dead-letter, возврат в работу, защита от `purge_finished`.

### Modified Capabilities

Нет: в `openspec/specs/` пока нет спецификаций.

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/metrics.py`, `jobq/store.py` (выборка готовых заданий), `jobq/queue.py`, `jobq/worker.py`, `jobq/__init__.py`, `README.md`; новые тесты.
- Не трогаем `jobq/dashboard.py` и `jobq/cli.py` (другая команда). Отчёт дежурных перебирает `JobStatus` и берёт подписи из `label`, поэтому новые строки появятся без правок в нём.
- Зависимости: новых нет (только стандартная библиотека).
