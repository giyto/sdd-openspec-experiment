## 0. Согласование до начала

- [x] 0.1 Получить решение по конфликту с существующими тестами (design.md, раздел «Конфликт с существующими тестами»): вариант 1 или 2; до решения тесты не трогаем
- [x] 0.2 Подтвердить значение по умолчанию `DeadLetterEntry.reason = EXHAUSTED` (D2); если нужна обязательность, пересмотреть тесты вместе с 0.1

## 1. Модели и ошибки

- [x] 1.1 Добавить `DeadLetterReason(str, Enum)` (`EXHAUSTED = "exhausted"`, `NON_RETRYABLE = "non_retryable"`) в `jobq/models.py`; проверить значения тестом
- [x] 1.2 Добавить поле `reason: DeadLetterReason = DeadLetterReason.EXHAUSTED` последним полем `DeadLetterEntry`; проверить, что пятиаргументный вызов работает и что `reason` задаётся явно
- [x] 1.3 Добавить `RetryLaterError(JobqError)` в `jobq/errors.py` с `__init__(message="", *, retry_after)`; `retry_after < 0` и нечисловые/не-конечные значения дают `ConfigError`; проверить тестами (сценарий «Negative Retry-After»)

## 2. Джиттер

- [x] 2.1 Изменить множитель в `RetryPolicy.delay_for` на `rng.uniform(1 - jitter, 1)` (`jobq/retry.py`); сохранить один вызов `rng` при `jitter > 0` и clamp к `max_delay`
- [x] 2.2 Проверить сценарии «Jitter with a predictable generator» (8.0 при значении 0.8), «Jitter never delays the retry» (результат в `[5.0, 10.0]` для нескольких генераторов) и «No jitter, no randomness»

## 3. Очередь

- [x] 3.1 Добавить keyword-only `reason: DeadLetterReason = DeadLetterReason.EXHAUSTED` в `mark_dead_lettered` (`jobq/queue.py`); записывать причину в `DeadLetterEntry`; проверить старые вызовы без `reason`
- [x] 3.2 Изменить `purge_finished`: убрать пропуск `DEAD_LETTERED`, для них возраст считать от `dead_lettered_at` записи; удалять задание из хранилища и запись из `_dead_letters`; `jobs.purged` учитывает их; проверить сценарии «Purge removes old dead letters» и «Purge keeps young dead letters»
- [x] 3.3 Реализовать `requeue_all_dead_letters(job_type=None)` по design D6; проверить сценарии «Requeue everything», «Requeue by type», «Nothing to requeue» и порядок возврата

## 4. Воркер

- [x] 4.1 Заменить `_decide_failure` в `jobq/worker.py` на порядок из design D4: нет политики → `FAILED`; неповторяемая → `DEAD_LETTERED`/`non_retryable`; исчерпание → `DEAD_LETTERED`/`exhausted`; `RetryLaterError` → `min(retry_after, max_delay)` без `rng`; иначе `delay_for(attempt, rng)`
- [x] 4.2 Ветку `UnknownJobTypeError` в `run_once` не менять; проверить сценарий «Unknown job type» (`FAILED`, `rng` не тянется)
- [x] 4.3 Проверить сценарии: «Non-retryable error on the last attempt», «Non-retryable error with attempts left» (`rng` не тянется), «Attempts exhausted», «Retry-After larger than max_delay», «Retry-After within the limit», «Retry-After on the last attempt», «No policy» (для `RetryLaterError`)
- [x] 4.4 Записать в лог `info` фактический `retry_after` и итоговую задержку, когда повтор запланирован по `RetryLaterError`

## 5. Публичный API

- [x] 5.1 Экспортировать `RetryLaterError` и `DeadLetterReason` из `jobq/__init__.py`, обновить `__all__`; проверить импортом
- [x] 5.2 Обновить docstring `DeadLetterEntry` и `purge_finished` (новое правило очистки dead-letter), docstring воркера (новые ветки решения)

## 6. Проверка

- [x] 6.1 Запустить `python -m pytest -q`; зафиксировать результат дословно. Ожидаемые падения: `test_non_retryable_marks_failed`, `test_permanent_error_on_last_attempt_marks_failed`, и `permanent`-проверка в `test_rng_is_drawn_only_when_retry_is_scheduled` (см. design.md); если решено вариантом 2 из 0.1, учесть это при отчёте
- [x] 6.2 Через `git diff --stat` убедиться, что `jobq/dashboard.py`, `jobq/cli.py` и файлы существующих тестов не изменены (если выбран вариант 1 из 0.1), и что новых зависимостей нет
- [x] 6.3 Запустить `openspec validate jobq-retry-followup` и убедиться, что ошибок нет
