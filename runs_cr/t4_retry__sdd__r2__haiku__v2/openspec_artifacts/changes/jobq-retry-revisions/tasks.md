## 1. Модель и ошибки

- [x] 1.1 Добавить `RetryLaterError(JobqError)` с `retry_after` в `jobq/errors.py`; проверка `retry_after` (число, конечное, не меньше 0) через `ConfigError` в конструкторе
- [x] 1.2 Добавить `DeadLetterReason(str, Enum)` (`EXHAUSTED`, `NON_RETRYABLE`) в `jobq/models.py`
- [x] 1.3 Добавить поле `reason: DeadLetterReason = DeadLetterReason.EXHAUSTED` последним в `DeadLetterEntry`

## 2. Политика повторов

- [x] 2.1 В `RetryPolicy.delay_for` заменить множитель на `rng.uniform(1 - jitter, 1)`; оставить `min(..., max_delay)` после умножения
- [x] 2.2 Проверить, что `rng.uniform` вызывается с аргументами `(1 - jitter, 1)`, и что задержка не превышает расчётную (новые тесты в `tests/test_retry_revisions.py`)

## 3. Очередь: dead-letter

- [x] 3.1 Добавить keyword-only `reason` (по умолчанию `EXHAUSTED`) в `JobQueue.mark_dead_lettered`; запись получает `reason`
- [x] 3.2 Изменить `purge_finished`: убрать пропуск `DEAD_LETTERED`, для них сравнивать `entry.dead_lettered_at` с cutoff и удалять запись вместе с заданием
- [x] 3.3 Реализовать `requeue_all_dead_letters(job_type: str | None = None)`: снимок записей, фильтр по типу, перезапуск через `requeue_dead_letter`, пустой `job_type` — `ConfigError`
- [x] 3.4 Тесты: очистка по возрасту попадания, сохранение свежих записей, удаление записи вместе с заданием, `reason`, `requeue_all_dead_letters` (все, по типу, пусто, пустая строка)

## 4. Воркер

- [x] 4.1 В `Worker._handle_failure` порядок: нет политики → `FAILED`; неповторяемая ошибка → `DEAD_LETTERED` с `NON_RETRYABLE`; исчерпание → `DEAD_LETTERED` с `EXHAUSTED`; `RetryLaterError` → `RETRY_SCHEDULED` с `min(retry_after, max_delay)` без `rng`; иначе — прежняя задержка по политике
- [x] 4.2 Тесты: `PermanentJobError` и неповторяемое исключение с политикой → `DEAD_LETTERED`/`NON_RETRYABLE`, в том числе на последней попытке; без политики → `FAILED`; `rng` не вызывается для неповторяемой ошибки и для `RetryLaterError`
- [x] 4.3 Тесты `RetryLaterError`: `retry_after` используется как задержка; больше `max_delay` — режется; `retry_after=0`; исчерпание попыток → `EXHAUSTED`; без политики → `FAILED`; отрицательное и `nan` — `ConfigError` при конструировании

## 5. Публичный API и документация

- [x] 5.1 Экспортировать `RetryLaterError` и `DeadLetterReason` в `jobq/__init__.py` и `__all__`
- [x] 5.2 Обновить `README.md`: раздел «Соглашения» (неповторяемые ошибки, `RetryLaterError`, причины dead-letter, очистка по возрасту, `requeue_all_dead_letters`)
- [x] 5.3 Проверить `git diff --stat`: `jobq/dashboard.py`, `jobq/cli.py`, существующие файлы `tests/` не изменены; `pytest.ini` и зависимости не изменены

## 6. Проверка

- [x] 6.1 Запустить `python -m pytest -q`; вывод приложить к отчёту. Ожидаемые падения — ровно четыре теста из раздела «Конфликт с существующими тестами» в `design.md`; другие падения — ошибка реализации
- [x] 6.2 Существующие тесты не переписывать. Обновление четырёх ожиданий — только после явного согласия команды
