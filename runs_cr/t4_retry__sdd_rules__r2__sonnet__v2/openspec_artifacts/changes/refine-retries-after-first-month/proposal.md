## Why

Месяц эксплуатации повторов и dead-letter (JOBQ-212) показал, что часть договорённостей не работает: задания с неповторяемыми ошибками теряются в `FAILED` и их ищут по логам, джиттер нарушает SLA почты (повтор приходит позже расчётного времени), dead-letter разросся до 40 тысяч записей без способа очистки, а внешний сервис (биллинг) сам называет время повтора, которое политика не учитывает. JOBQ-237 пересматривает эти решения.

## What Changes

- **BREAKING** Неповторяемая ошибка обработчика (включая `PermanentJobError`) для типа, на который действует политика повторов, отправляет задание в dead-letter без повторов, а не в `FAILED`. Без политики поведение прежнее (`FAILED`). Ошибка отсутствия обработчика (`UnknownJobTypeError`) по-прежнему даёт `FAILED`.
- **BREAKING** Джиттер только уменьшает задержку: множитель `rng.uniform(1 - jitter, 1)`; задержка никогда не больше расчётной.
- **BREAKING** `purge_finished` дополнительно удаляет задания из dead-letter по тому же правилу возраста, считая от `dead_lettered_at`; соответствующая запись исчезает из `dead_letters()`.
- Новый `DeadLetterReason(str, Enum)` в `jobq/models.py` со значениями `EXHAUSTED = "exhausted"` и `NON_RETRYABLE = "non_retryable"`; новое последнее поле `DeadLetterEntry.reason: DeadLetterReason`.
- Новое исключение `RetryLaterError(JobqError)` в `jobq/errors.py`: `__init__(self, message: str = "", *, retry_after: float)`, атрибут `retry_after: float` (секунды); `retry_after < 0` — `ConfigError`. Это обычная повторяемая ошибка, но следующая попытка планируется через `retry_after` секунд, ограниченных `max_delay`, без джиттера и без обращения к `rng`.
- Новый метод `JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]` в `jobq/queue.py`: перезапускает все (или только заданного типа) задания из dead-letter в порядке `dead_letters()`, каждое как `requeue_dead_letter`; если перезапускать нечего — `[]`.
- Выбор `reason`: неповторяемая ошибка всегда `non_retryable` (в том числе на последней попытке); исчерпание попыток, в том числе при `RetryLaterError` на последней попытке, — `exhausted`.

## Capabilities

### New Capabilities

### Modified Capabilities
- `retry-policy`: джиттер только уменьшает задержку; добавляется `RetryLaterError` с валидацией `retry_after`.
- `job-retry-execution`: неповторяемая ошибка → dead-letter при действующей политике; планирование повтора по `RetryLaterError`; экспорт новых имён.
- `dead-letter-queue`: поле `reason` и `DeadLetterReason`; очистка затрагивает dead-letter; `requeue_all_dead_letters`; метрики.

## Impact

- Код: `jobq/errors.py`, `jobq/models.py`, `jobq/retry.py`, `jobq/queue.py`, `jobq/worker.py`, `jobq/__init__.py`, `README.md` (раздел «Повторы и dead-letter»).
- Не меняются: `jobq/dashboard.py`, `jobq/cli.py`, сигнатуры существующих публичных методов, зависимости.
- Существующие тесты, закрепляющие отменяемое поведение (`FAILED` для неповторяемых ошибок, `purge_finished` не трогает dead-letter, двусторонний джиттер `uniform(1 - jitter, 1 + jitter)`), по условию задачи не редактируются и после реализации ожидаемо упадут; см. design.md, «Риски».
