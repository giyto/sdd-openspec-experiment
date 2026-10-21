## Context

Мотивация — в proposal.md. Текущее устройство: все смены статуса идут через `JobQueue._transition` по таблице `_TRANSITIONS`; `InMemoryJobStore.due()` выбирает только `PENDING`; `purge_finished` удаляет задания, у которых `is_terminal`; отчёт (`dashboard.render_report`) и `stats()` перебирают все `JobStatus`, поэтому новые статусы и подписи попадут в отчёт без правок `dashboard.py`. `dashboard.py` и `cli.py` менять нельзя. Соглашения: время только из `queue.clock`, ошибки только от `JobqError`, настройки keyword-only, только stdlib.

## Goals / Non-Goals

**Goals:**
- Повторы с экспоненциальной задержкой, dead-letter и возврат из него, без изменения поведения при отсутствии политики.
- `delay_for` математически безопасна: результат всегда в `[0, max_delay]` для любого `attempt`.

**Non-Goals:**
- Персистентность dead-letter (хранилище только в памяти).
- Изменения `dashboard.py`, `cli.py`, существующих тестов, новые зависимости.
- Политика на конкретное задание, слияние политик по полям, повтор ошибок конфигурации.

## Decisions

**Статусы нетерминальны.** `RETRY_SCHEDULED` и `DEAD_LETTERED` не входят в `_TERMINAL`. Тем самым `purge_finished` автоматически не трогает dead-letter (требование «лежат до requeue»), и `is_terminal` остаётся честным: из них ещё можно выйти. Альтернатива — отдельная проверка в `purge_finished` — хрупче. Следствие: `failure_rate` в dashboard не меняется (считает только FAILED и SUCCEEDED).

**Таблица переходов.** `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`; `RETRY_SCHEDULED → {RUNNING, CANCELLED}`; `DEAD_LETTERED → {PENDING}`. Отмена из dead-letter тем самым запрещена естественным образом (`InvalidTransitionError`), а переход `DEAD_LETTERED → PENDING` вызывается только из `requeue_dead_letter`.

**Выборка готовых.** `InMemoryJobStore.due()` берёт `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`.

**`delay_for` без переполнения.** `base_delay == 0` → `0.0` сразу (избегаем `0 * inf = nan`). Иначе `factor ** (attempt - 1)` оборачивается в `try/except OverflowError` → `max_delay` (покрывает `2.0 ** 5000` и `attempt=10**9`); если произведение стало `inf`, `min(..., max_delay)` всё равно возвращает `max_delay`. Затем `min(raw, max_delay)`, при `jitter > 0` — умножение на один `uniform`, и итог `min(max(x, 0.0), max_delay)`, чтобы джиттер не пробивал потолок. Альтернатива (логарифмы) сложнее и менее точна. При `factor == 1` возведение в степень безопасно. Без `rng` используется модуль `random` (`random.uniform`).

**Валидация в `__post_init__`** frozen-датакласса; `non_retryable` нормализуется в `tuple` через `object.__setattr__`. Проверки пишутся в виде `not (x >= bound)`, чтобы NaN отвергался. `bool` не считается допустимым числом; `max_attempts` — `int` (не `bool`). Все нарушения — `ConfigError`. Проверка класса исключения: `isinstance(x, type) and issubclass(x, BaseException)`.

**Классификация.** `is_retryable`: `isinstance(exc, PermanentJobError)` → False; `isinstance(exc, self.non_retryable)` → False (учитывает наследование); иначе True. `PermanentJobError(JobqError)` в `errors.py`.

**Алгоритм воркера** (в `run_once`, после `mark_running`):
1. Нет обработчика → `mark_failed` (без политики, как сейчас).
2. Обработчик упал → `policy = queue.retry_policy_for(job.job_type)` (на момент ошибки).
3. `policy is None` или `not policy.is_retryable(exc)` → `mark_failed`.
4. `job.attempts >= policy.max_attempts` → `mark_dead_lettered`.
5. Иначе `delay = policy.delay_for(job.attempts, self._rng)`; `mark_retry_scheduled(job.id, error, queue.clock.now() + timedelta(seconds=delay))`.
`rng` затрагивается только в п. 5 (и только при `jitter > 0`, это решает `delay_for`).

