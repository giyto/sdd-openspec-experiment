## Context

Сейчас `Worker.run_once` на любое `Exception` вызывает `queue.mark_failed`. Все смены статуса идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; `InMemoryJobStore.due` выбирает только `PENDING`; `Metrics` увеличивает счётчик в момент перехода. Отчёт (`dashboard.render_report`) обходит все `JobStatus` и берёт подписи из `JobStatus.label`, поэтому новые статусы появятся в нём без правок `dashboard.py` (он и `cli.py` вне зоны изменений). Мотивацию см. в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:**
- Политика повторов как чистый объект без состояния; решение «FAILED / повтор / dead-letter» в одном месте (воркер), состояние и переходы — в очереди.
- Полная обратная совместимость при отсутствии политик.

**Non-Goals:**
- Персистентность dead-letter (хранилище только в памяти), автоматический requeue, отдельные метрики по типам, изменения `dashboard.py`/`cli.py`.
- Отдельный раздел отчёта со списком dead-letter.

## Decisions

1. **`RetryPolicy` — frozen dataclass с `__post_init__`-валидацией.** `non_retryable` нормализуется в tuple через `object.__setattr__`. Все ошибки — `ConfigError` (в проекте встроенные исключения наружу не выпускаются). Дополнительно (допущение) отклоняем NaN/inf и не-числа/`bool`, иначе сравнения молча проходят.
2. **`delay_for` без переполнения.** `factor == 1` или `base_delay == 0` → без возведения в степень (`base_delay` / `0`). Иначе `base_delay * factor ** (attempt - 1)` в `try/except OverflowError` → `max_delay` (при `factor >= 1`, `base_delay > 0` переполнение означает значение заведомо выше любого конечного `max_delay`). Затем `min(..., max_delay)`, затем джиттер (`rng.uniform` ровно один раз, только при `jitter > 0`) и финальное ограничение `min(delay * uniform, max_delay)`: `max_delay` — жёсткий потолок, результат всегда в диапазоне `[0, max_delay]`. Без `rng` — модульный `random`. Альтернатива (логарифмы) сложнее и менее точна.
3. **Решение принимает воркер, очередь даёт примитивы.** В `JobQueue` добавляются `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` (по образцу `mark_failed`), `mark_failed` не меняется. Воркер: нет политики → `mark_failed`; `not is_retryable` → `mark_failed`; `attempts >= max_attempts` → `mark_dead_lettered`; иначе `delay_for(job.attempts, rng)` и `mark_retry_scheduled(run_at=clock.now()+delay)`. Это гарантирует порядок «rng трогаем только при реальном повторе» и использование политики на момент ошибки (`retry_policy_for` вызывается в обработчике ошибки). Ветка «нет обработчика» остаётся `mark_failed` до любой логики политик.
4. **Переходы:** `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`; `RETRY_SCHEDULED → {RUNNING, CANCELLED}`; `DEAD_LETTERED → {PENDING}` (только через `requeue_dead_letter`, поэтому `cancel` туда запрещён). `cancel` для `RETRY_SCHEDULED` разрешён (допущение: задание ещё не выполняется, как `PENDING`).
5. **Выборка:** `InMemoryJobStore.due` включает `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`.
6. **Dead-letter хранится в очереди** как список `DeadLetterEntry` (frozen) в порядке добавления; `dead_letters()` отдаёт копию; `requeue_dead_letter` ищет запись по `job_id` (отсутствие job → `JobNotFoundError` из хранилища, не в dead-letter → `InvalidTransitionError` через `_transition`), удаляет запись, меняет статус на `PENDING`, `run_at = now`, `error = None`, `finished_at = None`, счётчик `jobs.requeued`. `attempts` сбрасывается в `0`: после ручного возврата у задания снова полный набор попыток, как у нового. История прежних попыток остаётся в логах (в `attempts` не сохраняется); `DeadLetterEntry.attempts` фиксирует число попыток на момент попадания в dead-letter.
7. **`error` и `finished_at`.** `mark_succeeded` обнуляет `error` (инвариант модели: у `SUCCEEDED` `error is None`, а после повторов там лежит прошлая ошибка). `RETRY_SCHEDULED` не ставит `finished_at`; `DEAD_LETTERED` ставит.
8. **`DEAD_LETTERED` терминален для воркера (`is_terminal=True`), но `purge_finished` пропускает его**, чтобы запись dead-letter не осталась «висячей». `RETRY_SCHEDULED` нетерминален.
9. **Метрики:** константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`; инкремент внутри соответствующих `mark_*`/`requeue_*` сразу после перехода. Обновить docstring `metrics.py`.
10. **Экспорт и документация:** `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`; раздел в README.

## Risks / Trade-offs

- [После возврата из dead-letter `attempts` обнуляется, поэтому «упорное» задание может раз за разом получать полный набор попыток] → осознанное решение владельца продукта; возвраты ручные и учитываются счётчиком `jobs.requeued`, история попыток — в логах.
- [`stats()` и отчёт получают две новые строки; внешние потребители с жёстким набором ключей могут удивиться] → ожидаемо для новых статусов; существующие тесты проверяют набор ключей через `JobStatus`.
- [`failure_rate` не учитывает `DEAD_LETTERED`] → `dashboard.py` не трогаем; отметить владельцам отчёта.
- [Блок «Последние ошибки» в отчёте показывает только `FAILED`] → то же ограничение, вне зоны.

## Допущения

- `cancel` для `RETRY_SCHEDULED` разрешён, для `DEAD_LETTERED` — нет.
- Джиттер может уменьшить задержку, но не увеличить её выше `max_delay` (при превышении ждём ровно `max_delay`).
- Без `rng` используется модульный `random`; при `Worker(rng=None)` поведение то же.
- `set_retry_policy`/конструктор проверяют тип политики и непустой `job_type` (`ConfigError`).
- Задание, у которого политика пропала между попытками, при следующем падении идёт в `FAILED`.
