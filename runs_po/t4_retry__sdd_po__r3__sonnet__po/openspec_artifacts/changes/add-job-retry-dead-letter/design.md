## Context

Сейчас воркер (`jobq/worker.py`) при любом `Exception` вызывает `queue.mark_failed`. Статусы меняются только через `JobQueue._transition` по таблице `_TRANSITIONS`; `InMemoryJobStore.due()` отдаёт только `PENDING`; `dashboard.render_report` перебирает все `JobStatus` и берёт подписи из `JobStatus.label`, поэтому новые статусы появятся в отчёте без правок `dashboard.py` (он закрыт для нас). Требования — в `specs/job-retry` и `specs/dead-letter`, мотивация — в `proposal.md`.

## Goals / Non-Goals

**Goals:**
- Вся логика решения «FAILED / повтор / dead-letter» в одном месте (воркер), вся смена статусов — в очереди.
- `delay_for` без `OverflowError` для любого `attempt`.

**Non-Goals:**
- Персистентность dead-letter (хранилище только в памяти), правки `dashboard.py`/`cli.py`, учёт новых статусов в `failure_rate`.
- Автоматическое возобновление из dead-letter.

## Decisions

1. **`RetryPolicy` — frozen dataclass с валидацией в `__post_init__`**; `non_retryable` нормализуется через `object.__setattr__(self, "non_retryable", tuple(...))`. Проверки записаны в форме «не (допустимо)», чтобы NaN отвергался. Элемент валиден, если `isinstance(x, type) and issubclass(x, BaseException)`. Ошибки — `ConfigError`. Тип `max_attempts` должен быть `int` (не `bool`).
2. **Устойчивый `delay_for`.** Порядок: проверить `attempt >= 1`; если `base_delay == 0` — база `0.0`; иначе считать `base_delay * factor ** (attempt - 1)` в `try`, при `OverflowError` брать `max_delay`; затем `min(.., max_delay)`. При `factor == 1` степень не считается. Для `int`-фактора степень приводить к `float` внутри `try`, чтобы огромный `int` не падал при умножении. Только после ограничения применяется jitter, результат снова ограничивается: `min(delay * rng.uniform(1 - jitter, 1 + jitter), max_delay)` — `max_delay` жёсткий потолок и для jitter; при `jitter == 0` `rng` не трогается; при `rng is None` берётся модульный `random`. Альтернатива (ограничивать `attempt` заранее) отвергнута: зависит от `factor`.
3. **Решение принимает воркер, смену статуса — очередь.** В очереди появляются `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)`; каждая делает `_transition`, пишет `error`, увеличивает свой счётчик (`jobs.retried` / `jobs.dead_lettered`) и, для dead-letter, добавляет `DeadLetterEntry`. Воркер вызывает `queue.retry_policy_for(job.job_type)` в момент ошибки (даёт «действует политика на момент ошибки»). `rng` у воркера по умолчанию `random.Random()`; `delay_for` вызывается только в ветке повтора.
4. **Порядок проверок в воркере**: нет обработчика → `FAILED` (до всякой политики); нет политики или `not is_retryable` → `FAILED`; `job.attempts >= max_attempts` → `DEAD_LETTERED`; иначе `RETRY_SCHEDULED` с `run_at = clock.now() + timedelta(seconds=delay_for(job.attempts, rng))`.
5. **Таблица переходов**: `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`, `RETRY_SCHEDULED → {RUNNING, CANCELLED}`, `DEAD_LETTERED → {PENDING}` (только из `requeue_dead_letter`). `mark_running` из `RETRY_SCHEDULED` работает как из `PENDING`.
6. **Готовность к запуску.** `InMemoryJobStore.due()` включает `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`.
7. **Dead-letter хранится в очереди** как список `DeadLetterEntry` (порядок попадания), `dead_letters()` возвращает копию. Альтернатива — вычислять из `list_jobs(DEAD_LETTERED)` — отвергнута: порядок попадания не равен порядку `seq`, и нужны `dead_lettered_at`.
8. **`requeue_dead_letter`**: берёт задание (`JobNotFoundError`), проверяет наличие записи/статус до любых изменений (иначе `InvalidTransitionError` через `_transition`), затем переход в `PENDING`, `run_at = now`, `error = None`, `attempts = 0` (у задания снова полный набор попыток, как у нового), удаление записи, `jobs.requeued`. `finished_at`/`started_at` не меняются. Атомарность: проверка до мутаций.
9. **Терминальность.** `RETRY_SCHEDULED` и `DEAD_LETTERED` не входят в `_TERMINAL`, значит `purge_finished` их не удаляет; запись dead-letter не может «повиснуть». `finished_at` для них не выставляется.
10. **Подписи и метрики.** Новые подписи в `_LABELS`, константы в `metrics.py`, дополнить его docstring. Экспорт `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`.
11. **Совместимость.** `JobQueue.__init__` и `Worker.__init__` получают только keyword-only параметры с `None` по умолчанию; без политики ветка воркера идентична прежней.

## Допущения (в тикете не определено)

- `attempts` при `requeue_dead_letter` обнуляется (решение владельца продукта): возвращённое задание получает полный набор попыток. `DeadLetterEntry.attempts` фиксирует число попыток на момент попадания и после возврата запись удаляется.
- Отмена (`cancel`) разрешена для `RETRY_SCHEDULED` (задание не выполняется) и запрещена для `DEAD_LETTERED` («выход один»).
- `requeue_dead_letter` для задания не в dead-letter → `InvalidTransitionError`; для неизвестного id → `JobNotFoundError`.
- `is_terminal` у новых статусов ложно; `failure_rate` не учитывает dead-letter (файл не наш).
- `mark_succeeded` очищает `error`: после повторов у `SUCCEEDED` задания `error is None` (инвариант `Job`).
- Сообщение об ошибке для обоих исходов берётся через `format_error`.

## Risks / Trade-offs

- [Очень большой `max_delay` (например `1e20`) делает `timedelta` непредставимым → `OverflowError` в воркере] → в воркере ограничить секунды величиной, допустимой для `timedelta`, либо ловить `OverflowError` и брать `timedelta.max`-безопасное значение; покрыть тестом.
- [`failure_rate` и отчёт «Последние ошибки» не показывают dead-letter] → ограничение владельца dashboard; передать другой команде.
- [Dead-letter теряется при перезапуске процесса] → как и всё хранилище; вне объёма.
