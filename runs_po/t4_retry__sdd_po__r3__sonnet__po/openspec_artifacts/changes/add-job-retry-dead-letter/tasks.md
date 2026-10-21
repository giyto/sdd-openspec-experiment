## 1. Модели, ошибки, метрики

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить тестом `issubclass(PermanentJobError, JobqError)`
- [x] 1.2 Добавить `RETRY_SCHEDULED`, `DEAD_LETTERED`, подписи «Ожидает повтора» и «В dead-letter» и `DeadLetterEntry` (frozen dataclass) в `jobq/models.py`, не включая новые статусы в `_TERMINAL`; проверить тестом подписей и `is_terminal`
- [x] 1.3 Добавить константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` (`jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`) в `jobq/metrics.py` и дополнить docstring; проверить, что неизвестный счётчик читается как 0

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy`: поля и значения по умолчанию, валидация в `__post_init__` (`ConfigError`), нормализация `non_retryable` в кортеж; проверить параметризованными тестами на каждое некорректное значение (включая NaN, не-класс, список → кортеж)
- [x] 2.2 Реализовать `delay_for` (формула, ограничение `max_delay`, jitter после ограничения и результат не выше `max_delay`, один `uniform` только при `jitter > 0`, `attempt < 1` → `ConfigError`, без `OverflowError`, `base_delay=0` → 0, `factor=1`); проверить тестами: `delay_for(5001)`, `delay_for(10**6)` с `factor=2`, `base_delay=0`, сценарии jitter (`1.5` при `max_delay=60` → `60`), `Random(seed)` и счётчик вызовов у подставного `rng`
- [x] 2.3 Реализовать `is_retryable` (наследование через `isinstance`, `PermanentJobError` всегда `False`); проверить тестом с наследником `ValueError`

## 3. Очередь и хранилище

- [x] 3.1 В `InMemoryJobStore.due()` включить `RETRY_SCHEDULED`; проверить тестом, что повтор не выбирается до `run_at` и выбирается после, порядок `(run_at, seq)` сохранён
- [x] 3.2 Расширить `_TRANSITIONS` (см. design, п. 5); проверить тестом допустимых и недопустимых переходов, включая `cancel` из `RETRY_SCHEDULED` и ошибку `cancel` из `DEAD_LETTERED`
- [x] 3.3 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for`; проверить тестами: замена целиком, снятие через `None`, поведение без политик
- [x] 3.4 Добавить `mark_retry_scheduled` и `mark_dead_lettered` (запись `error`, счётчики, `DeadLetterEntry` с временем очереди), `dead_letters()` (копия в порядке попадания); проверить тестами содержимого, порядка и счётчиков (`jobs.failed` не растёт)
- [x] 3.5 Добавить `requeue_dead_letter` (то же задание, `PENDING`, `run_at=now`, `error=None`, `attempts=0`, запись удалена, `jobs.requeued`; `JobNotFoundError` и `InvalidTransitionError` без побочных эффектов); проверить тестами каждого сценария из `specs/dead-letter`
- [x] 3.6 Проверить тестом, что `purge_finished` не удаляет `RETRY_SCHEDULED` и `DEAD_LETTERED`

## 4. Воркер

- [x] 4.1 Добавить в `Worker.__init__` keyword-only `rng` (по умолчанию `random.Random()`); проверить, что старые вызовы `Worker(queue, registry, name=...)` работают
- [x] 4.2 Реализовать выбор исхода в `run_once` в порядке из design, п. 4 (нет обработчика → `FAILED`; нет политики/неповторяемая → `FAILED`; исчерпано → `DEAD_LETTERED`; иначе `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`); проверить тестами со сценариями из `specs/job-retry`, включая `max_attempts=1`, неповторяемую ошибку на последней попытке, политику на момент ошибки и число обращений к `rng`
- [x] 4.3 Защититься от `OverflowError` при построении `timedelta` для огромного `max_delay` (design, «Риски»); проверить тестом с `max_delay=1e20`
- [x] 4.4 Сквозной тест: повторы идут по `ManualClock`, задание в итоге `SUCCEEDED` с `error is None`; и цикл «dead-letter → requeue → полный набор попыток → успех»

## 5. Экспорты и документация

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`; проверить импортом `from jobq import ...`
- [x] 5.2 Обновить `README.md` (модуль `retry.py`, раздел о повторах и dead-letter, новые счётчики и статусы)
- [x] 5.3 Проверить, что отчёт `render_report` показывает новые подписи (новый тест без правок `dashboard.py`), что `git diff` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты, и что `python -m pytest -q` проходит целиком
