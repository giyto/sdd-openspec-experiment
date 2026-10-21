## Why

После месяца эксплуатации повторов и dead-letter (JOBQ-212) дежурные и биллинг собрали претензии: неповторяемые ошибки теряются мимо dead-letter, джиттер может сдвинуть повтор позже расчётного времени (нарушает SLA почты), в dead-letter накопилось около 40 тысяч записей без способа очистки, а массовый возврат и учёт `Retry-After` внешних сервисов не поддержаны.

## What Changes

- **BREAKING** Неповторяемая ошибка (включая `PermanentJobError`) для типа с действующей политикой повторов сразу отправляет задание в `DEAD_LETTERED` (без повторов), а не в `FAILED`. Без политики поведение прежнее (`FAILED`).
- **BREAKING** Джиттер только уменьшает задержку: множитель `rng.uniform(1 - jitter, 1)` вместо `rng.uniform(1 - jitter, 1 + jitter)`.
- **BREAKING** `purge_finished` дополнительно удаляет задания из dead-letter по тому же правилу возраста, считая от `dead_lettered_at`; запись из `dead_letters()` исчезает.
- Добавляется `jobq.models.DeadLetterReason(str, Enum)` со значениями `EXHAUSTED = "exhausted"` и `NON_RETRYABLE = "non_retryable"` и последнее поле `DeadLetterEntry.reason: DeadLetterReason`.
- Добавляется `jobq.errors.RetryLaterError(JobqError)` с `__init__(self, message: str = "", *, retry_after: float)` и атрибутом `retry_after: float` (секунды). Следующая попытка планируется через `retry_after` секунд вместо задержки политики; потолок `max_delay` действует, джиттер и `rng` не используются (решение от 04.11 отменяет первоначальное описание тикета). `retry_after < 0` — `ConfigError`.
- Добавляется `JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]`.
- Не меняются `jobq/dashboard.py`, `jobq/cli.py`, сигнатуры существующих публичных методов, существующие тесты; новых зависимостей нет.

## Capabilities

### New Capabilities

### Modified Capabilities
- `job-retry-policy`: расчёт задержки с односторонним джиттером; исход упавшего задания (неповторяемая ошибка → dead-letter, причина, `RetryLaterError`); новое требование про `RetryLaterError`.
- `dead-letter-queue`: поле `reason` в записях; `purge_finished` очищает dead-letter; массовый возврат `requeue_all_dead_letters`.

## Impact

- Код: `jobq/models.py`, `jobq/errors.py`, `jobq/retry.py`, `jobq/queue.py`, `jobq/worker.py`, `jobq/__init__.py` (экспорт новых имён, если пакет экспортирует остальные).
- Поведение: пункты **BREAKING** затрагивают потребителей, полагавшихся на `FAILED` для неповторяемых ошибок, на двусторонний джиттер и на сохранность dead-letter при `purge_finished`.
- Существующие тесты, закрепляющие прежние договорённости JOBQ-212, прямо противоречат новым требованиям; по ограничению тикета они не редактируются, расхождение описано в design.md.
- Зависимости: без изменений.
