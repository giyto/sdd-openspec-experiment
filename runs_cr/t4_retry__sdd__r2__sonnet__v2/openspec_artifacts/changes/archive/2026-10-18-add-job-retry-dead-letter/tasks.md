## 1. Базовые типы

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` в тесте
- [x] 1.2 В `jobq/models.py` добавить `RETRY_SCHEDULED`, `DEAD_LETTERED` (нетерминальные), подписи «Ожидает повтора» / «В dead-letter» и `DeadLetterEntry` (frozen dataclass); проверить тестом значения, подписи, `is_terminal`
- [x] 1.3 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` и обновить docstring; проверить импортом в тесте

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py`: frozen `RetryPolicy` со значениями по умолчанию, нормализацией `non_retryable` в tuple и валидацией (`ConfigError`, включая NaN); проверить тестами на каждый недопустимый параметр и граничные значения
- [x] 2.2 Реализовать `delay_for` (защита от `OverflowError`, `base_delay=0`, потолок после джиттера, один `uniform`, без rng при `jitter=0`, `attempt < 1` → `ConfigError`); проверить тестами: 1,2,4,8; attempt 5000 и 10**9; джиттер на границах не выше `max_delay`; подсчёт вызовов rng
- [x] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError`); проверить тестом с наследником `ValueError`

## 3. Очередь и хранилище

- [x] 3.1 В `InMemoryJobStore.due` учесть `RETRY_SCHEDULED`; проверить тестом выборки и порядка `(run_at, seq)`
- [x] 3.2 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` (замена целиком, `None` снимает, проверка типов); проверить тестами приоритета и ошибок конфигурации
- [x] 3.3 Расширить `_TRANSITIONS`, добавить `mark_retry_scheduled` и `mark_dead_lettered` (счётчики, запись в dead-letter, `error`), очистку `error` в `mark_succeeded`; проверить тестами переходов и `jobs.retried` / `jobs.dead_lettered`
- [x] 3.4 Реализовать `dead_letters()` (копия списка, порядок попадания) и `requeue_dead_letter()` (тот же объект, PENDING, `run_at=now`, `error=None`, `attempts=0`, `finished_at=None`, `jobs.requeued`, ошибки для неизвестного id и не-dead-letter); проверить тестами
- [x] 3.5 Проверить тестами: отмена из `RETRY_SCHEDULED` работает, из `DEAD_LETTERED` — `InvalidTransitionError`, `purge_finished` не удаляет dead-letter и ожидающие повтора

## 4. Воркер

- [x] 4.1 Добавить keyword-only `rng` в `Worker` и ветвление ошибок по политике, действующей в момент ошибки (FAILED / DEAD_LETTERED / RETRY_SCHEDULED, `run_at = now + delay_for(job.attempts, rng)`); проверить тестами: без политики → FAILED, max_attempts=1 → DEAD_LETTERED, неповторяемая на последней попытке → FAILED, нет обработчика → FAILED
- [x] 4.2 Проверить сквозными тестами с `ManualClock`: цепочка 3 попыток до dead-letter и счётчики; повтор не берётся до `run_at`; успех после ошибки даёт `error=None`; после requeue первая ошибка → RETRY_SCHEDULED; rng не трогается при FAILED / DEAD_LETTERED / `jitter=0` и вызывается ровно раз при планировании

## 5. Экспорт, документация, итоговая проверка

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`; проверить импортом `from jobq import ...`
- [x] 5.2 Обновить README (таблица модулей, раздел о повторах и dead-letter); проверить визуально
- [x] 5.3 Запустить `python -m pytest -q` и убедиться, что существующие тесты проходят без изменений, а `git diff --stat` не содержит `jobq/dashboard.py`, `jobq/cli.py` и существующих тестов; проверить отчёт `render_report` на строки новых статусов
