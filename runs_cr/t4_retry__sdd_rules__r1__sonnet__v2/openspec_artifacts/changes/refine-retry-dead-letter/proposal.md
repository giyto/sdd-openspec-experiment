## Why

Месяц эксплуатации повторов и dead-letter (JOBQ-212) показал проблемы: задания с неповторяемой ошибкой (почти всегда кривые данные) падают в `FAILED` и потом ищутся по логам; джиттер в большую сторону нарушает SLA почты (повтор не позже расчётного времени); dead-letter не чистится и накопил 40 тысяч записей; у биллинга есть собственный Retry-After, который политика не учитывает (JOBQ-237).

## What Changes

- **Неповторяемые ошибки** (в том числе `PermanentJobError`) для типов с действующей политикой сразу отправляют задание в dead-letter, без повторов, на любой попытке. Без политики поведение прежнее: `FAILED`. Отсутствие обработчика по-прежнему даёт `FAILED`. **BREAKING** относительно JOBQ-212.
- **Джиттер** только уменьшает задержку: множитель `rng.uniform(1 - jitter, 1)`. **BREAKING** для `RetryPolicy.delay_for`.
- **Очистка**: `purge_finished` удаляет и задания в `DEAD_LETTERED` по тому же правилу возраста, считая от `dead_lettered_at`; запись пропадает и из `dead_letters()`. **BREAKING** относительно JOBQ-212.
- `jobq/models.py`: `DeadLetterReason(str, Enum)` со значениями `EXHAUSTED = "exhausted"`, `NON_RETRYABLE = "non_retryable"`; в `DeadLetterEntry` новое последнее поле `reason: DeadLetterReason`.
- `jobq/errors.py`: `RetryLaterError(JobqError)` с `__init__(self, message: str = "", *, retry_after: float) -> None` и атрибутом `retry_after: float` (секунды). `retry_after < 0` даёт `ConfigError`.
- Обработка `RetryLaterError`: обычная временная ошибка, но следующая попытка планируется через `retry_after` секунд вместо задержки из политики, с потолком `max_delay`. Джиттер не применяется, `rng` не используется (UPD тимлида от 04.11 отменяет формулировку описания тикета про джиттер). На последней попытке — обычное исчерпание, `exhausted`.
- `jobq/queue.py`: `JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]`.
- Неповторяемая ошибка на последней попытке получает причину `non_retryable`, а не `exhausted`.
- Вне границ: `jobq/dashboard.py`, `jobq/cli.py`, новые зависимости. Сигнатуры существующих публичных методов не меняются.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities
- `retry-policy`: расчёт задержки (джиттер только вниз); новая `RetryLaterError`.
- `job-retry-handling`: исход падения обработчика, использование rng, dead-letter очередь (причина, очистка, массовый requeue).

## Impact

- Код: `jobq/errors.py`, `jobq/models.py`, `jobq/retry.py`, `jobq/queue.py` (`mark_dead_lettered` получает keyword-only `reason` со значением по умолчанию `EXHAUSTED`, `purge_finished`, `requeue_all_dead_letters`), `jobq/worker.py`, `jobq/__init__.py` (экспорт `DeadLetterReason`, `RetryLaterError`), тесты.
- Существующие тесты `test_purge_keeps_dead_letter`, `test_non_retryable_on_last_attempt`, `test_jitter_capped`, `test_jitter_applied_once` и ветка `y` в `test_rng_usage` проверяют заменённое поведение JOBQ-212 и противоречат тикету; их придётся обновить. Остальные существующие тесты остаются без изменений.
- Операционно: после выкатки задания с неповторяемыми ошибками появляются в dead-letter, а не в `FAILED`; `jobs.failed` для них не растёт, `jobs.dead_lettered` растёт.

## Допущения

- Конфликт ограничений: «существующие тесты не меняем» противоречит самому тикету (см. Impact). Приоритет у поведения тикета; меняются только перечисленные тесты, и только в части заменённого поведения.
- `RetryLaterError` классифицируется `is_retryable` по обычным правилам (если пользователь внёс её суперкласс в `non_retryable`, она неповторяемая); `is_retryable` не меняется.
- `retry_after` — число (не `bool`); `NaN`, нечисловые и отрицательные значения дают `ConfigError` при создании исключения; `inf` допустим и срезается до `max_delay`.
- `RetryLaterError` без политики даёт `FAILED`, как любая ошибка.
- Вызовы `mark_dead_lettered(job_id, error)` продолжают работать, причина по умолчанию `exhausted`; у `DeadLetterEntry.reason` значение по умолчанию `EXHAUSTED` ради совместимости построения записи без него.
- `purge_finished` включает удалённые dead-letter задания в возвращаемое число и в счётчик `jobs.purged`.
- Пустая строка в `job_type` у `requeue_all_dead_letters` даёт `ConfigError` (как в остальных методах очереди); `None` — все записи.
- Потолок `max_delay` берётся из политики, действующей в момент ошибки.
