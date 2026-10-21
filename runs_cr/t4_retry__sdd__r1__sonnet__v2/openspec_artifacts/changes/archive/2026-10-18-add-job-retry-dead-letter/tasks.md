## 1. Базовые типы

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` тестом
- [x] 1.2 В `jobq/models.py` добавить `RETRY_SCHEDULED`/`DEAD_LETTERED`, подписи «Ожидает повтора»/«В dead-letter» (не terminal) и `DeadLetterEntry`; тесты на значения, подписи и `is_terminal`
- [x] 1.3 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` и обновить docstring модуля; тест, что имена равны `jobs.retried` и т. д.

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py`: dataclass, валидация в `__post_init__`, нормализация `non_retryable` в tuple; тесты на все некорректные и граничные параметры, включая NaN
- [x] 2.2 Реализовать `delay_for` (потолок, `OverflowError` при `attempt=5000`, `base_delay=0`, `factor=1`, один `uniform` при `jitter>0`, зажим в `[0, max_delay]`, `ConfigError` при `attempt<1`); тесты со стабом `rng`
- [x] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError` всегда False); тесты по сценариям спецификации

## 3. Очередь и хранилище

- [x] 3.1 Расширить `_TRANSITIONS` и `InMemoryJobStore.due` (выбор `RETRY_SCHEDULED` с `run_at <= now`); тесты: порядок по `run_at`/`seq`, отмена в `RETRY_SCHEDULED`, отказ отмены в `DEAD_LETTERED`
- [x] 3.2 Добавить `default_retry_policy` (keyword-only), `set_retry_policy`, `retry_policy_for` с проверкой типов; тесты: замена дефолта целиком, снятие политики, `ConfigError`
- [x] 3.3 Добавить `mark_retry_scheduled`, `mark_dead_lettered`, `dead_letters` и очистку `error` в `mark_succeeded`; тесты счётчиков, порядка записей, копии списка
- [x] 3.4 Добавить `requeue_dead_letter` (attempts=0, error=None, run_at=now, запись удалена, `jobs.requeued`) и защиту `purge_finished`; тесты: успех, чужой статус, `JobNotFoundError`, purge не удаляет dead-letter

## 4. Воркер

- [x] 4.1 Добавить keyword-only `rng` в `Worker` и ветвление `FAILED`/`DEAD_LETTERED`/`RETRY_SCHEDULED` в `run_once`; тесты: все сценарии спецификации, включая `max_attempts=1`, неповторяемую ошибку на последней попытке, отсутствие обработчика и политику, смену политики после enqueue
- [x] 4.2 Тест предсказуемого `rng`: ни одного вызова при FAILED/DEAD_LETTERED и `jitter=0`, ровно один при планировании повтора
- [x] 4.3 Сквозной тест: упало → повтор → успех (`error is None`), и упало до dead-letter → requeue → успех; проверить счётчики и `render_report` с новыми подписями

## 5. Завершение

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py` и описать модуль в `README.md`; проверить импорт `from jobq import ...`
- [x] 5.2 Запустить `pytest` целиком: существующие тесты не изменены и проходят, `git diff` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты
