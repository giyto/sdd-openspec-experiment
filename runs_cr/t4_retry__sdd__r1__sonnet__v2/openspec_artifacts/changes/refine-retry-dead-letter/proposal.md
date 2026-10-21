## Why

Месяц эксплуатации повторов и dead-letter (JOBQ-212) показал, что часть договорённостей не работает: задания с кривыми данными исчезают в `FAILED` и их ищут по логам, джиттер ломает SLA почты, а dead-letter разросся до 40 тысяч записей без способа очистки. Биллинг также сам сообщает время повтора (Retry-After), а массово вернуть записи из dead-letter нечем.

## What Changes

- **BREAKING** Неповторяемая ошибка (включая `PermanentJobError`) при действующей политике больше не ведёт в `FAILED`, а сразу переводит задание в `DEAD_LETTERED`, без повторов и на любой попытке.
- **BREAKING** Джиттер только уменьшает задержку: множитель `rng.uniform(1 - jitter, 1)` вместо `rng.uniform(1 - jitter, 1 + jitter)`.
- **BREAKING** `purge_finished` удаляет и задания из dead-letter по тому же правилу возраста, считая от `dead_lettered_at`; запись из `dead_letters()` исчезает вместе с заданием.
- Новое поле `DeadLetterEntry.reason: DeadLetterReason` (`exhausted` / `non_retryable`), последним в dataclass.
- Новая ошибка `RetryLaterError(message="", *, retry_after)`: временная ошибка, следующая попытка через `retry_after` секунд (с потолком `max_delay`, без джиттера, `rng` не трогается). `retry_after < 0` — `ConfigError`.
- Новый метод `JobQueue.requeue_all_dead_letters(job_type=None) -> list[Job]`.
- Не меняются: `jobq/dashboard.py`, `jobq/cli.py`, сигнатуры существующих публичных методов, зависимости.

## Capabilities

### New Capabilities

### Modified Capabilities
- `job-retry-dead-letter`: маршрутизация неповторяемых ошибок в dead-letter с причиной, `RetryLaterError`, правило `rng`, очистка dead-letter через `purge_finished`, массовый возврат.
- `retry-policy`: джиттер только уменьшает задержку.

## Impact

- Код: `jobq/models.py`, `jobq/errors.py`, `jobq/retry.py`, `jobq/queue.py`, `jobq/worker.py`, `jobq/__init__.py` (экспорт), `README.md`.
- Тесты: старые тесты, закрепляющие заменённое поведение, противоречат новым требованиям (см. design.md, «Конфликт с ограничением по тестам»).
- Метрики: `jobs.dead_lettered` теперь растёт и для неповторяемых ошибок, `jobs.failed` для них не растёт; `jobs.purged` учитывает удалённые dead-letter.
