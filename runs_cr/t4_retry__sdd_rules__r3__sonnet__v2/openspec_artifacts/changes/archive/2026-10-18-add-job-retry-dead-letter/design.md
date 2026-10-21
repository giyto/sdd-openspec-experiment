## Context

Статусы меняются только через `JobQueue._transition` по таблице `_TRANSITIONS`; воркер сейчас на любое исключение вызывает `mark_failed`. `InMemoryJobStore.due()` берёт только `PENDING`, `purge_finished` удаляет всё с `is_terminal`, `dashboard.render_report` перебирает `JobStatus` и берёт подписи из `label` (сам `dashboard.py` менять нельзя). Мотивация — см. proposal.md.

## Goals / Non-Goals

**Goals:**
- Реализовать API из тикета без изменений имён и сигнатур; поведение без политики идентично текущему.
- Логика выбора исхода сосредоточена в воркере и `RetryPolicy`, переходы — в очереди.

**Non-Goals:**
- Персистентность dead-letter (хранилище в памяти), автоматический requeue, изменение `dashboard.py`/`cli.py`.

## Decisions

1. **`jobq/retry.py` — модуль без зависимости от очереди.** `RetryPolicy` — `@dataclass(frozen=True)`; валидация и приведение `non_retryable` к `tuple` в `__post_init__` (`object.__setattr__`), ошибки — `ConfigError`. Числа проверяются на конечность (`math.isfinite`), `bool` для `max_attempts` отвергается. NaN/inf не должны попасть в расчёт `run_at`.
2. **Безопасный расчёт задержки.** `factor ** (attempt-1)` считается в `try/except OverflowError` (→ `max_delay`); `base_delay == 0` обрабатывается явно (0), иначе `0 * inf` даст NaN. Затем `min(raw, max_delay)`, джиттер и финальный `min(max(x, 0), max_delay)`. Альтернатива — логарифмы: сложнее и менее точно для малых `attempt`.
3. **Генератор.** Без `rng` и при `jitter > 0` `delay_for` использует модульный `random`; `Worker` при `rng=None` создаёт `random.Random()`. Один `uniform` на задержку, при `jitter == 0` генератор не вызывается — контракт для детерминированных тестов.
4. **Эффективная политика.** `retry_policy_for` возвращает политику типа, иначе дефолт; воркер читает её в момент ошибки, снимка в задании нет. Слияния полей нет.
5. **Переходы.** В `_TRANSITIONS`: `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`, `RETRY_SCHEDULED → {RUNNING, CANCELLED}`, `DEAD_LETTERED → {PENDING}`. Новые методы очереди: `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)`; счётчик увеличивается после успешного `_transition`. `mark_failed` не меняется.
6. **Готовность.** `InMemoryJobStore.due()` учитывает `PENDING` и `RETRY_SCHEDULED` (общая сортировка `(run_at, seq)`) — единственное изменение хранилища.
7. **Терминальность и purge.** Новые статусы не входят в `_TERMINAL`, поэтому `purge_finished` их не трогает, а существующие тесты `is_terminal` не затронуты. `finished_at` для них не выставляется.
8. **Хранение dead-letter.** `JobQueue` держит упорядоченный `dict[job_id, DeadLetterEntry]`; `dead_letters()` отдаёт `list(values())`. Вывод из статуса хранилища потерял бы порядок попадания и `dead_lettered_at`.
9. **Requeue.** Меняет то же `Job`: `PENDING`, `run_at=now`, `error=None`, `attempts=0` (решение тимлида в UPD, оно отменяет «attempts сохраняем» из описания), `started_at=None`; запись удаляется, прежнее число попыток пишется в лог (`logger.info`).
10. **Алгоритм воркера** при исключении: `policy = queue.retry_policy_for(type)`; `None` или `not policy.is_retryable(exc)` → `mark_failed`; `job.attempts >= policy.max_attempts` → `mark_dead_lettered`; иначе `delay = policy.delay_for(job.attempts, rng)`, `run_at = clock.now() + timedelta(seconds=delay)` → `mark_retry_scheduled`. Ветка `UnknownJobTypeError` не меняется (`FAILED`, политика не читается). Ловится по-прежнему `Exception`.
11. **Экспорт и документация.** `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` добавляются в `jobq/__init__.py`; README обновляется.

## Допущения (неоднозначности тикета)

- `retry_policy_for` возвращает *действующую* политику (тип, иначе дефолт, иначе `None`).
- `DEAD_LETTERED` и `RETRY_SCHEDULED` не `is_terminal`: тикет требует лишь, чтобы purge не трогал dead-letter.
- `requeue_dead_letter` для задания не в dead-letter → `InvalidTransitionError`; неизвестный id → `JobNotFoundError`.
- `attempts` в `DeadLetterEntry` — значение на момент попадания; у задания при requeue обнуляется.
- Нефинитные числа в `RetryPolicy` — ошибка конфигурации (ужесточение сверх списка тикета).
- Dead-letter хранится в памяти очереди; очередь, созданная поверх хранилища с уже `DEAD_LETTERED` заданиями, их записей не восстанавливает.
- `jobs.retried` считается в момент перехода в `RETRY_SCHEDULED`, а не при запуске повтора.

## Risks / Trade-offs

- [Расширение `store.due()` затрагивает файл вне перечня тикета] → Изменение минимально, покрыто новыми тестами; существующие тесты `due` остаются зелёными.
- [`failure_rate` и список ошибок отчёта не учитывают новые статусы] → `dashboard.py` вне зоны ответственности; строки статусов и счётчики в отчёте появляются автоматически.
- [Потеря dead-letter при перезапуске процесса] → Хранилище и так в памяти; фиксируется как ограничение.

## Решения при реализации

- `Job.error` сбрасывается в `None` в `mark_succeeded`: иначе успех после повтора сохранял бы ошибку прошлой попытки, что противоречит спецификации и инварианту `Job`.
- `RetryPolicy` приводит числовые поля к `float` в `__post_init__`; это исключает огромные `int` в `factor ** n`.
- `delay_for` проверяет, что `attempt` — `int` (не `bool`) и `>= 1`, иначе `ConfigError`.
