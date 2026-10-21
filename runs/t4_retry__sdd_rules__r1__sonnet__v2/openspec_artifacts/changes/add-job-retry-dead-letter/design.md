## Context

Все смены статуса идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; `InMemoryJobStore.due` выбирает только `PENDING`; `purge_finished` удаляет задания по `is_terminal`; `render_report` и `stats()` перечисляют `JobStatus`, а подписи берут из `JobStatus.label`. Поэтому новые статусы попадают в отчёт без правок `dashboard.py`. Мотивация и границы — в proposal.md.

## Goals / Non-Goals

**Goals:**
- Повторы и dead-letter без изменения поведения при отсутствии политики.
- Вся логика выбора исхода в одном месте, переходы только через `_transition`.

**Non-Goals:**
- Персистентность dead-letter, правки `dashboard.py` и `cli.py`, асинхронный воркер.

## Decisions

1. **Таблица переходов.** `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`; `RETRY_SCHEDULED → {RUNNING, CANCELLED}`; `DEAD_LETTERED → {PENDING}` (только через `requeue_dead_letter`, `cancel` туда не ходит, потому что `cancel` целится в `CANCELLED`). Альтернатива «отдельный флаг на `Job`» отвергнута: ломает единый механизм статусов.
2. **Выборка готовых.** `store.due` берёт `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка `(run_at, seq)` прежняя.
3. **`is_terminal`.** `RETRY_SCHEDULED` и `DEAD_LETTERED` не входят в `_TERMINAL`, поэтому `purge_finished` их не трогает без изменения кода purge. Docstring `is_terminal` («больше не будет выполняться воркером») уточнить: dead-letter ждёт осознанного requeue.
4. **Dead-letter хранилище.** `DeadLetterEntry` хранится списком в `JobQueue` (порядок попадания); `dead_letters()` отдаёт копию. `requeue_dead_letter` ищет и удаляет запись по `job_id`. Задание остаётся в сторе тем же объектом. Альтернатива «вычислять из сторе по статусу» отвергнута: теряется порядок попадания.
5. **Методы очереди для воркера.** `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` по образцу `mark_failed`: переход, `job.error`, счётчик, запись. `finished_at` не ставится (задание не завершено). `requeue_dead_letter` обнуляет `attempts`, `error`, `started_at`, `finished_at`, ставит `run_at = now`.
6. **Логика исхода в воркере.** После перехвата `Exception`: `policy = queue.retry_policy_for(job.job_type)` (в момент ошибки); `None` или `not policy.is_retryable(exc)` → `mark_failed`; `job.attempts >= policy.max_attempts` → `mark_dead_lettered`; иначе `delay = policy.delay_for(job.attempts, rng)` и `mark_retry_scheduled(run_at=clock.now()+delay)`. Задержка считается только в последней ветке, поэтому `rng` трогается только при реальном повторе. Ветка `UnknownJobTypeError` остаётся прежней (`FAILED`). Воркер хранит `rng`; при `None` каждый вызов `delay_for` получает `None`, а `delay_for` создаёт локальный источник.
7. **`delay_for` без переполнения.** Если `base_delay == 0` → 0. Иначе считать в логарифмах или через ограниченный цикл/`try pow except OverflowError` → `max_delay`; при `factor == 1` — `base_delay`. Затем `min(..., max_delay)`, при `jitter > 0` умножение на `rng.uniform(1-jitter, 1+jitter)` и повторный `min(..., max_delay)` и `max(..., 0.0)`. Один вызов `uniform` на задержку.
8. **Валидация.** `__post_init__` фрозен-dataclass: `object.__setattr__` для приведения `non_retryable` к `tuple`; проверки, включая `NaN` (сравнения с `NaN` ложны, поэтому проверять инвертированно: `not (x >= 0)`), поднимают `ConfigError`. `bool` для `max_attempts` не особо обрабатывается; нецелый `max_attempts` — `ConfigError`.
9. **Метрики.** Добавить константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`; обновить docstring модуля.
10. **Экспорт.** `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` добавить в `jobq/__init__.py`.
11. **Валидация в очереди.** `default_retry_policy` и `set_retry_policy` принимают `RetryPolicy | None`, иначе `ConfigError`.

## Risks / Trade-offs

- [Потребители, перечисляющие `JobStatus`, увидят новые статусы] → Это ожидаемо; существующие тесты не фиксируют полный набор — проверить прогоном.
- [`failure_rate` в `dashboard.py` не учитывает dead-letter] → Файл не наш; отметить владельцам.
- [Пропавшая история `attempts` после requeue] → По решению тимлида; количество попыток видно в логах, поэтому логировать requeue с прежним `attempts`.
- [Запись dead-letter может разойтись со сторе, если задание удалят снаружи] → `purge_finished` не удаляет `DEAD_LETTERED`; прямое `store.remove` вне контракта.

## Решения при реализации

- `retry_policy_for("")` тоже даёт `ConfigError` (как `set_retry_policy`), чтобы пустой `job_type` отвергался единообразно.
- `RetryPolicy`: `max_attempts` должен быть `int` (не `bool`), числовые поля — `Real` (не `bool`), иначе `ConfigError`; `delay_for` с нецелым или `bool` `attempt` — `ConfigError`.
- Переполнение в `delay_for` ловится через `OverflowError` → `inf`, затем ограничивается `max_delay`.
- `requeue_dead_letter` дополнительно сбрасывает `started_at` и `finished_at`; прежнее значение `attempts` пишется в лог.
