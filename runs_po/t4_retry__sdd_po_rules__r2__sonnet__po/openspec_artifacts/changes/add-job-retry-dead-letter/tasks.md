## 1. Модели, ошибки, метрики

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить новым тестом `issubclass`
- [x] 1.2 Добавить `RETRY_SCHEDULED`/`DEAD_LETTERED` в `JobStatus` с подписями «Ожидает повтора»/«В dead-letter» (нетерминальные) и `DeadLetterEntry`; проверить тестом значений, подписей и `is_terminal`
- [x] 1.3 Добавить счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` в `jobq/metrics.py`; проверить, что они читаются как 0 по умолчанию

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy`, валидацией в `ConfigError` и приведением `non_retryable` к tuple; проверить тестами из сценариев валидации
- [x] 2.2 Реализовать `delay_for` без `OverflowError` (attempt 5000/10000, `base_delay=0`, `factor=1`) и jitter с одним вызовом `uniform` и жёстким потолком `max_delay` (результат с jitter не выше `max_delay`); проверить тестами с фейковым `rng`, в т.ч. `60.0` вместо `75.0`
- [x] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError`); проверить тестами

## 3. Очередь и хранилище

- [x] 3.1 Расширить `InMemoryJobStore.due()` статусом `RETRY_SCHEDULED`; проверить тестом выборки до и после `run_at`
- [x] 3.2 Добавить `default_retry_policy`, `set_retry_policy`, `retry_policy_for` (замена целиком, `None` снимает); проверить тестами
- [x] 3.3 Расширить `_TRANSITIONS`, добавить `mark_retry_scheduled`, `mark_dead_lettered`, `dead_letters`, `requeue_dead_letter` (со сбросом `attempts` в 0 и логом прежнего значения) со счётчиками; проверить тестами порядка, копии списка, ошибок requeue, сброса `attempts` и полного набора попыток после возврата, `cancel` и `purge_finished`

## 4. Воркер

- [x] 4.1 Добавить keyword-only `rng` в `Worker` и выбор `FAILED`/`RETRY_SCHEDULED`/`DEAD_LETTERED` (политика на момент ошибки, нет обработчика → `FAILED`, `rng` только при реальном повторе); проверить тестами всех сценариев `job-retries`, включая полный цикл с `ManualClock`

## 5. Экспорт, отчёт и регрессия

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`; проверить импортом
- [x] 5.2 Проверить, что `render_report` показывает новые подписи, `git diff --stat` не содержит `dashboard.py`/`cli.py`, и полный `pytest` проходит без изменения существующих тестов
- [x] 5.3 Сверить публичный API реализации с proposal и specs (имена, сигнатуры, keyword-only параметры, значения enum, имена счётчиков) и устранить расхождения
