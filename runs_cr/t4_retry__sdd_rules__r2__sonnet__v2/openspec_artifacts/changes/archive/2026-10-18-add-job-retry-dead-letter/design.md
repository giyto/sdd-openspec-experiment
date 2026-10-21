## Context

Мотивация — в proposal.md, требования — в specs. Текущее устройство `jobq`:

- Все смены статуса идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; счётчик статуса растёт в методе `mark_*` ровно в момент перехода.
- `InMemoryJobStore.due(now)` выбирает только `PENDING` с `run_at <= now`.
- `JobStatus.is_terminal` определяет, что трогает `purge_finished`; `queue.stats()` и `dashboard.render_report` итерируются по всем членам `JobStatus` и берут подписи из `JobStatus.label`, поэтому новые статусы появятся в отчёте без правки `dashboard.py`.
- `Worker.run_once` ловит `Exception` и безусловно вызывает `mark_failed`.
- Время — только из `queue.clock`; ошибки конфигурации — `ConfigError`; стандартная библиотека.

## Goals / Non-Goals

**Goals:**
- Добавить повторы и dead-letter, не меняя поведение без политики и сигнатуры существующих методов.
- Сохранить единый механизм переходов и правило «счётчик растёт в момент перехода».

**Non-Goals:**
- Персистентность dead-letter (хранилище остаётся в памяти).
- Изменения `dashboard.py`, `cli.py`, существующих тестов.
- Автоматический возврат из dead-letter, пакетный requeue, отдельные политики по классам ошибок.

## Decisions

**1. `RetryPolicy` — frozen dataclass с валидацией в `__post_init__`.** Нормализация `non_retryable` в `tuple` делается через `object.__setattr__` (стандартный приём для frozen). Валидация бросает `ConfigError`, проверяет границы по ТЗ, а также отвергает `NaN` (сравнения с `NaN` ложны и пропустили бы мусор) и нечисловые значения; элементы `non_retryable` проверяются как `isinstance(x, type) and issubclass(x, BaseException)`. Альтернатива — валидировать при `set_retry_policy`: отвергнута, объект должен быть корректен с момента создания.

**2. Устойчивый расчёт `delay_for`.** Порядок: проверка `attempt >= 1` (`ConfigError`); если `base_delay == 0` → `0.0`; иначе `raw = base_delay * float(factor) ** (attempt - 1)` внутри `try/except OverflowError`; при переполнении, `inf` или `NaN` берётся `max_delay`; затем `min(raw, max_delay)`. Только после этого, если `jitter > 0`, умножение на `(rng or _default_rng).uniform(1 - jitter, 1 + jitter)` и финальный `min(..., max_delay)`/`max(..., 0.0)`. Так результат всегда в `[0, max_delay]`, а `rng` не трогается при `jitter == 0` и вызывается ровно один раз при `jitter > 0`. Обход `base_delay == 0` нужен, чтобы не получить `0 * inf = nan`. Альтернатива «считать степень через логарифмы/цикл до потолка» сложнее без выигрыша. Генератор по умолчанию — общий экземпляр `random.Random()` модуля `retry`, а не глобальное состояние `random`, чтобы тесты, подставляющие свой `rng`, не зависели от посторонних вызовов.

**3. `is_retryable`.** `False`, если `isinstance(exc, PermanentJobError)` или `isinstance(exc, self.non_retryable)` (при пустом кортеже `isinstance` даёт `False`); иначе `True`. Наследование учитывается самим `isinstance`.

**4. Новые статусы и переходы.** В `JobStatus` добавляются `RETRY_SCHEDULED`, `DEAD_LETTERED` и подписи в `_LABELS`. Оба вне `_TERMINAL`: так `purge_finished` не удаляет dead-letter без изменения собственной логики и `is_terminal` честно отражает «воркер ещё может это взять / оператор ещё может вмешаться». Таблица переходов:

| из | в |
|---|---|
| PENDING | RUNNING, CANCELLED (как было) |
| RUNNING | SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED |
| RETRY_SCHEDULED | RUNNING, CANCELLED |
| DEAD_LETTERED | PENDING |

Переход `DEAD_LETTERED → PENDING` допустим в таблице, но публично достижим только через `requeue_dead_letter`; `cancel` из `DEAD_LETTERED` отклоняется, потому что `CANCELLED` не входит в допустимые цели.

**5. Выбор готовых заданий.** `InMemoryJobStore.due` расширяется до `status in (PENDING, RETRY_SCHEDULED)`; сортировка `(run_at, seq)` не меняется. Это единственная правка `store.py`.

