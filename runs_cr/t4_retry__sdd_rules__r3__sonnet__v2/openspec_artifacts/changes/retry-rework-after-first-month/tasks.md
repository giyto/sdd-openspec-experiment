## 1. Модели и ошибки

- [x] 1.1 Добавить `DeadLetterReason(str, Enum)` (`EXHAUSTED="exhausted"`, `NON_RETRYABLE="non_retryable"`) и последнее поле `DeadLetterEntry.reason` со значением по умолчанию `EXHAUSTED` в `jobq/models.py`; проверить тестом создание записи без `reason` и значения enum
- [x] 1.2 Добавить `RetryLaterError(JobqError)` с `__init__(self, message: str = "", *, retry_after: float)` и атрибутом `retry_after` в `jobq/errors.py`; проверить тестами: `retry_after=-1`, NaN и не число → `ConfigError`, `0` допустим, `str(exc)` равен сообщению
- [x] 1.3 Экспортировать `DeadLetterReason` и `RetryLaterError` в `jobq/__init__.py`, если там экспортируются остальные модели/ошибки; проверить импортом `from jobq import ...`

## 2. Политика и джиттер

- [x] 2.1 Изменить множитель джиттера в `RetryPolicy.delay_for` на `rng.uniform(1 - jitter, 1)`; проверить тестом с поддельным `rng`: один вызов с аргументами `(1 - jitter, 1)`, результат не превышает расчётной задержки, потолок и `jitter == 0` без вызовов `rng` сохранены

## 3. Очередь

- [x] 3.1 Добавить необязательный параметр `reason` (по умолчанию `EXHAUSTED`) в `JobQueue.mark_dead_lettered` и записывать его в `DeadLetterEntry`; проверить тестом, что старый вызов даёт `EXHAUSTED`, а вызов с `NON_RETRYABLE` сохраняет причину
- [x] 3.2 Реализовать `JobQueue.requeue_all_dead_letters(job_type=None) -> list[Job]` через `requeue_dead_letter` по снимку `dead_letters()`; проверить тестами: порядок как в `dead_letters()`, фильтр по типу, пустой dead-letter и неизвестный тип → `[]`, `jobs.requeued` растёт на число заданий
- [x] 3.3 Расширить `purge_finished`: удалять задания и записи dead-letter с `dead_lettered_at <= now - older_than`, включать их в возвращаемое число и `jobs.purged`; проверить тестами: удаление при `older_than=0`, возраст от `dead_lettered_at`, моложе порога остаётся, `RETRY_SCHEDULED` не удаляется, запись пропадает из `dead_letters()`

## 4. Воркер

- [x] 4.1 Переписать `Worker._handle_failure` по порядку: нет политики → `FAILED`; неповторяемая → dead-letter `NON_RETRYABLE`; `attempts >= max_attempts` → dead-letter `EXHAUSTED`; иначе повтор; проверить тестами все сценарии спецификации, включая `PermanentJobError` на первой и последней попытке, `max_attempts=1` и отсутствие вызовов `rng` для неповторяемых ошибок
- [x] 4.2 Обработать `RetryLaterError` в планировании повтора: задержка `min(retry_after, max_delay)`, без `delay_for` и без обращения к `rng` даже при `jitter > 0`; проверить тестами: `retry_after=10`, `3600` при `max_delay=60`, `0`, последняя попытка → `EXHAUSTED`, без политики → `FAILED`

## 5. Сверка

- [x] 5.1 Запустить полный набор тестов (`pytest`) и перечислить тесты, расходящиеся с новыми требованиями JOBQ-237 (существующие тесты не править, новые тесты класть в отдельные файлы); убедиться, что `jobq/dashboard.py`, `jobq/cli.py` не изменены (`git diff --stat`)
- [x] 5.2 Сверить публичный API реализации с proposal и specs: `DeadLetterReason` и значения, порядок и имя поля `DeadLetterEntry.reason` (последнее), сигнатуры `RetryLaterError.__init__(message="", *, retry_after)` и атрибут `retry_after`, `JobQueue.requeue_all_dead_letters(job_type=None) -> list[Job]`, неизменность сигнатур существующих методов; проверить через `inspect.signature` и `openspec validate retry-rework-after-first-month`
