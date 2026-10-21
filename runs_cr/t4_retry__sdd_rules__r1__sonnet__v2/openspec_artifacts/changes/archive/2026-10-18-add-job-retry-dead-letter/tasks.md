## 1. Базовые типы

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` тестом
- [x] 1.2 В `jobq/models.py` добавить `RETRY_SCHEDULED`, `DEAD_LETTERED`, подписи «Ожидает повтора» и «В dead-letter», `DeadLetterEntry`; не включать новые статусы в `_TERMINAL`; тест на значения, подписи и `is_terminal`
- [x] 1.3 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` и обновить docstring; тест, что неизвестные/нулевые счётчики читаются как 0

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py`: dataclass, приведение `non_retryable` к tuple, валидация с `ConfigError` (включая NaN); тесты на каждую ошибку конфигурации и граничные допустимые значения
- [x] 2.2 Реализовать `delay_for` без `OverflowError`, с потолком до и после джиттера и ровно одним `uniform` при `jitter > 0`; тесты: attempt=5000 при max_attempts=10000, base_delay=0, потолок с джиттером, rng не вызывается при jitter=0, `attempt=0` даёт `ConfigError`
- [x] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError`); тесты по сценариям спецификации

## 3. Очередь

- [x] 3.1 В `jobq/store.py` включить `RETRY_SCHEDULED` в `due`; тест: повтор виден после `run_at` и не виден до него
- [x] 3.2 В `jobq/queue.py` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` с проверкой типов; тесты на приоритет, снятие, замену целиком
- [x] 3.3 Обновить `_TRANSITIONS`, добавить `mark_retry_scheduled`, `mark_dead_lettered`, список dead-letter, `dead_letters()`, `requeue_dead_letter` (обнуление `attempts`, `error`, `run_at=now`) и счётчики; тесты: порядок записей, тот же объект Job, ошибки `JobNotFoundError`/`InvalidTransitionError`, cancel для RETRY_SCHEDULED работает, для DEAD_LETTERED нет, purge не удаляет dead-letter

## 4. Воркер

- [x] 4.1 Добавить в `Worker` keyword-only `rng` и логику исхода (FAILED / DEAD_LETTERED / RETRY_SCHEDULED, политика на момент ошибки, нет обработчика → FAILED); тесты на все ветки, `max_attempts=1`, неповторяемую ошибку на последней попытке, наследника из `non_retryable`
- [x] 4.2 Тест с подменным `rng`: вызовов нет при FAILED/DEAD_LETTERED, ровно один `uniform` на повтор; сквозной тест с `ManualClock`: падение, повтор, успех/dead-letter, requeue, `jobs.*` счётчики

## 5. Экспорт и отчёт

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`; проверить импорт `from jobq import ...`
- [x] 5.2 Тест `render_report` с заданиями в новых статусах: есть строки «Ожидает повтора» и «В dead-letter»; `git diff` не показывает изменений в `jobq/dashboard.py` и `jobq/cli.py`

## 6. Итоговая проверка

- [x] 6.1 Запустить `pytest`: существующие тесты проходят без изменений, новые зелёные; зависимости не добавлены
- [x] 6.2 Сверить публичный API реализации с proposal и specs: поля и значения по умолчанию `RetryPolicy`, сигнатуры `delay_for`, `is_retryable`, `JobQueue(...)`, `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`, `Worker(...)`, значения enum и поля `DeadLetterEntry` совпадают дословно