**6. Ответственность: решение — у воркера, состояние — у очереди.** Воркер знает исключение, поэтому решение «FAILED / retry / dead-letter» принимает он; очередь даёт атомарные операции с учётом переходов, метрик и хранилища dead-letter:
- `mark_retry_scheduled(job_id, error, run_at)`: переход, `error`, `run_at`, `jobs.retried`;
- `mark_dead_lettered(job_id, error)`: переход, `error`, `finished_at`, добавление `DeadLetterEntry`, `jobs.dead_lettered`;
- `requeue_dead_letter(job_id)`: проверка статуса до любых изменений; затем переход в `PENDING`, `run_at = now`, `error = None`, `attempts = 0`, `finished_at = None`, удаление записи, `jobs.requeued`.

`mark_failed` не меняется. Альтернатива — поместить всю логику в `JobQueue.mark_failed(job_id, error, exc)`: отвергнута, так как меняет сигнатуру существующего публичного метода.

**7. Алгоритм воркера** (после `mark_running`, `attempts` уже увеличен):
1. Нет обработчика → `mark_failed` (политику не смотрим, `rng` не трогаем).
2. Исключение → `policy = queue.retry_policy_for(job.job_type)` (на момент ошибки).
3. `policy is None or not policy.is_retryable(exc)` → `mark_failed`.
4. `job.attempts >= policy.max_attempts` → `mark_dead_lettered`.
5. Иначе `delay = policy.delay_for(job.attempts, self._rng)`; `mark_retry_scheduled(job.id, error, queue.clock.now() + timedelta(seconds=delay))`.

Порядок проверок 3 → 4 гарантирует, что неповторяемая ошибка на последней попытке даёт `FAILED`, а `rng` вызывается только на шаге 5.

**8. Хранилище dead-letter** — список `DeadLetterEntry` в `JobQueue` (порядок попадания); `dead_letters()` отдаёт копию. Удаление записи при requeue — линейный поиск по `job_id`; объёмы оператора малы. Отдельный объект в `store` не вводим, чтобы не менять `InMemoryJobStore` сверх п. 5. Заданий, удалённых из хранилища, в dead-letter быть не может, потому что `purge_finished` их не трогает.

**9. `finished_at`.** Для `DEAD_LETTERED` проставляется (выполнение закончилось, нужно для показа в отчётах), при requeue очищается; для `RETRY_SCHEDULED` не ставится. `started_at` остаётся временем последнего запуска.

**10. Экспорты и документация.** `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` добавляются в `jobq/__init__.py`; константы счётчиков — в `metrics.py` (`JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`) с обновлением docstring; README — таблица модулей и раздел о повторах. Циклических импортов нет: `retry` зависит только от `errors`.

## Risks / Trade-offs

- [Появление двух новых статусов меняет вывод `stats()` и отчёта дежурных у существующих потребителей] → Это ожидаемо и безопасно: существующие тесты проверяют набор ключей через `JobStatus`; значения 0 при выключенной политике.
- [Обнуление `attempts` при requeue теряет историю попыток] → Следует решению тимлида (UPD); число попыток до перезапуска остаётся в записи на момент попадания и в логах — при requeue логируем `attempts` и последнюю ошибку на уровне INFO.
- [`DEAD_LETTERED` нетерминален, и код, полагающийся на `is_terminal` для «закончено», будет считать такие задания незавершёнными] → Осознанно, иначе `purge_finished` удалил бы dead-letter; в docstring `is_terminal` уточняется смысл.
- [Общий дефолтный `random.Random` не потокобезопасен в смысле воспроизводимости] → Воркер синхронный; для воспроизводимости передаётся свой `rng`.
- [Политика заменяется во время жизни задания] → По ТЗ берётся действующая на момент ошибки; уменьшение `max_attempts` ниже текущих `attempts` отправит задание в dead-letter при следующей ошибке.

## Assumptions

- `jitter`, `base_delay` и т.п. — вещественные числа; `NaN` и нечисловые значения считаются ошибкой конфигурации.
- Если в политике `max_attempts` — `bool`, это не особый случай и отдельно не обрабатывается.
- `requeue_dead_letter` для задания не в `DEAD_LETTERED` даёт `InvalidTransitionError` (неизвестный id — `JobNotFoundError`).
- Если `max_delay` меньше `base_delay` — это ошибка; при равенстве допустимо.
- Новые счётчики по тем же правилам: растут ровно в момент перехода/операции, не при попытке с ошибкой.

## Migration Plan

Миграции данных нет (хранилище в памяти). Изменение обратно совместимо; откат — возврат коммита. Политика включается явно (`default_retry_policy` или `set_retry_policy`); без неё поведение прежнее.
