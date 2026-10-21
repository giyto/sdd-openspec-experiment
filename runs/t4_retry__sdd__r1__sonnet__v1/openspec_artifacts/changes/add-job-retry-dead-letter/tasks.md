## 1. Основа: ошибки, модели, метрики

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить тестом `issubclass(PermanentJobError, JobqError)`
- [x] 1.2 В `jobq/models.py` добавить `JobStatus.RETRY_SCHEDULED`/`DEAD_LETTERED` с подписями «Ожидает повтора»/«В dead-letter», `is_terminal` (True только у DEAD_LETTERED) и frozen `DeadLetterEntry`; проверить тестом значений, подписей и `is_terminal`
- [x] 1.3 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`; проверить, что имена равны `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py`: frozen `RetryPolicy` с дефолтами, нормализацией `non_retryable` в `tuple` и валидацией (`ConfigError`); проверить тестами на каждое недопустимое и граничное значение
- [x] 2.2 Реализовать `delay_for` (экспонента, потолок, `attempt < 1` → `ConfigError`, защита от `OverflowError`/NaN, `base_delay=0`, `factor=1`); проверить тестами, включая `attempt=5000` и `10**6`
- [x] 2.3 Добавить джиттер (один вызов `uniform(1-j, 1+j)`, повторный потолок `max_delay`, `jitter=0` не трогает `rng`) и `is_retryable` (подклассы, `PermanentJobError`); проверить тестом с мок-генератором, считающим вызовы

## 3. Хранилище и очередь

- [x] 3.1 `InMemoryJobStore.due()` учитывает `PENDING` и `RETRY_SCHEDULED`, сортировка `(run_at, seq)`; проверить тестом порядка при равном `run_at`
- [x] 3.2 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for`; проверить тестами полной замены, сброса `None` и отсутствия политик
- [x] 3.3 Расширить `_TRANSITIONS` (RUNNING→RETRY_SCHEDULED/DEAD_LETTERED, RETRY_SCHEDULED→RUNNING/CANCELLED, DEAD_LETTERED→PENDING), очищать `error` в `mark_succeeded`, добавить `mark_retry_scheduled`/`mark_dead_lettered` с метриками; проверить тестами переходов и `cancel` для обоих новых статусов
- [x] 3.4 Реализовать `dead_letters()` и `requeue_dead_letter()` (сброс `attempts`, `error`, `finished_at`, `run_at=now`, метрика `jobs.requeued`, ошибки `JobNotFoundError`/`InvalidTransitionError`); проверить тестами порядка, повторного попадания и ошибок
- [x] 3.5 `purge_finished()` не удаляет `DEAD_LETTERED`; проверить тестом, что остальные завершённые удаляются, а dead-letter остаётся

## 4. Воркер

- [x] 4.1 Добавить keyword-only `rng` в `Worker` (по умолчанию `random.Random()`) и логику выбора FAILED / DEAD_LETTERED / RETRY_SCHEDULED в порядке из спецификации; проверить тестами: без политики, неповторяемая на последней попытке, `max_attempts=1`, исчерпание, планирование повтора с `ManualClock`
- [x] 4.2 Проверить метрики и `rng`: `jobs.failed` не растёт при повторе/dead-letter, `rng` не вызывается при dead-letter/FAILED; тест с мок-генератором
- [x] 4.3 Проверить сквозные сценарии: успех после повтора (`error is None`, `attempts`), нулевая задержка в одном `run_pending()`, смена политики во время ожидания, отсутствие обработчика → `FAILED`

## 5. Экспорт, отчёт, документация

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py` и обновить `README.md`; проверить импортом из `jobq`
- [x] 5.2 Проверить, что `render_report` показывает «Ожидает повтора» и «В dead-letter» с количеством без правок `dashboard.py` (новый тест в новом файле)
- [x] 5.3 Запустить весь `pytest`: существующие тесты проходят без изменений, а `git diff --stat` не содержит `jobq/dashboard.py`, `jobq/cli.py` и файлов старых тестов
