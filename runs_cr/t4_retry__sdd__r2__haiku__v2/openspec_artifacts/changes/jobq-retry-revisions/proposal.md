## Why

Повторы и dead-letter работают месяц (JOBQ-212), и по итогам эксплуатации пересматриваются четыре
договорённости. Неповторяемые ошибки уходят в `FAILED` и выпадают из dead-letter, поэтому их разбирают
по логам. Джиттер расширяет задержку в обе стороны, а SLA почты требует, чтобы повтор не пришёл позже
расчётного времени. `purge_finished` не трогает dead-letter, и там скопилось 40 тысяч записей. Биллинг
присылает `Retry-After`, который сейчас нельзя передать политике повторов. Этот change меняет поведение
по JOBQ-237 и опирается на уже заархивированный `jobq-retry-dead-letter`.

## What Changes

- **Неповторяемые ошибки в dead-letter.** Для типов с действующей политикой повторов неповторяемая
  ошибка (включая `PermanentJobError` и исключения из `non_retryable`) сразу переводит задание в
  `DEAD_LETTERED` без повтора. Если неповторяемая ошибка случилась на последней попытке, причина важнее
  счётчика: запись получает `reason = non_retryable`. Без политики поведение прежнее: `FAILED`.
- **BREAKING (поведение)**: для заданий с политикой повторов `PermanentJobError` и неповторяемые
  исключения больше не дают `FAILED`, а дают `DEAD_LETTERED`. Сигнатуры не меняются.
- **Джиттер только уменьшает задержку.** Множитель `rng.uniform(1 - jitter, 1)`; потолок `max_delay`
  сохраняется. При `jitter == 0` `rng` не используется, как и раньше.
- **`RetryLaterError(JobqError)`** с `retry_after: float` (секунды). Обработчик бросает его, когда внешний
  сервис назвал время следующей попытки. Это обычная временная ошибка: следующая попытка планируется через
  `min(retry_after, max_delay)` секунд. Джиттер и `rng` для неё не используются. `retry_after < 0` (и
  нечисловое или не конечное значение) — `ConfigError`. Если попытки исчерпаны, запись получает
  `reason = exhausted`.
- **`DeadLetterReason`** (`EXHAUSTED = "exhausted"`, `NON_RETRYABLE = "non_retryable"`) и поле
  `DeadLetterEntry.reason`, добавленное последним; по умолчанию `EXHAUSTED`.
- **Очистка dead-letter.** `purge_finished` удаляет и задания в dead-letter, у которых момент попадания
  (`dead_lettered_at`) не позже `now - older_than`; соответствующая запись из `dead_letters()` тоже
  исчезает. **Меняет** требование «dead-letter не очищается».
- **`JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]`** перезапускает все
  записи dead-letter или только записи типа `job_type`, в порядке `dead_letters()`, каждую через
  `requeue_dead_letter`. Пустой результат — пустой список.

## Capabilities

### New Capabilities
- Нет.

### Modified Capabilities
- `job-retry`: решение воркера для неповторяемых ошибок и `RetryLaterError`, джиттер только вниз.
- `dead-letter`: причина попадания (`reason`), очистка по возрасту попадания, массовый перезапуск
  `requeue_all_dead_letters`.

## Impact

- Код: `jobq/errors.py` (`RetryLaterError`), `jobq/models.py` (`DeadLetterReason`, поле `reason`),
  `jobq/retry.py` (джиттер), `jobq/queue.py` (`mark_dead_lettered(..., reason=)`, `purge_finished`,
  `requeue_all_dead_letters`), `jobq/worker.py` (решение по исходам), `jobq/__init__.py` (экспорт),
  `README.md` (раздел о повторах).
- Не трогаем: `jobq/dashboard.py`, `jobq/cli.py`, существующие тесты в `tests/`, зависимости.
- API: сигнатуры существующих методов не меняются. Новые параметры keyword-only или с значениями по
  умолчанию, поэтому старые вызовы работают.
- Тесты: новые тесты добавляются отдельными файлами. Четыре существующих теста описывают прежнее поведение,
  которое этот change отменяет (см. `design.md`, раздел «Конфликт с существующими тестами»).
