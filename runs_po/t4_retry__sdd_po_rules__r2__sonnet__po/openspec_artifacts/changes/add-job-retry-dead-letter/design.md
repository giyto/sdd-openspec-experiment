## Context

Все изменения статуса идут через `JobQueue._transition` по таблице `_TRANSITIONS`; `InMemoryJobStore.due()` выбирает только `PENDING`; отчёт дежурных (`dashboard.py`, не трогаем) перебирает `JobStatus` и берёт `label`, поэтому новые статусы с подписями в модели попадут в него сами. Мотивация — в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:** политика повторов с защитой от переполнения; детерминированный `rng`; все переходы и счётчики через очередь.

**Non-Goals:** персистентность dead-letter, управление повторами из CLI/dashboard, слияние политик по полям, хранение истории прежних попыток в самом задании (она в логах).

## Decisions

- **`RetryPolicy` валидируется в `__post_init__`**, `non_retryable` приводится к tuple через `object.__setattr__` (frozen). Проверки пишутся как «не (допустимо)», чтобы NaN отклонялся с `ConfigError`.
- **`delay_for` без OverflowError:** при `base_delay == 0` → `0.0`; при `factor == 1` → `min(base, max)`; иначе `factor ** (attempt-1)` в `try/except OverflowError` (и проверка на `inf`) → `max_delay`; результат `min(..., max_delay)`. Альтернатива — логарифмы: сложнее и менее точно. Jitter: `rng.uniform(1-j, 1+j)` ровно один раз и только при `jitter > 0`; `rng=None` → модульный `random`. `max_delay` — жёсткий потолок: после умножения на jitter результат снова ограничивается `min(..., max_delay)`, т.е. при превышении ждём ровно `max_delay`.
- **Порядок проверок в воркере:** нет обработчика → `FAILED` до любой политики; затем политика через `queue.retry_policy_for` на момент ошибки; нет политики → `FAILED`; `not is_retryable` → `FAILED`; `attempts >= max_attempts` → dead-letter; иначе retry. `delay_for` вызывается только в последней ветке (требование к `rng`).
- **Новые методы очереди** `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` рядом с `mark_failed`; воркер считает `run_at` по `queue.clock.now()`. Счётчики инкрементируются внутри них, `jobs.requeued` — в `requeue_dead_letter`. Переходы: `RUNNING → RETRY_SCHEDULED/DEAD_LETTERED`, `RETRY_SCHEDULED → RUNNING/CANCELLED`, `DEAD_LETTERED → PENDING` (только requeue, тоже через `_transition`).
- **Dead-letter — список `DeadLetterEntry` в `JobQueue`** (в памяти, как и хранилище); `dead_letters()` отдаёт копию. `requeue` сначала получает задание (`JobNotFoundError`), проверяет статус через `_transition`, затем удаляет запись по `job_id`.
- **`store.due()`** учитывает `PENDING` и `RETRY_SCHEDULED`; порядок `(run_at, seq)` прежний.
- **`is_terminal`:** новые статусы не терминальны, чтобы `purge_finished` не оставлял висячих записей dead-letter. `finished_at` в этих статусах не выставляется.
- **Подписи** — в `_LABELS`; константы счётчиков — в `metrics.py`, докстринг модуля дополняется.

## Risks / Trade-offs

- `is_terminal=False` для `DEAD_LETTERED` меняет смысл «больше не будет выполняться воркером» → уточнить докстринг: ждёт ручного решения.
- `requeue_dead_letter` обнуляет `attempts`: иначе первая же ошибка вернула бы задание в dead-letter. Запись `DeadLetterEntry` хранит `attempts` на момент попадания, прежняя история — в логах (очередь пишет прежний `attempts` в лог при requeue).
- Существующие тесты могут зависеть от набора статусов в `stats()`/отчёте → прогнать весь набор тестов.
- Большие `attempt` во float → явная ветка переполнения и тесты на 5000/10000.
- **Успех после повтора:** `mark_succeeded` обнуляет `error` (требование «Повтор наступил»; инвариант `SUCCEEDED ⇒ error is None` из докстринга `Job`).
