## 1. Модели и исключения

- [x] 1.1 Добавить `DeadLetterReason(str, Enum)` со значениями `EXHAUSTED`/`NON_RETRYABLE` в `jobq/models.py` и поле `reason` (default `EXHAUSTED`) последним полем `DeadLetterEntry`; проверить, что `DeadLetterEntry(...)` со старым набором аргументов создаётся и `reason` равен `EXHAUSTED`
- [x] 1.2 Добавить `RetryLaterError(message="", *, retry_after)` в `jobq/errors.py`; конструктор выбрасывает `ConfigError` при `retry_after < 0`, нечисловом или неконечном значении; проверить тестом из spec «Server-specified retry delay»
- [x] 1.3 Экспортировать `DeadLetterReason` и `RetryLaterError` из `jobq/__init__.py` и добавить в `__all__`; проверить `from jobq import DeadLetterReason, RetryLaterError`

## 2. Джиттер и задержка от сервера

- [x] 2.1 Изменить множитель джиттера в `RetryPolicy.delay_for` на `rng.uniform(1 - jitter, 1)` в `jobq/retry.py` и обновить docstring поля `jitter`; проверить сценарии «Джиттер уменьшает ограниченную задержку», «Джиттер не увеличивает задержку» и «Джиттер не пробивает max_delay»
- [x] 2.2 Проверить, что при `jitter = 0` и при `RetryLaterError` генератор `rng` не вызывается (сценарии «Без джиттера генератор не используется» и «Джиттер и генератор не используются»)

## 3. Решение воркера

- [x] 3.1 Переписать `Worker._handle_failure` в `jobq/worker.py` по порядку из design.md (решение 1): нет политики → `FAILED`; неповторяемая → `DEAD_LETTERED` с `NON_RETRYABLE`; исчерпание → `DEAD_LETTERED` с `EXHAUSTED`; `RetryLaterError` → `RETRY_SCHEDULED` с `min(retry_after, max_delay)`; иначе — `delay_for`; проверить сценарии требования «Worker decision after handler failure» и «Server-specified retry delay»
- [x] 3.2 Добавить keyword-only параметр `reason` (default `EXHAUSTED`) в `JobQueue.mark_dead_lettered` в `jobq/queue.py` и записывать его в `DeadLetterEntry`; проверить сценарий «Старый вызов mark_dead_lettered»
- [x] 3.3 Обновить docstring `Worker`/`_handle_failure`, описывающие прежние правила (неповторяемые ошибки → `FAILED`), и проверить, что текст соответствует новым правилам

## 4. Очистка и массовый перезапуск dead-letter

- [x] 4.1 Изменить `JobQueue.purge_finished` в `jobq/queue.py`: включить `DEAD_LETTERED` в очистку по `finished_at`, при удалении убирать запись из `_dead_letters`; обновить docstring; проверить сценарии требования «Dead-lettered jobs are kept until requeued or purged»
- [x] 4.2 Добавить `JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]` в `jobq/queue.py` через `requeue_dead_letter` в порядке `dead_letters()`; проверить сценарии требования «Bulk requeue of dead-lettered jobs» (все записи, по типу, пустой результат)

## 5. Тесты и проверка

- [x] 5.1 Добавить новый файл тестов `tests/test_retry_followups.py` для сценариев изменённых и добавленных требований (существующие файлы тестов не меняем); запустить `pytest tests/test_retry_followups.py` и убедиться, что все проходят
- [x] 5.2 Запустить весь набор `pytest` и убедиться, что существующие тесты проходят без изменения; если существующий тест ломается из-за изменения спеки (например, ожидает `FAILED` для `PermanentJobError`), зафиксировать это в отчёте и не править тест без согласования
- [x] 5.3 Проверить, что `jobq/dashboard.py` и `jobq/cli.py` не изменены (`git diff --stat`) и что новых зависимостей в проекте нет

## 6. Документация

- [x] 6.1 Обновить README.md разделом о неповторяемых ошибках, джиттере, `RetryLaterError` и очистке dead-letter, если в README описано прежнее поведение; проверить по тексту README, что прежние формулировки убраны
