## 1. Модели и ошибки

- [x] 1.1 `jobq/models.py`: добавить `DeadLetterReason(str, Enum)` (`EXHAUSTED = "exhausted"`, `NON_RETRYABLE = "non_retryable"`) и последнее поле `reason: DeadLetterReason = DeadLetterReason.EXHAUSTED` в `DeadLetterEntry`
- [x] 1.2 `jobq/errors.py`: добавить `RetryLaterError(JobqError)` с `__init__(self, message: str = "", *, retry_after: float)`, атрибутом `retry_after` и валидацией (`ConfigError` для отрицательных, `NaN`, `bool`, нечисловых)
- [x] 1.3 `jobq/__init__.py`: экспортировать `DeadLetterReason` и `RetryLaterError`

## 2. Политика

- [x] 2.1 `jobq/retry.py`: джиттер как `rng.uniform(1 - jitter, 1)`, убрать повторное ограничение сверху; результат в `[0, max_delay]`

## 3. Очередь

- [x] 3.1 `mark_dead_lettered(job_id, error, *, reason=DeadLetterReason.EXHAUSTED)` пишет причину в запись
- [x] 3.2 `purge_finished` удаляет и dead-letter задания по `dead_lettered_at <= now - older_than`, чистит `dead_letters()`, учитывает их в возвращаемом числе и `jobs.purged`
- [x] 3.3 `requeue_all_dead_letters(job_type: str | None = None) -> list[Job]`: порядок `dead_letters()`, фильтр по типу, `[]` если нечего, `ConfigError` для пустой строки

## 4. Воркер

- [x] 4.1 `_handle_failure`: неповторяемая ошибка при наличии политики → dead-letter с `NON_RETRYABLE` на любой попытке; исчерпание → `EXHAUSTED`; без политики и без обработчика по-прежнему `FAILED`
- [x] 4.2 `RetryLaterError`: задержка `min(retry_after, max_delay)`, без джиттера и без обращения к `rng`; на последней попытке — `EXHAUSTED`

## 5. Тесты

- [x] 5.1 Обновить тесты заменённого поведения: `test_purge_keeps_dead_letter`, `test_non_retryable_on_last_attempt`, `test_jitter_capped`, `test_jitter_applied_once`, ветку `y` в `test_rng_usage`; остальные существующие тесты не менять
- [x] 5.2 Новые тесты по сценариям specs: джиттер вниз, причины, `RetryLaterError` (потолок, без rng, последняя попытка, без политики, валидация), purge dead-letter по возрасту, `requeue_all_dead_letters` (всё, по типу, пусто, порядок, счётчик)
- [x] 5.3 Запустить весь набор тестов, убедиться, что `dashboard.py` и `cli.py` не изменены

## 6. Сверка публичного API

- [x] 6.1 Сверить реализацию с proposal и specs: `DeadLetterReason` и значения, поле `DeadLetterEntry.reason` последним, `RetryLaterError(message="", *, retry_after)` и атрибут `retry_after`, `JobQueue.requeue_all_dead_letters(job_type=None) -> list[Job]`, неизменность сигнатур существующих методов
