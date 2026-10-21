## 1. Модели и ошибки

- [x] 1.1 Добавить `DeadLetterReason` и поле `DeadLetterEntry.reason` (последним, по умолчанию `EXHAUSTED`) в `jobq/models.py`; проверить, что `DeadLetterEntry(...)` без `reason` создаётся
- [x] 1.2 Добавить `RetryLaterError(message="", *, retry_after)` в `jobq/errors.py` с проверкой (`ConfigError` для <0, не число, bool, NaN), обновить докстринг `PermanentJobError`; проверить тестом, включая `retry_after=0`
- [x] 1.3 Экспортировать `DeadLetterReason` и `RetryLaterError` из `jobq/__init__.py`; проверить `from jobq import ...`

## 2. Политика и очередь

- [x] 2.1 Изменить джиттер в `RetryPolicy.delay_for` на `uniform(1 - jitter, 1)`; проверить тестом с заглушкой генератора (аргументы вызова, результат не больше расчётного)
- [x] 2.2 Добавить в `JobQueue.mark_dead_lettered` необязательный именованный `reason` и записывать его в запись; проверить, что вызов без него даёт `EXHAUSTED`
- [x] 2.3 Расширить `purge_finished`: удалять задания и записи dead-letter с `dead_lettered_at <= now - older_than`, учитывать в результате и `jobs.purged`; проверить границу возраста, свежие записи и исчезновение из `dead_letters()`
- [x] 2.4 Добавить `JobQueue.requeue_all_dead_letters(job_type=None)`; проверить порядок, фильтр по типу, пустой результат, счётчик `jobs.requeued`, `ConfigError` для не-строки

## 3. Воркер

- [x] 3.1 Переписать `Worker._handle_error`: нет политики → `FAILED`; неповторяемая → dead-letter `NON_RETRYABLE`; исчерпание → `EXHAUSTED`; проверить, что `rng` не вызывается, а неповторяемая на последней попытке даёт `non_retryable`
- [x] 3.2 Добавить обработку `RetryLaterError`: задержка `min(retry_after, max_delay)`, без джиттера и без `rng`; проверить `retry_after=3600` при `max_delay=60`, последнюю попытку (`exhausted`) и отсутствие политики (`FAILED`)

## 4. Проверка

- [x] 4.1 Написать новые тесты по сценариям спеков в новом файле (существующие не менять); запустить его через `pytest` и убедиться, что он проходит
- [x] 4.2 Запустить весь `pytest`, перечислить в отчёте тесты старого поведения, упавшие по причине тикета; убедиться, что остальные проходят, а `git diff` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты
