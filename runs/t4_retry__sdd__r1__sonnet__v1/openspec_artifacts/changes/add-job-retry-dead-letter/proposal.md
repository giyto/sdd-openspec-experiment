## Why

Сейчас любое исключение обработчика сразу переводит задание в `FAILED`, и дежурные каждое утро руками перезапускают десятки заданий, упавших из-за временных причин (таймауты почтового шлюза, 503 от биллинга). Нужны настраиваемые повторы с экспоненциальной задержкой и dead-letter очередь для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py`: frozen-датакласс `RetryPolicy` (`max_attempts`, `base_delay`, `factor`, `max_delay`, `jitter`, `non_retryable`), `delay_for`, `is_retryable`; валидация через `ConfigError`.
- Новая ошибка `PermanentJobError` (наследник `JobqError`) — повтор не поможет при любой политике.
- `JobQueue`: keyword-only `default_retry_policy`, методы `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`.
- `Worker`: keyword-only `rng`; при ошибке обработчика выбор между `FAILED`, `DEAD_LETTERED` и `RETRY_SCHEDULED`.
- Новые статусы `RETRY_SCHEDULED` и `DEAD_LETTERED`, новый `DeadLetterEntry`, новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Выборка готовых заданий учитывает `RETRY_SCHEDULED`; `cancel` работает для `RETRY_SCHEDULED`; `purge_finished` не удаляет `DEAD_LETTERED`.
- Без политики поведение не меняется (первая ошибка → `FAILED`). Нарушений обратной совместимости нет (**не BREAKING**): новые параметры только keyword-only с дефолтами.

## Capabilities

### New Capabilities
- `retry-policy`: параметры, валидация, расчёт задержки (экспонента, потолок, джиттер) и классификация повторяемости ошибок.
- `job-retries`: где задаётся политика (очередь по умолчанию / по типу) и как воркер реагирует на ошибку обработчика, включая планирование и выборку повторов.
- `dead-letter`: содержимое dead-letter очереди, `DeadLetterEntry`, возврат заданий в работу.
- `job-statuses`: новые статусы и их совместимость со `stats`, `list_jobs`, `is_terminal`, `cancel`, `purge_finished` и отчётом дежурных.

### Modified Capabilities
<!-- В openspec/specs пока нет спецификаций, изменять нечего. -->

## Impact

- Код: новый `jobq/retry.py`; правки `jobq/errors.py`, `jobq/models.py`, `jobq/metrics.py`, `jobq/store.py`, `jobq/queue.py`, `jobq/worker.py`, `jobq/__init__.py`; README.
- Не трогаем `jobq/dashboard.py` и `jobq/cli.py` (владелец — другая команда): отчёт перебирает `JobStatus` и берёт подписи из `JobStatus.label`, поэтому новые строки появятся сами.
- Существующие тесты не меняются; новые тесты — в новых файлах. Новых зависимостей нет.

## Допущения

- Точная выборка `retry_policy_for` для типа без своей политики возвращает политику очереди по умолчанию (или `None`).
- `ConfigError` дополнительно для нечисловых/нефинитных (NaN, inf) числовых параметров и нецелого `max_attempts`; один класс исключения вместо коллекции в `non_retryable` — тоже `ConfigError`.
