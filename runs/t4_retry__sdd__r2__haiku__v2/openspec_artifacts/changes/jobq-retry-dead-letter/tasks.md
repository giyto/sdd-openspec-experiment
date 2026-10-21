## 1. Модель и ошибки

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py` и проверить, что он наследуется от `JobqError`
- [x] 1.2 Добавить `JobStatus.RETRY_SCHEDULED` ("Ожидает повтора") и `JobStatus.DEAD_LETTERED` ("В dead-letter") в `jobq/models.py`; `DEAD_LETTERED` включить в терминальные; проверить `label` и `is_terminal` в тесте-скрипте
- [x] 1.3 Добавить `DeadLetterEntry` (frozen dataclass) в `jobq/models.py` и проверить, что он неизменяем
- [x] 1.4 Добавить константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `jobq/metrics.py` и дополнить docstring модуля

## 2. Политика повторов

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy`: `__post_init__` валидирует поля (`ConfigError`), `non_retryable` приводится к `tuple`; проверить тестом все невалидные значения из спецификации
- [x] 2.2 Реализовать `delay_for(attempt, rng=None)` без переполнения (`OverflowError` → `max_delay`), с ограничением `max_delay`, с джиттером и повторным ограничением; проверить сценарии из `specs/job-retry/spec.md` (рост, потолок, `attempt=10000`, `base_delay=0`, `attempt < 1`)
- [x] 2.3 Реализовать `is_retryable(exc)`: `non_retryable` с учётом наследования и `PermanentJobError` всегда `False`; проверить тестами
- [x] 2.4 Проверить, что `rng.uniform` вызывается ровно один раз при `jitter > 0` и не вызывается при `jitter == 0` (тест с подставным `rng`)

## 3. Очередь: политики и dead-letter

- [x] 3.1 Добавить keyword-only `default_retry_policy` в `JobQueue.__init__` и поля для политик типов и dead-letter записей; существующие вызовы конструктора должны работать без изменений
- [x] 3.2 Реализовать `set_retry_policy(job_type, policy)` (`None` снимает политику типа, пустой `job_type` — `ConfigError`) и `retry_policy_for(job_type)` (эффективная политика без слияния полей); проверить сценарии из `specs/job-retry/spec.md`
- [x] 3.3 Расширить `_TRANSITIONS`: `RUNNING → RETRY_SCHEDULED`, `RUNNING → DEAD_LETTERED`, `RETRY_SCHEDULED → RUNNING`, `RETRY_SCHEDULED → CANCELLED`, `DEAD_LETTERED → PENDING`; проверить, что `cancel` для `DEAD_LETTERED` даёт `InvalidTransitionError`
- [x] 3.4 Добавить `schedule_retry(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` в `JobQueue`: переходы, `job.error`, `finished_at`, запись в dead-letter, счётчики `jobs.retried` / `jobs.dead_lettered`; проверить тестами
- [x] 3.5 Изменить `InMemoryJobStore.due()`, чтобы он брал `PENDING` и `RETRY_SCHEDULED`; существующий тест `store.due` должен пройти без изменений
- [x] 3.6 Изменить `purge_finished`, чтобы он пропускал `DEAD_LETTERED`; проверить, что запись и задание остаются после `purge_finished(older_than=0)`
- [x] 3.7 Реализовать `dead_letters()` (порядок попадания) и `requeue_dead_letter(job_id)` (`PENDING`, `run_at = now`, `error = None`, `finished_at = None`, `attempts = 0`, удаление записи, `jobs.requeued`, лог с числом попыток до перезапуска); проверить сценарии из `specs/dead-letter/spec.md`, включая `JobNotFoundError` и `InvalidTransitionError` для `FAILED`

## 4. Воркер

- [x] 4.1 Добавить keyword-only `rng` в `Worker.__init__` (по умолчанию `random.Random()`) и хранить его
- [x] 4.2 В `Worker.run_once` при исключении обработчика выбирать исход по политике, которая действует в момент ошибки (`queue.retry_policy_for`): `FAILED` для отсутствия политики, неповторяемой ошибки, `PermanentJobError`; `DEAD_LETTERED` при `attempts >= max_attempts`; иначе `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`; проверить, что `rng` не вызывается в `FAILED` и `DEAD_LETTERED`
- [x] 4.3 Оставить `UnknownJobTypeError` переводом в `FAILED` без повтора; проверить тестом с политикой для этого типа
- [x] 4.4 Проверить полный цикл: упасть N раз → `DEAD_LETTERED` → `requeue_dead_letter` → успешное выполнение, с тем же `job.id`; проверить, что после requeue первая ошибка даёт `RETRY_SCHEDULED`

## 5. Публичный API и документация

- [x] 5.1 Экспортировать `RetryPolicy`, `DeadLetterEntry`, `PermanentJobError` в `jobq/__init__.py` и `__all__`
- [x] 5.2 Обновить `README.md`: строка `jobq/retry.py` в таблице модулей и пункт о повторах в «Соглашениях»
- [x] 5.3 Проверить, что `jobq/dashboard.py` и `jobq/cli.py` не изменены (`git diff --stat`) и существующие тесты в `tests/` не изменены

## 6. Проверка

- [x] 6.1 Добавить новые тесты в `tests/` (отдельные файлы, например `tests/test_retry.py`, `tests/test_dead_letter.py`), не меняя существующие
- [x] 6.2 Запустить `python -m pytest -q` и убедиться, что все тесты (старые и новые) проходят; вывод приложить к отчёту
- [x] 6.3 Убедиться, что ни одна новая зависимость не добавлена (`pytest.ini`, `requirements*` не изменены)
