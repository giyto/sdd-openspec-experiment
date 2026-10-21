## Context

Сейчас `Worker.run_once` при исключении в обработчике сразу вызывает `JobQueue.mark_failed`, и задание
уходит в `FAILED`. Переходы статусов проверяются таблицей `_TRANSITIONS` в `jobq/queue.py`; все
изменения идут через `_transition`. Часы внедряются через `Clock`, датакласс `Job` — mutable, `attempts`
увеличивается в `mark_running`. Хранилище `InMemoryJobStore.due()` сейчас отбирает только `PENDING`.
Дашборд (`jobq/dashboard.py`) и CLI не меняем, но дашборд итерирует `JobStatus`, поэтому новые статусы
попадут в его отчёт автоматически.

См. `proposal.md` — Why и What Changes; требования — в `specs/job-retry/spec.md` и
`specs/dead-letter/spec.md`.

## Goals / Non-Goals

**Goals:**
- Вся логика решения «повторить / в dead-letter / в FAILED» находится в одном месте (воркер),
  переходы статусов остаются только через `JobQueue`.
- `delay_for` детерминирован при заданном `rng` и не падает ни при каком `attempt`.
- Существующие вызовы и поведение без политики не меняются.

**Non-Goals:**
- Персистентность dead-letter (хранилище в памяти, как и остальная очередь).
- Асинхронность, отдельный поток или планировщик повторов: повтор — это просто `RETRY_SCHEDULED`
  с `run_at`, который воркер берёт как обычное задание.
- Изменения в `dashboard.py` и `cli.py`.

## Decisions

**1. Модуль `jobq/retry.py` содержит только `RetryPolicy`, без состояния очереди.**
`RetryPolicy` — frozen dataclass с `__post_init__`, который валидирует поля и бросает `ConfigError`
(как во всём проекте для конфигурации). `non_retryable` приводится к `tuple` через
`object.__setattr__`, потому что dataclass заморожен.
*Альтернатива:* отдельный класс-билдер. Отклонена: лишняя сущность без выгоды.

**2. Вычисление задержки без переполнения.**
`factor ** (attempt - 1)` при больших `attempt` даёт `OverflowError`. Поэтому расчёт идёт в `try`:
при `OverflowError` берётся `max_delay`. Для `base_delay == 0` результат `0.0` сразу. Затем
`min(raw, max_delay)`. Если `jitter > 0`, вызывается `rng.uniform(1 - jitter, 1 + jitter)` один раз,
результат умножается на значение и снова ограничивается `max_delay` (джиттер не пробивает потолок,
по решению тимлида). При `jitter == 0` `rng` не трогается.
*Альтернатива:* считать через `math.log` или через целочисленный предел степени. Отклонена: `try` короче
и точно соответствует семантике «всё равно упрётся в max_delay».

**3. Источник случайности.** `delay_for(attempt, rng=None)`: если `rng` не передан и `jitter > 0`,
используется `random.Random()` (новый экземпляр). `Worker(..., rng=None)` по умолчанию создаёт
`random.Random()` и передаёт его в `delay_for`. Так тесты передают предсказуемый `rng`, а `rng` не
трогается, если задание не уходит в повтор.

**4. Где живут политики и dead-letter — в `JobQueue`.** Поля `_default_retry_policy`,
`_type_policies: dict[str, RetryPolicy]`, `_dead_letters: dict[str, DeadLetterEntry]` (dict сохраняет
порядок вставки, поэтому `dead_letters()` отдаёт записи в порядке попадания). `retry_policy_for(job_type)`
возвращает эффективную политику: политика типа, иначе дефолт, иначе `None`. Слияния полей нет.

**5. Решение по падению — в воркере, переходы — в очереди.** Воркер вызывает новые методы очереди:
- `schedule_retry(job_id, error, run_at)` — переход `RUNNING → RETRY_SCHEDULED`, `job.error = error`,
  `job.run_at = run_at`, `jobs.retried`;
- `mark_dead_lettered(job_id, error)` — переход `RUNNING → DEAD_LETTERED`, `finished_at = now`,
  запись в `_dead_letters`, `jobs.dead_lettered`;
- `mark_failed` (без изменений) — остаётся для `FAILED`.

Политику воркер получает через `queue.retry_policy_for(job.job_type)` в момент ошибки. Так выполняется
требование «политика в момент ошибки, а не при постановке». Выбор между `FAILED`, `DEAD_LETTERED` и
`RETRY_SCHEDULED` и вызов `rng` происходят только здесь, поэтому `rng` трогается только при реальном
повторе.

*Альтернатива:* перенести решение в `JobQueue.mark_error(job_id, exc, rng)`. Отклонена: очередь не должна
знать о классификации исключений, это обязанность воркера, который уже форматирует ошибку.

**6. Таблица переходов расширяется:**
- `PENDING`: + (без изменений: `RUNNING`, `CANCELLED`)
- `RUNNING`: + `RETRY_SCHEDULED`, `DEAD_LETTERED` (к `SUCCEEDED`, `FAILED`)
- `RETRY_SCHEDULED`: `RUNNING`, `CANCELLED`
- `DEAD_LETTERED`: `PENDING` (только через `requeue_dead_letter`)

