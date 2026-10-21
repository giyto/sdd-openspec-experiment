## Context

Retry-политика (`jobq/retry.py`), исход упавшего задания (`Worker._handle_failure`), dead-letter (`JobQueue._dead_letters`, `mark_dead_lettered`, `requeue_dead_letter`) и `purge_finished` уже реализованы по JOBQ-212. Мотивация и список изменений — в proposal.md. Решения из обсуждения тикета (порядок `requeue_all_dead_letters`, пустой результат, потолок `max_delay` для `Retry-After`, приоритет `non_retryable` на последней попытке, отсутствие джиттера для `RetryLaterError` по UPD от 04.11) приняты как окончательные; более ранняя формулировка тикета «к этой задержке тоже применяем джиттер» отменена.

## Goals / Non-Goals

**Goals:**
- Реализовать поведение из specs без изменения сигнатур существующих публичных методов.
- Держать всю логику выбора исхода в одном месте (`Worker._handle_failure`).

**Non-Goals:**
- Правки `jobq/dashboard.py`, `jobq/cli.py` и существующих тестов; новые зависимости.
- Новые метрики (счётчики `jobs.dead_lettered`, `jobs.requeued`, `jobs.purged` переиспользуются).
- Изменение `RetryPolicy.is_retryable`.

## Decisions

1. **`reason` в `mark_dead_lettered` как необязательный keyword-параметр** (`reason: DeadLetterReason = DeadLetterReason.EXHAUSTED`) и поле `DeadLetterEntry.reason` со значением по умолчанию `EXHAUSTED`. Так старые вызовы и конструирование записи остаются рабочими. Альтернатива — отдельный метод `mark_dead_lettered_non_retryable`: больше поверхности API без выгоды.
2. **Порядок проверок в `_handle_failure`:** нет политики → `FAILED`; неповторяемая → dead-letter `NON_RETRYABLE`; `attempts >= max_attempts` → dead-letter `EXHAUSTED`; иначе повтор. Неповторяемая проверяется раньше счётчика, поэтому на последней попытке причина `NON_RETRYABLE`, а `RetryLaterError` (повторяемая) на последней попытке даёт `EXHAUSTED`. Ветка «нет обработчика» (`UnknownJobTypeError`) остаётся до этой логики и даёт `FAILED`.
3. **Джиттер:** в `RetryPolicy.delay_for` заменить `uniform(1 - jitter, 1 + jitter)` на `uniform(1 - jitter, 1)`. Итоговое ограничение `min(max(delay, 0), max_delay)` оставить как защиту: при множителе ≤ 1 оно уже выполняется, но дёшево и защищает от нестандартного `rng`.
4. **`RetryLaterError`:** значение валидируется в `__init__` (число, не bool, конечное, `>= 0`, иначе `ConfigError`), хранится как `float`; `message` передаётся в `super().__init__`. Воркер при `isinstance(exc, RetryLaterError)` считает `delay = min(exc.retry_after, policy.max_delay)` и не вызывает `delay_for` и `rng`. Для расчёта потолка новый публичный метод политики не нужен. Альтернатива — параметр `delay_for(attempt, rng, retry_after=...)` — меняет сигнатуру существующего метода, отвергнуто.
5. **`purge_finished`:** после прохода по завершённым заданиям пройти по `_dead_letters` и для записей с `dead_lettered_at <= cutoff` удалить задание из хранилища (`store.remove`) и запись из словаря. Счётчик и возвращаемое значение суммируются, `JOBS_PURGED` увеличивается один раз на общее число. Записи итерировать по копии списка значений.
6. **`requeue_all_dead_letters`:** взять снимок `dead_letters()`, отфильтровать по `job_type` (если не `None`), для каждой записи вызвать `requeue_dead_letter(entry.job_id)` и собрать результаты. Повторное использование метода гарантирует идентичное поведение и метрики; порядок задаётся снимком. Атомарность не требуется: все задания по построению в `DEAD_LETTERED`, ошибки невозможны.
7. **Экспорт:** если `jobq/__init__.py` экспортирует модели и ошибки, добавить `DeadLetterReason` и `RetryLaterError` в тот же список.

## Допущения

- `RetryLaterError` без политики типа даёт `FAILED` (правило 1 действует для любой ошибки).
- `RetryLaterError` подчиняется обычной классификации: если её класс попадает под `non_retryable`, она неповторяемая и идёт в dead-letter с `NON_RETRYABLE`. Обратное в тикете не оговорено, изменений `is_retryable` не требуется.
- Нечисловой/нефинитный `retry_after` — тоже ошибка конфигурации (`ConfigError`), по аналогии с валидацией `RetryPolicy`; `retry_after == 0` допустим.
- `purge_finished` удаляет задание из dead-letter целиком (из хранилища), иначе остался бы «осиротевший» `DEAD_LETTERED` без записи. Возвращаемое число и `jobs.purged` включают такие задания.
- Граница возраста включительная (`<=`), как для завершённых заданий.
- `requeue_all_dead_letters` с `job_type`, не совпадающим ни с одним типом (в т.ч. пустой строкой), возвращает `[]`; `None` означает «все типы».

## Risks / Trade-offs

- [Существующие тесты JOBQ-212 фиксируют прежнее поведение (неповторяемая → `FAILED`, `uniform(1 - j, 1 + j)`, purge не трогает dead-letter) и перестанут проходить] → тикет запрещает их менять; при реализации не править их, а явно сообщить, какие тесты расходятся с новыми требованиями, и добавить новые тесты в отдельный файл.
- [Потеря заданий через purge: dead-letter больше не хранится вечно] → намеренно по тикету; оператор выбирает `older_than`. `purge_finished()` без аргумента (`older_than=0`) очистит весь dead-letter.
- [Раздел основной спецификации «Готовность заданий и обратная совместимость» утверждает, что поведение `purge_finished` не меняется] → в части dead-letter он вытесняется данным изменением; остальные вызовы совместимы.
- [Требование «DEAD_LETTERED → PENDING только через `requeue_dead_letter`»] → `requeue_all_dead_letters` делегирует ему, нарушения нет.

## Migration Plan

Миграции данных нет (in-memory хранилище). Откат — возврат коммита. Потребителям сообщить о трёх изменениях поведения из proposal (**BREAKING**).

## Результаты реализации

- Старые тесты JOBQ-212 не правились. Расходятся с новыми требованиями (5 шт., все в `tests/test_retry.py`): `test_jitter_does_not_break_ceiling` и `test_rng_used_once_per_retry` (диапазон `uniform(1 - j, 1 + j)`), `test_purge_keeps_new_statuses` (purge теперь удаляет dead-letter), `test_non_retryable_on_last_attempt_fails[<lambda>0/1]` (неповторяемая ошибка теперь даёт `DEAD_LETTERED`, а не `FAILED`). Их нужно обновить отдельным решением владельцев тикета.
- Новые тесты лежат в `tests/test_retry_rework.py`; `jobq/dashboard.py` и `jobq/cli.py` не изменены.
