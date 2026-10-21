## 1. Ошибки, модели, метрики

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`
- [x] 1.2 В `jobq/models.py` добавить `JobStatus.RETRY_SCHEDULED = "retry_scheduled"` и `JobStatus.DEAD_LETTERED = "dead_lettered"`, подписи «Ожидает повтора» и «В dead-letter»; оба вне `_TERMINAL`; уточнить docstring `is_terminal`
- [x] 1.3 Добавить frozen dataclass `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` в `jobq/models.py`
- [x] 1.4 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` (`jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`) и обновить docstring модуля

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy` (поля и значения по умолчанию из спецификации), нормализацией `non_retryable` в `tuple` и валидацией в `__post_init__` (`ConfigError`, включая NaN и не-классы исключений)
- [x] 2.2 Реализовать `delay_for(attempt, rng=None)`: `attempt < 1` → `ConfigError`; `base_delay == 0` → 0.0; защита от `OverflowError`/inf/NaN; потолок до и после джиттера; один `uniform` только при `jitter > 0`
- [x] 2.3 Реализовать `is_retryable(exc)` (`non_retryable` с наследованием и всегда `PermanentJobError`)

## 3. Очередь и хранилище

- [x] 3.1 `InMemoryJobStore.due`: учитывать `PENDING` и `RETRY_SCHEDULED`
- [x] 3.2 `JobQueue.__init__`: keyword-only `default_retry_policy` (проверка типа → `ConfigError`); `set_retry_policy`, `retry_policy_for` (тип заменяет дефолт целиком)
- [x] 3.3 Обновить `_TRANSITIONS` по таблице из design.md
- [x] 3.4 Добавить `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` (метрики, `finished_at`, запись `DeadLetterEntry`)
- [x] 3.5 Добавить `dead_letters()` (копия, порядок попадания) и `requeue_dead_letter(job_id)` (статус `PENDING`, `run_at = now`, `error = None`, `attempts = 0`, `finished_at = None`, удаление записи, `jobs.requeued`, проверка статуса до изменений)
- [x] 3.6 Убедиться, что `cancel` работает для `RETRY_SCHEDULED` и отклоняется (`InvalidTransitionError`) для `DEAD_LETTERED`, а `purge_finished` не удаляет `DEAD_LETTERED`/`RETRY_SCHEDULED`

## 4. Воркер

- [x] 4.1 `Worker.__init__`: keyword-only `rng: random.Random | None = None`
- [x] 4.2 В `run_once` реализовать алгоритм из design.md: нет обработчика → `FAILED`; нет политики или неповторяемая ошибка → `FAILED`; `attempts >= max_attempts` → `DEAD_LETTERED`; иначе `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`; политика берётся на момент ошибки; `rng` только при планировании повтора

## 5. Экспорт и документация

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py` (`__all__`)
- [x] 5.2 Обновить `README.md`: таблица модулей, раздел о повторах и dead-letter, упоминание новых счётчиков
- [x] 5.3 Не менять `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты

## 6. Тесты (только новые файлы)

- [x] 6.1 `tests/test_retry_policy.py`: значения по умолчанию, валидация, `delay_for` (рост, потолок, `attempt=5000`, `base_delay=0`, `factor=1`, джиттер и потолок, число вызовов `rng`), `is_retryable`
- [x] 6.2 `tests/test_retry_worker.py`: сценарии из `job-retry-execution` (FAILED / RETRY_SCHEDULED / DEAD_LETTERED, `max_attempts=1`, наследование `non_retryable`, замена политики типом, политика на момент ошибки, нет обработчика, `run_at`, отмена, метрики, `rng`)
- [x] 6.3 `tests/test_dead_letter.py`: сценарии из `dead-letter-queue` (запись, порядок, requeue с обнулением `attempts`, ошибки requeue, отмена запрещена, `purge_finished`, статистика и отчёт с подписями)
- [x] 6.4 Прогнать `python -m pytest -q`: старые и новые тесты зелёные

## 7. Сверка публичного API

- [x] 7.1 Сверить реализацию с proposal и specs: имена, порядок и вид параметров (`RetryPolicy`, `delay_for(attempt, rng=None)`, `is_retryable(exc)`, `PermanentJobError`, `JobStatus.RETRY_SCHEDULED`/`DEAD_LETTERED` и значения, `DeadLetterEntry`, `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy=None)`, `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`, `Worker(queue, registry, *, name="worker", rng=None)`), подписи статусов и имена счётчиков; убедиться, что сигнатуры существующих методов не изменились