**Методы очереди.** `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` — по образцу `mark_failed`; ставят `error`, считают `jobs.retried` / `jobs.dead_lettered`. `finished_at` у них остаётся `None` (задание не завершено); `mark_dead_lettered` добавляет `DeadLetterEntry` в упорядоченный `dict[str, DeadLetterEntry]` очереди. `mark_succeeded` дополнительно сбрасывает `error = None` (инвариант модели: у SUCCEEDED `error` всегда `None`, а после повтора там осталась бы прошлая ошибка). `cancel` не меняется: он уже работает через таблицу переходов, но для `RETRY_SCHEDULED` вызывается `_transition` в `CANCELLED`, остальное (finished_at, счётчик) то же.

**Возврат.** `requeue_dead_letter(job_id)`: `store.get` (→ `JobNotFoundError`), `_transition(job, PENDING)` (→ `InvalidTransitionError` для не-dead-letter), затем `run_at = now`, `error = None`, `attempts = 0`, `finished_at = None`, удаление записи, `jobs.requeued`, `logger.info` с числом прежних попыток. Решение об обнулении `attempts` взято из UPD тимлида (оно отменяет формулировку «attempts сохраняем» из тела тикета): иначе возвращённое задание уходило бы в dead-letter после первой же ошибки. Прежнее число попыток остаётся в `DeadLetterEntry` до возврата и в логе. `started_at` не сбрасывается.

**Политики.** Хранятся в очереди: `default_retry_policy` и `dict[str, RetryPolicy]`. `retry_policy_for` возвращает политику типа или дефолт (без слияния). Типы аргументов проверяются (`ConfigError`).

**Хранение dead-letter в очереди, а не в store.** Простота и отсутствие изменений интерфейса хранилища. Ограничение: задания, уже лежащие в переданном `store` в статусе `DEAD_LETTERED`, не получат записи (в этом изменении такого состояния не бывает, т.к. статус новый).

**Метрики.** Константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `metrics.py`, обновляется docstring модуля. Счётчик растёт ровно в момент перехода, как у существующих.

**Подписи.** «Ожидает повтора» и «В dead-letter» добавляются в `_LABELS` в `models.py`; ширина колонки отчёта (18) достаточна.

## Risks / Trade-offs

- [Потребители `stats()`/отчёта увидят две новые строки] → ожидаемо, существующие тесты перебирают `JobStatus` и не ломаются.
- [Задание в dead-letter не истекает и не чистится] → осознанное требование; нужен только `requeue_dead_letter`. Рост памяти контролируется дежурными.
- [Бесконечно большие `max_attempts` (10000)] → безопасно благодаря защите от переполнения в `delay_for`.
- [Дубликаты записей/рассинхрон между dict очереди и статусами] → запись создаётся только в `mark_dead_lettered` и удаляется только в `requeue_dead_letter`; тесты проверяют согласованность.
- [Часы вне нашего контроля сдвигаются назад] → `run_at` считается от `clock.now()` в момент ошибки; специальной обработки нет.

## Migration Plan

Миграции данных нет (хранилище в памяти). Без политик поведение прежнее, откат — откат коммита.

## Допущения (тикет не определяет явно)

- Нечисловые/NaN параметры `RetryPolicy`, а также не-`RetryPolicy` в `set_retry_policy` / `default_retry_policy` → `ConfigError`.
- `requeue_dead_letter` для неизвестного id → `JobNotFoundError`; для задания не в dead-letter → `InvalidTransitionError`.
- `DeadLetterEntry.attempts` и `error` фиксируются на момент попадания; `dead_lettered_at` — `queue.clock.now()`.
- `dead_letters()` возвращает новый список; запись неизменяема.
- Ошибка в `Job.error` у задания в `RETRY_SCHEDULED` — последняя ошибка; при успешном повторе очищается.
- Ловятся только `Exception` (как сейчас), `BaseException` вроде `KeyboardInterrupt` не обрабатываются.
- Сброс `finished_at` при возврате — безопасное следствие того, что задание снова нетерминально.

## Решения при реализации

- Тип генератора в сигнатурах — `Protocol` `UniformSource` в `jobq/retry.py` (нужен только метод `uniform`); `Worker(rng=...)` принимает его.
- `delay_for` дополнительно проверяет, что `attempt` — `int` (не `bool`), иначе `ConfigError`.
- `factor=inf` допустим (результат всё равно ограничен `max_delay`); `base_delay` и `max_delay` должны быть конечными.
- Тесты новой функциональности собраны в `tests/test_retry.py`; существующие тесты не менялись.
