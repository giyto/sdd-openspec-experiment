## Context

`JobQueue` держит единую таблицу переходов `_TRANSITIONS`, воркер сейчас переводит любую ошибку в `FAILED` через `mark_failed`. `InMemoryJobStore.due()` выбирает только `PENDING`. `render_report` перебирает `JobStatus` и берёт подписи из `JobStatus.label`, `stats()` строится по `count_by_status()` для всех статусов — поэтому новые статусы попадают в отчёт сами. `dashboard.py` и `cli.py` менять запрещено. Мотивация — см. proposal.md.

## Goals / Non-Goals

**Goals:**
- Повторы и dead-letter без изменения сигнатур существующих публичных методов.
- Весь расчёт задержки — в чистой функции `RetryPolicy.delay_for`, пригодной для тестов.

**Non-Goals:**
- Персистентность dead-letter (хранилище только в памяти), автоповтор из dead-letter, пакетный requeue, правки `dashboard.py`/`cli.py`.

## Decisions

1. **`RetryPolicy` — `@dataclass(frozen=True)`, валидация в `__post_init__`.** `non_retryable` нормализуется в `tuple` через `object.__setattr__`. Проверка класса: `isinstance(x, type) and issubclass(x, BaseException)`. Нечисловые и NaN/inf значения отклоняются (`bool` за число не принимается) — иначе сравнения тихо дают неверный результат. Параметры именованные (`kw_only=True`).

2. **Устойчивый расчёт задержки.** `factor ** (attempt-1)` для float падает с `OverflowError`, а `0 * inf` даёт NaN. Алгоритм: если `base_delay == 0` → 0; если `factor == 1` → `base_delay`; иначе `try: raw = base * factor ** (attempt-1)` и `except OverflowError: raw = max_delay`; затем `min(raw, max_delay)` (inf тоже срезается). Альтернатива — логарифмы: сложнее, без выигрыша. После джиттера результат повторно ограничивается `min(..., max_delay)`, так как множитель может быть до `1+jitter`. Джиттер: `rng.uniform(1-j, 1+j)` ровно один раз и только при `jitter > 0`. Если `rng=None` — свежий `random.Random()` (допущение; воркер всегда передаёт свой).

3. **`PermanentJobError(JobqError)` в `errors.py`; `is_retryable` = `not isinstance(exc, (*non_retryable, PermanentJobError))`.** `isinstance` покрывает подклассы.

4. **Решение о судьбе задания принимает `Worker`, состояние меняет `JobQueue`.** В очереди добавляются `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)`; `mark_failed` остаётся. Порядок проверок в воркере строго по ТЗ: нет политики → `mark_failed`; неповторяемая → `mark_failed`; `attempts >= max_attempts` → dead-letter; иначе `delay_for(job.attempts, rng)` и retry. Так `rng` не трогается без реального повтора. `UnknownJobTypeError` обрабатывается до политики → `FAILED`. Политика читается через `queue.retry_policy_for(job.job_type)` в момент ошибки.

5. **Таблица переходов.** `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`; `RETRY_SCHEDULED → {RUNNING, CANCELLED}`; `DEAD_LETTERED → {PENDING}` (только через `requeue_dead_letter`). `cancel` целится в `CANCELLED`, поэтому отмена из `DEAD_LETTERED` автоматически даёт `InvalidTransitionError`.

6. **Выборка.** `store.due()` берёт статусы `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`. `seq` при повторе не меняется — это и даёт «порядок исходной постановки». `mark_running` разрешён из обоих статусов и увеличивает `attempts`.

7. **Dead-letter хранится в очереди как `dict[str, DeadLetterEntry]`** (порядок вставки = порядок попадания; после requeue запись удалена, повторное попадание — снова в конец). `dead_letters()` возвращает новый список. `DeadLetterEntry` — frozen-датакласс в `models.py`, время — `clock.now()`. Альтернатива — вычислять список из `store.by_status(DEAD_LETTERED)`: теряет порядок попадания.

8. **`requeue_dead_letter`:** `store.get` (→ `JobNotFoundError`), затем переход `DEAD_LETTERED → PENDING` (→ `InvalidTransitionError` для прочих статусов), затем `run_at=now`, `attempts=0`, `error=None`, `finished_at=None`, `result=None`; `seq` сохраняется. Метрика `jobs.requeued`; `jobs.enqueued` не трогаем.

9. **Успех и очистка.** `mark_succeeded` обнуляет `error`. `is_terminal` у `DEAD_LETTERED` истинен, но `purge_finished` явно пропускает этот статус. У dead-lettered задания `finished_at` ставится (момент ухода). Подписи «Ожидает повтора» (15 символов) и «В dead-letter» умещаются в `LABEL_WIDTH=18`, форматирование отчёта не ломается.

10. **Метрики** — константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `metrics.py`. Новые имена экспортируются из `jobq/__init__.py`.

## Risks / Trade-offs

- [Код может полагаться на «terminal ⇒ можно purge»] → `purge_finished` исключает `DEAD_LETTERED` явно; покрыть тестом.
- [`failure_rate` в `dashboard.py` не считает dead-letter сбоем] → вне нашей зоны; сообщить команде-владельцу.
- [`now` для `run_at` берётся после выполнения обработчика] → так и сказано в ТЗ («текущее время + задержка»).
- [`max_attempts` уменьшили, пока задание ждало повтора] → следующий сбой сразу даст dead-letter; следствие правила «политика берётся в момент ошибки».
- [Float-арифметика джиттера может дать значение выше `max_delay`] → финальный `min`.

## Migration Plan

Чисто аддитивное изменение, миграции данных нет (хранилище в памяти). Без настройки политик поведение идентично прежнему. Откат — revert коммита.


## Решения при реализации

- `delay_for` принимает только `int >= 1` в `attempt` (bool и float → `ConfigError`); `factor` приводится к `float` перед возведением в степень, чтобы огромный `int` не давал `OverflowError` при умножении на `float`.
- `RetryPolicy` — `kw_only=True`; `mark_retry_scheduled`/`mark_dead_lettered` не очищают `started_at`; `finished_at` ставится только у dead-letter.
