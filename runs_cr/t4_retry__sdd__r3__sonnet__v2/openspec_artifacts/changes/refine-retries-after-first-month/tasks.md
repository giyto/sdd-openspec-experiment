## 1. Модели и ошибки

- [x] 1.1 Добавить `DeadLetterReason` и последнее поле `DeadLetterEntry.reason` (дефолт `EXHAUSTED`) в `jobq/models.py`; проверить, что `DeadLetterEntry` из пяти аргументов по-прежнему создаётся (новый тест)
- [x] 1.2 Добавить `RetryLaterError(message="", *, retry_after)` в `jobq/errors.py` с валидацией `ConfigError`; новые тесты на иерархию, атрибут, `-1`, NaN, `inf`, `True`, строку, `0`
- [x] 1.3 Экспортировать `DeadLetterReason` и `RetryLaterError` из `jobq/__init__.py`; проверить `from jobq import DeadLetterReason, RetryLaterError`

## 2. Политика и воркер

- [x] 2.1 В `RetryPolicy.delay_for` заменить множитель джиттера на `uniform(1 - jitter, 1)`, оставив ограничение `[0, max_delay]`; новый тест: аргументы `uniform`, результат не больше расчётной задержки, один вызов, потолок при `uniform > 1`
- [x] 2.2 В `JobQueue.mark_dead_lettered` добавить keyword-only `reason` (дефолт `EXHAUSTED`) и записывать его в `DeadLetterEntry`; проверить, что старый вызов без `reason` даёт `exhausted`
- [x] 2.3 Переписать `Worker._handle_failure`: неповторяемая ошибка при политике → dead-letter с `NON_RETRYABLE` (в том числе на последней попытке), исчерпание → `EXHAUSTED`, без политики → `FAILED`; новые тесты на все ветки и на счётчики (`jobs.dead_lettered` растёт, `jobs.failed` нет)
- [x] 2.4 Обработать `RetryLaterError` в воркере: `run_at = now + min(retry_after, max_delay)`, без `delay_for` и без обращения к `rng`; новые тесты: 30 с, 3600 → потолок 60, 0, последняя попытка → `exhausted`, `rng` не тронут при `jitter > 0`, без политики → `FAILED`

## 3. Очередь

- [x] 3.1 Изменить `purge_finished`: удалять `DEAD_LETTERED` по правилу возраста от момента попадания в dead-letter и убирать запись из `dead_letters()`; новые тесты: удаление, порог `older_than` (50 против 200), счётчик `jobs.purged`, `JobNotFoundError` на `requeue_dead_letter` после очистки, `RETRY_SCHEDULED` не удаляется
- [x] 3.2 Добавить `JobQueue.requeue_all_dead_letters(job_type=None)` поверх `requeue_dead_letter`; новые тесты: порядок `dead_letters()`, фильтр по типу, пустой dead-letter и отсутствие типа → `[]` без изменения `jobs.requeued`, `ConfigError` на `""`/не строку без побочных эффектов, полный набор попыток после возврата

## 4. Документация и проверка

- [x] 4.1 Обновить `README.md` (три пересмотренных правила, `DeadLetterReason`, `RetryLaterError`, `requeue_all_dead_letters`) и убедиться, что `git diff --stat` не содержит `jobq/dashboard.py`, `jobq/cli.py` и существующих файлов тестов
- [x] 4.2 Запустить `pytest` целиком: все новые тесты проходят; список существующих тестов, падающих из-за пересмотренных правил, не править, а перечислить в отчёте владельцу тикета; остальные существующие тесты проходят без изменений
