## Why

После месяца эксплуатации повторов и dead-letter (JOBQ-212) дежурные и биллинг собрали претензии: задания с неповторяемой ошибкой теряются в `FAILED` и их ищут по логам, джиттер может отдать повтор позже расчётного времени (SLA почты), а в dead-letter накопилось 40 тысяч записей без способа очистки. Часть договорённостей JOBQ-212 пересматривается (JOBQ-237).

## What Changes

- **BREAKING (поведение)**: неповторяемая ошибка (включая `PermanentJobError`) при действующей политике сразу отправляет задание в dead-letter, без повторов, вместо `FAILED`. Без политики поведение прежнее (`FAILED`).
- **BREAKING (поведение)**: джиттер только уменьшает задержку: множитель `rng.uniform(1 - jitter, 1)` вместо `uniform(1 - jitter, 1 + jitter)`.
- **BREAKING (поведение)**: `purge_finished` чистит и dead-letter по тому же правилу возраста, считая от `dead_lettered_at`; запись исчезает и из `dead_letters()`.
- Новый `DeadLetterReason` (`EXHAUSTED`, `NON_RETRYABLE`) и поле `DeadLetterEntry.reason` (последним).
- Новое исключение `RetryLaterError(message="", *, retry_after)`: временная ошибка с заданным сервером временем следующей попытки. Задержка = `retry_after`, ограниченная `max_delay`, без джиттера, `rng` не используется (решение тимлида от 04.11 отменяет формулировку тикета про джиттер).
- Новый `JobQueue.requeue_all_dead_letters(job_type=None)`: массовый возврат из dead-letter в порядке `dead_letters()`.
- Сигнатуры существующих публичных методов не меняются; `jobq/dashboard.py` и `jobq/cli.py` не трогаем; новых зависимостей нет.

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities
- `retry-policy`: джиттер только вниз; добавляется `RetryLaterError` с валидацией `retry_after`.
- `job-retry`: исход неповторяемой ошибки (dead-letter), обработка `RetryLaterError`, использование `rng`.
- `dead-letter`: поле `reason`, очистка через `purge_finished`, массовый возврат.

## Impact

- Код: `jobq/models.py`, `jobq/errors.py`, `jobq/queue.py`, `jobq/retry.py`, `jobq/worker.py`, `jobq/__init__.py` (экспорт новых имён), `README.md`; новые тесты.
- Существующие тесты не меняются. Несколько из них закрепляют старое поведение (неповторяемая ошибка → `FAILED`, двусторонний джиттер, `purge` не трогает dead-letter) и будут падать; см. design.md, «Риски».
- Операционно: после выкладки первый `purge_finished` может удалить накопленные ~40 тысяч записей dead-letter старше порога.
