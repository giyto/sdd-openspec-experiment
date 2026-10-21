## Context

Повторы и dead-letter реализованы в `jobq/worker.py` (`_handle_failure`), `jobq/queue.py` (`mark_*`, `purge_finished`, `requeue_dead_letter`, словарь `_dead_letters`), `jobq/retry.py` (`delay_for`, `is_retryable`) и `jobq/models.py` (`DeadLetterEntry`). Запись dead-letter хранится отдельно от задания в `JobQueue._dead_letters`. `dashboard.py` и `cli.py` не затрагиваются.

## Goals / Non-Goals

**Goals:**
- Неповторяемые ошибки при действующей политике попадают в dead-letter с причиной.
- Джиттер только уменьшает задержку.
- `purge_finished` чистит dead-letter по возрасту от `dead_lettered_at`.
- `RetryLaterError` и `requeue_all_dead_letters`.

**Non-Goals:**
- Изменения `dashboard.py`, `cli.py`, существующих сигнатур, зависимостей.
- Поведение без политики (остаётся `FAILED`) и отсутствие обработчика (остаётся `FAILED`).
- Отдельная очистка только dead-letter, новые метрики, персистентность.

## Decisions

1. **Порядок решений в `_handle_failure`**: нет политики → `FAILED`; `not is_retryable` → dead-letter `NON_RETRYABLE`; `attempts >= max_attempts` → dead-letter `EXHAUSTED`; иначе повтор. Это даёт требуемое: неповторяемая на последней попытке — `non_retryable`, `RetryLaterError` на последней — `exhausted`. Альтернатива «причина по счётчику» отвергнута тимлидом.
2. **Причина через `mark_dead_lettered(job_id, error, reason=DeadLetterReason.EXHAUSTED)`**: keyword-параметр с умолчанием сохраняет совместимость старых вызовов. `DeadLetterEntry.reason` последний, с умолчанием `EXHAUSTED` (старые 5-аргументные конструкторы работают). `DeadLetterReason(str, Enum)` в `models.py`, экспорт из `jobq/__init__.py`.
3. **Джиттер**: в `RetryPolicy.delay_for` заменить верхнюю границу на 1: `uniform(1 - jitter, 1)`. Финальный зажим `[0, max_delay]` оставить (дёшево и защищает от стаб-генераторов). Один вызов `uniform` на расчёт сохраняется.
4. **`RetryLaterError`** в `jobq/errors.py`, наследник `JobqError`; проверка `retry_after` в `__init__` (`< 0` или NaN → `ConfigError`), `message` передаётся в `super().__init__`. Бесконечный `retry_after` допустим: потолок `max_delay` его срежет. Задержка считается в воркере: `min(exc.retry_after, policy.max_delay)`, минуя `delay_for`, поэтому `rng` не вызывается. Повторяемость определяется обычным `is_retryable`.
5. **`purge_finished`**: для `DEAD_LETTERED` брать `dead_lettered_at` из `_dead_letters[job.id]`, сравнивать с `cutoff`, при удалении убирать задание из хранилища и запись из `_dead_letters`; учитывать в `removed` и `jobs.purged`. Если записи нет (рассинхрон), задание пропускается.
6. **`requeue_all_dead_letters(job_type=None)`**: взять снимок `dead_letters()`, отфильтровать по типу, для каждого вызвать `requeue_dead_letter`; вернуть список заданий в том же порядке. Пустой результат — `[]`. `job_type=""` не считается ошибкой и просто ничего не совпадёт.
7. **Конфликт с ограничением по тестам.** Ограничение «существующие тесты не меняем» несовместимо с тремя явно пересмотренными договорённостями: старые тесты в `tests/test_retry.py` закрепляют `FAILED` для неповторяемых ошибок (`test_non_retryable_on_last_attempt`, проверка с `non_retryable=(ValueError,)` на ~стр. 195, `rng`-тест на ~стр. 350), джиттер `1 + jitter` (`test_jitter_stub`, `test_jitter_capped`) и «purge не трогает dead-letter» (`test_requeue_errors_and_purge`). Решение: при реализации менять только эти тесты, и только в части заменённого требования (ожидаемые значения), остальные не трогать; точный список зафиксировать в итоговом отчёте. Если команда настаивает на неизменности, эти тесты останутся красными, и это надо явно признать, а не обходить кодом.

## Risks / Trade-offs

- `purge_finished()` с `older_than=0` по умолчанию теперь удаляет весь dead-letter сразу. Это прямое следствие «тем же правилом возраста»; вызывающим стоит передавать ненулевой возраст. Отмечено в README.
- Записи dead-letter, удалённые purge, нельзя вернуть — потеря данных для разбора; принято тикетом.
- `jobs.failed` для неповторяемых ошибок под политикой перестанет расти; дашборды/алерты на `jobs.failed` могут занижать проблемы — стоит смотреть и `jobs.dead_lettered`.
- Задание, чей класс ошибки одновременно `RetryLaterError` и в `non_retryable`, уйдёт в dead-letter (допущение: классификация первична).
- Допущения: `jobs.purged` включает dead-letter; `retry_after=inf` не отвергается.

## Решения при реализации

- Сценарий «Джиттер не пробивает потолок» требует, чтобы стаб со значением > 1 не увеличивал задержку, поэтому множитель дополнительно ограничен сверху единицей: `min(rng.uniform(1 - jitter, 1), 1.0)`. Вызов `uniform` по-прежнему один, с аргументами `(1 - jitter, 1)`.
- Изменённые старые тесты (`tests/test_retry.py`): `test_jitter_stub` (аргументы `(0.5, 1)`), `test_requeue_errors_and_purge` (purge теперь удаляет dead-letter), `test_non_retryable_on_last_attempt` (теперь `DEAD_LETTERED`, `non_retryable`). `test_jitter_capped` и rng-тесты остались зелёными без правок. Новые тесты — `tests/test_refine_retry.py`.