`cancel` для `DEAD_LETTERED` не разрешён, потому что в его таблице нет `CANCELLED`. Это даёт
`InvalidTransitionError` без отдельной проверки.

**7. `DEAD_LETTERED` считается терминальным** (`is_terminal = True`: воркер его не выполнит), но
`purge_finished` явно пропускает этот статус. Иначе терминальность и сохранность в dead-letter
конфликтовали бы. `FAILED` остаётся терминальным и очищается, как сейчас.

**8. `store.due()` берёт `PENDING` и `RETRY_SCHEDULED`.** Сортировка прежняя (`run_at`, `seq`).
Существующий тест `store.due` работает только с `PENDING`, поэтому он не ломается.

**9. `requeue_dead_letter(job_id)`:**
- если задание не найдено — `JobNotFoundError` (уже есть в `store.get`);
- если не в `DEAD_LETTERED` — `InvalidTransitionError(job_id, current, "pending")`;
- иначе переход `DEAD_LETTERED → PENDING`, `run_at = now`, `error = None`, `finished_at = None`,
  `attempts = 0`, удаление записи, `jobs.requeued`, лог с числом попыток до перезапуска.

Обнуление `attempts` взято из последнего уточнения тимлида (в тикете оно поначалу сказано «сохраняем»).
Прежнее значение видно в логе.

**10. Ошибки.** Добавляем `PermanentJobError(JobqError)` в `errors.py`. Все новые ошибки конфигурации —
`ConfigError`. Для `set_retry_policy` с пустым `job_type` — `ConfigError`, как у `registry.register`.

**11. Метрики.** Константы `JOBS_RETRIED = "jobs.retried"`, `JOBS_DEAD_LETTERED = "jobs.dead_lettered"`,
`JOBS_REQUEUED = "jobs.requeued"` в `metrics.py`. Строку в docstring модуля тоже дополняем.

**12. Публичный экспорт.** `RetryPolicy`, `DeadLetterEntry`, `PermanentJobError` добавляются в
`jobq/__init__.py` и `__all__`. README: строка в таблице модулей для `retry.py` и абзац в «Соглашениях».

## Risks / Trade-offs

- **[Тесты дашборда и CLI]** `test_dashboard_cli.py` проверяет наличие строк всех статусов по `label`,
  новые статусы в отчёте будут. Тест использует `for status in JobStatus`, поэтому проходит. → Запустить
  весь набор тестов после реализации.
- **[Потеря dead-letter при перезапуске процесса]** Хранилище в памяти, как и вся очередь. → Зафиксировано
  как non-goal; персистентность — отдельная задача.
- **[Сброс `attempts` при requeue]** Снижает наглядность числа попыток. → Число до перезапуска пишется в лог
  (по решению тимлида).
- **[Джиттер и потолок]** Клиппинг после джиттера даёт скопление задержек ровно в `max_delay`.
  → Принято: требование тимлида «жёсткий потолок».
- **[Производительность `due()`]** Фильтр по двум статусам — тот же линейный проход, что и сейчас.

## Migration Plan

Миграции данных нет: состояние в памяти. Развёртывание — обычный релиз. Без `default_retry_policy` и
без `set_retry_policy` поведение идентично прежнему (любая ошибка → `FAILED`), поэтому откат — удаление
вызовов в коде потребителя, без последствий для данных.

## Open Questions

Нет. Неоднозначности зафиксированы как допущения в этом документе (решения 3, 4, 7, 9, 10) и не влияют
на спецификации.

## Решения при реализации

Спецификация не задаёт следующее, поэтому выбрано здесь (при apply, без участия пользователя):

- **Значения по умолчанию `RetryPolicy`:** `max_attempts=3`, `base_delay=1.0`, `factor=2.0`,
  `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`. Сценарий `RetryPolicy()` в спецификации требует,
  чтобы конструктор без аргументов работал.
- **Валидация типов:** `max_attempts` и `attempt` — `int` (не `bool`); численные параметры — `int`/`float`
  (не `bool`) и конечные (`math.isfinite`). Нарушение любого правила даёт `ConfigError`.
- **Место `is_retryable`:** метод `RetryPolicy.is_retryable(exc)`, а не функция модуля. Так политика
  сама отвечает за свой набор `non_retryable`.
- **Конструктор `RetryPolicy` и `jitter`:** при `jitter > 0` без `rng` внутри `delay_for` создаётся новый
  `random.Random()` на каждый вызов (как в решении 3). Воркер всегда передаёт свой `rng`.
- **`schedule_retry` не трогает `finished_at`:** задание не завершено, поле остаётся `None`.
- **`requeue_dead_letter` для статуса, отличного от `DEAD_LETTERED`:** переход проверяется через
  `_transition`, поэтому ошибка — `InvalidTransitionError(job_id, current, "pending")`, как в решении 9.
- **Порядок статусов в `JobStatus`:** новые статусы вставлены рядом с родственными (`RETRY_SCHEDULED`
  после `RUNNING`, `DEAD_LETTERED` после `FAILED`). Отчёт дашборда идёт по `JobStatus`, поэтому порядок
  строк в нём меняется; сам дашборд не трогаем.
