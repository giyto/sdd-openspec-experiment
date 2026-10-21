### design.md

## Context

Сейчас `Worker.run_once` при любом `Exception` вызывает `queue.mark_failed`. Статусы меняются только через `JobQueue._transition` по таблице `_TRANSITIONS`; `InMemoryJobStore.due` отбирает только `PENDING`; `purge_finished` удаляет все терминальные задания; `dashboard.render_report` перебирает `JobStatus` и берёт `label`, поэтому новые статусы появятся в отчёте без правок `dashboard.py`/`cli.py` (они закрыты для изменений). Мотивация — в proposal.md.

## Goals / Non-Goals

**Goals:**
- Повторы и dead-letter без изменения поведения при отсутствии политик.
- Детерминированность для тестов: время только из `queue.clock`, случайность только из `rng`.

**Non-Goals:**
- Персистентность dead-letter, повторы вне воркера, асинхронность, изменение `dashboard.py`/`cli.py`.
- Выделение отдельного публичного класса хранилища dead-letter.

## Decisions

**1. `RetryPolicy` как frozen dataclass с `__post_init__`.** Валидация в `__post_init__`, `non_retryable` нормализуется в `tuple` через `object.__setattr__`. Все нарушения — `ConfigError`, включая нечисловые типы и NaN (проверки в форме `not (x >= 0)`), чтобы не выпускать `TypeError`. Класс исключения проверяется `isinstance(x, type) and issubclass(x, BaseException)`. Нечитаемый как последовательность `non_retryable` (например, одиночный класс) — `ConfigError`. Альтернатива — валидация в `JobQueue`: отвергнута, политика должна быть корректной сразу при создании.

**2. Безопасный `delay_for`.** Порядок: проверка `attempt >= 1`; если `base_delay == 0` — база 0; иначе при `factor == 1` — `base_delay`; иначе `factor ** (attempt - 1)` внутри `try/except OverflowError` с результатом `max_delay` (для больших `attempt` ограничение достигается задолго до переполнения, поэтому при `OverflowError` ответ однозначно `max_delay`); затем `min(..., max_delay)`. Умножение `base_delay * inf` не даёт исключения и отсекается `min`, а `0 * inf` (NaN) исключён отдельной веткой `base_delay == 0`. Jitter — после ограничения: `delay * rng.uniform(1 - j, 1 + j)`; при `jitter == 0` ветка не обращается к `rng`. Если `rng is None` и `jitter > 0`, создаётся `random.Random()` (глобальное состояние `random` не используется). Альтернатива — вычисление через логарифмы: сложнее и теряет точность на малых значениях.

**3. Таблица переходов.** `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`, `RETRY_SCHEDULED → {RUNNING, CANCELLED}`, `DEAD_LETTERED → {PENDING}`. Переход `DEAD_LETTERED → PENDING` выполняет только `requeue_dead_letter`. Новые методы очереди `mark_retry_scheduled(job_id, error, delay)` и `mark_dead_lettered(job_id, error)` (по образцу `mark_failed`) инкапсулируют переход, запись `error`, счётчик и запись в dead-letter. `mark_succeeded` дополнительно очищает `error`, чтобы выполнить инвариант «у SUCCEEDED `error` всегда `None`» после успешного повтора. Метод `mark_retry_scheduled` принимает уже посчитанную задержку: `rng` остаётся ответственностью воркера, а очередь не знает о политиках при переходе.

**4. Решение принимает воркер, политику даёт очередь.** Воркер в `except Exception` вызывает `queue.retry_policy_for(job.job_type)` в момент ошибки и применяет цепочку: нет политики → `mark_failed`; `not is_retryable` → `mark_failed`; `job.attempts >= max_attempts` → `mark_dead_lettered`; иначе `delay_for(job.attempts, rng)` → `mark_retry_scheduled`. `delay_for` вызывается только в последней ветке — этим обеспечивается «`rng` трогаем, только когда реально планируем повтор». Ветка `UnknownJobTypeError` не меняется (всегда `FAILED`). Политики хранятся в очереди (`dict[str, RetryPolicy]` + дефолт), политика типа заменяет дефолт целиком, без слияния. Воркер держит `self._rng = rng if rng is not None else random.Random()`.

**5. Хранилище.** `InMemoryJobStore.due` выбирает `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`. Изменение внутри `store.py`, публичная сигнатура та же.

**6. Dead-letter внутри `JobQueue`.** Список `DeadLetterEntry` (frozen dataclass в `models.py`) в порядке добавления; `dead_letters()` возвращает копию. `requeue_dead_letter` сначала находит задание (`JobNotFoundError`), затем делает переход (`InvalidTransitionError` до любых изменений), после чего выставляет `run_at = now`, `error = None`, `finished_at = None`, удаляет запись по `job_id`, увеличивает `jobs.requeued`. `attempts` не сбрасывается. Альтернатива — хранить dead-letter в `store`: потребовала бы расширять `InMemoryJobStore`, а выбранный вариант оставляет интерфейс хранилища нетронутым.

**7. Терминальность и очистка.** `DEAD_LETTERED.is_terminal == True` (воркер его не берёт), `RETRY_SCHEDULED` — нет. `purge_finished` явно пропускает `DEAD_LETTERED`, иначе запись в `dead_letters()` осталась бы без задания, а «единственный выход — requeue». `finished_at` при dead-letter ставится, при requeue сбрасывается. `cancel` допускается из `RETRY_SCHEDULED` (через таблицу переходов), из `DEAD_LETTERED` — нет.

**8. Метрики и модели.** В `metrics.py` константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` со значениями `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`; счётчик растёт внутри метода перехода, сразу после успешного `_transition`. Подписи новых статусов добавляются в `_LABELS`. Новые имена экспортируются из `jobq/__init__.py` (`RetryPolicy`, `PermanentJobError`, `DeadLetterEntry`). Публичные сигнатуры из задачи реализуются дословно, новые параметры — keyword-only после `*`.

## Risks / Trade-offs

- [Две новые строки в `stats()` и отчёте меняют вывод для потребителей] → существующие тесты проверяют статусы через перебор `JobStatus`; изменение нужно по задаче, `dashboard.py` не правим.
- [`requeue_dead_letter` сохраняет `attempts`: вернувшееся задание после первой же повторяемой ошибки снова попадёт в dead-letter, если `max_attempts` не увеличен] → осознанное допущение (в задаче перечислены только изменяемые поля); документируется в README.
- [Задание в `RETRY_SCHEDULED` можно отменить] → допущение, безопасно, задание не выполняется.
- [Dead-letter не переживает перезапуск процесса] → как и хранилище, в памяти; вне объёма.
- [`purge_finished` не удаляет dead-letter] → память освобождается только после `requeue_dead_letter`; приемлемо для малого объёма.


### proposal.md

## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий. Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py` с `RetryPolicy` (frozen dataclass: `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`), методами `delay_for(attempt, rng=None)` и `is_retryable(exc)`. Некорректные параметры — `ConfigError`.
- `jobq/errors.py`: `PermanentJobError(JobqError)` — обработчик бросает её, когда повтор точно не поможет.
- `jobq/models.py`: статусы `JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`, «Ожидает повтора») и `JobStatus.DEAD_LETTERED` (`"dead_lettered"`, «В dead-letter»); dataclass `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`.
- `jobq/queue.py`: `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy=None)`, `set_retry_policy(job_type, policy)`, `retry_policy_for(job_type)`, `dead_letters()`, `requeue_dead_letter(job_id)`; новые допустимые переходы статусов.
- `jobq/worker.py`: `Worker(queue, registry, *, name="worker", rng=None)`; при падении обработчика воркер выбирает `FAILED`, `DEAD_LETTERED` или `RETRY_SCHEDULED` по политике, действующей в момент ошибки.
- `jobq/store.py`: задания в `RETRY_SCHEDULED` с наступившим `run_at` считаются готовыми к запуску наравне с `PENDING`.
- `jobq/metrics.py`: счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Экспорт новых имён из `jobq/__init__.py`, обновление README.
- Без политики (ни дефолта очереди, ни политики типа) поведение прежнее. Существующие сигнатуры не меняются, новые параметры только keyword-only. Новых зависимостей нет.
- Не затрагиваются `jobq/dashboard.py` и `jobq/cli.py` (другая команда): отчёт перебирает `JobStatus`, поэтому подписи новых статусов попадают в него автоматически.

## Capabilities

### New Capabilities

- `retry-policy`: `RetryPolicy` — валидация параметров, расчёт задержки `delay_for` (без `OverflowError`), `is_retryable`, `PermanentJobError`.
- `job-retry`: назначение политик очереди и типов, решение воркера при падении обработчика (`FAILED` / `DEAD_LETTERED` / `RETRY_SCHEDULED`), повторный запуск по `run_at`, статусы, переходы и счётчики `jobs.retried`.
- `dead-letter`: `DeadLetterEntry`, `dead_letters()`, `requeue_dead_letter()`, счётчики `jobs.dead_lettered` и `jobs.requeued`.

### Modified Capabilities

<!-- В openspec/specs/ нет существующих спецификаций. -->

## Impact

- Код: `jobq/retry.py` (новый), `errors.py`, `models.py`, `queue.py`, `worker.py`, `store.py`, `metrics.py`, `__init__.py`, `README.md`; новые тесты в `tests/`.
- Публичный API расширяется; обратная совместимость сохраняется.
- `stats()` и отчёт дежурных получают две новые строки статусов (следствие перебора `JobStatus`).
- `purge_finished` не удаляет задания в `DEAD_LETTERED`: выход из dead-letter только через `requeue_dead_letter`.

## Допущения

- `retry_policy_for(job_type)` возвращает действующую политику: политику типа, а если её нет — дефолт очереди (или `None`).
- Попытки исчерпаны, когда `job.attempts >= policy.max_attempts`.
- `requeue_dead_letter` не сбрасывает `attempts`; у вернувшегося задания будет ещё одна попытка до повторного попадания в dead-letter, если политика не изменена.
- Отмена (`cancel`) допустима для `RETRY_SCHEDULED`, но не для `DEAD_LETTERED`.
- Если `rng` не передан и `jitter > 0`, используется собственный экземпляр `random.Random()` воркера.
- Dead-letter хранится в `JobQueue` (в памяти процесса, как и хранилище) и не восстанавливается из заданий уже заполненного `store`.


### specs/dead-letter/spec.md

## Purpose

Описывает dead-letter очередь: учёт заданий, которые исчерпали попытки, и осознанное возвращение их в работу.

## ADDED Requirements

### Requirement: Записи dead-letter
`jobq/models.py` SHALL содержать неизменяемый dataclass `DeadLetterEntry(job_id: str, job_type: str, attempts: int, error: str, dead_lettered_at: datetime)`. При переводе задания в `DEAD_LETTERED` очередь SHALL добавлять запись с идентификатором, типом, числом попыток и последней ошибкой задания и моментом по часам очереди. `JobQueue.dead_letters()` SHALL возвращать список записей в порядке попадания; возвращаемый список — копия, его изменение не влияет на очередь.

#### Scenario: Порядок записей
- **WHEN** сначала в dead-letter попало задание A, затем B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Содержимое записи
- **WHEN** задание типа `billing` с третьей попытки упало с `TimeoutError: t` в момент T
- **THEN** запись: `job_type == "billing"`, `attempts == 3`, `error == "TimeoutError: t"`, `dead_lettered_at == T`

#### Scenario: Пустой dead-letter
- **WHEN** ни одно задание не исчерпало попытки
- **THEN** `dead_letters() == []`

### Requirement: Возврат из dead-letter
`JobQueue.requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` равен текущему времени очереди, `error` очищается (`None`), запись удаляется из `dead_letters()`. Метод SHALL возвращать это задание. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`; в обоих случаях состояние очереди не меняется. Единственный выход из `DEAD_LETTERED` — `requeue_dead_letter`. Остальные поля задания (`id`, `payload`, `attempts`) не меняются.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter(job.id)` для задания в `DEAD_LETTERED`
- **THEN** возвращается тот же `Job` (тот же `id`), статус `PENDING`, `run_at == now`, `error is None`, `dead_letters()` не содержит запись, число заданий в очереди не изменилось

#### Scenario: Возвращённое задание выполняется
- **WHEN** после возврата вызывается `run_pending()`
- **THEN** задание запускается воркером

#### Scenario: Повторный возврат
- **WHEN** `requeue_dead_letter` вызывается второй раз для того же задания
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: Неизвестное задание
- **WHEN** вызывается `requeue_dead_letter("nope")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Задание не в dead-letter
- **WHEN** вызывается `requeue_dead_letter` для задания в `FAILED` или `PENDING`
- **THEN** выбрасывается `InvalidTransitionError`

### Requirement: Счётчики dead-letter
Счётчик `jobs.dead_lettered` SHALL увеличиваться на 1 ровно в момент перехода в `DEAD_LETTERED`, а `jobs.requeued` — на 1 ровно при успешном `requeue_dead_letter`. Неудачные вызовы счётчики не меняют.

#### Scenario: Счётчики
- **WHEN** задание попало в dead-letter и было возвращено
- **THEN** `jobs.dead_lettered == 1`, `jobs.requeued == 1`

#### Scenario: Неудачный возврат
- **WHEN** `requeue_dead_letter` завершился `JobNotFoundError`
- **THEN** `jobs.requeued` не изменился


### specs/job-retry/spec.md

## Purpose

Описывает назначение политик повторов очереди и типам заданий и то, как воркер при падении обработчика выбирает между повтором, `FAILED` и dead-letter.

## ADDED Requirements

### Requirement: Политики очереди и типа задания
`JobQueue` SHALL принимать keyword-only параметр `default_retry_policy: RetryPolicy | None = None`. `set_retry_policy(job_type, policy)` SHALL задавать политику для типа, а `policy=None` — снимать её. `retry_policy_for(job_type)` SHALL возвращать действующую политику: политику типа, если она задана, иначе дефолт очереди, иначе `None`. Политика типа SHALL заменять дефолт целиком, поля не сливаются. Пустой `job_type` или значение `policy`, не являющееся `RetryPolicy` или `None`, SHALL давать `ConfigError`; некорректный `default_retry_policy` в конструкторе — тоже `ConfigError`.

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** дефолт очереди `RetryPolicy(non_retryable=(ValueError,))`, а для типа `a` задана `RetryPolicy(max_attempts=5)`
- **THEN** `retry_policy_for("a")` возвращает политику с пустым `non_retryable`, а для других типов — дефолт

#### Scenario: Снятие политики типа
- **WHEN** для типа `a` вызван `set_retry_policy("a", None)`
- **THEN** `retry_policy_for("a")` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Политик нет
- **WHEN** не задано ни дефолта, ни политики типа
- **THEN** `retry_policy_for(job_type)` возвращает `None`

### Requirement: Поведение без политики не меняется
Если для типа задания не действует ни одна политика, падение обработчика SHALL переводить задание в `FAILED` с `error` в формате `"ИмяКласса: сообщение"`, как и до этого изменения. Вызовы существующих публичных методов и конструкторов без новых параметров SHALL работать как раньше.

#### Scenario: Падение без политики
- **WHEN** обработчик бросает `RuntimeError("boom")` и политик нет
- **THEN** задание в статусе `FAILED`, `error == "RuntimeError: boom"`, `jobs.retried` и `jobs.dead_lettered` равны 0

### Requirement: Решение воркера при падении обработчика
Когда обработчик бросил исключение (`Exception`), воркер SHALL использовать политику, действующую в момент ошибки (а не в момент постановки), и определять итоговый статус так:
1. политики нет → `FAILED`;
2. ошибка неповторяемая (`is_retryable` вернул `False`) → `FAILED`, в том числе на последней попытке, и в dead-letter такое задание не попадает;
3. иначе, если `job.attempts >= max_attempts` → `DEAD_LETTERED` и появляется запись в `dead_letters()`;
4. иначе → `RETRY_SCHEDULED` с `run_at` = текущее время очереди + `delay_for(job.attempts, rng)`.

Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. `max_attempts=1` означает «без повторов, но в dead-letter»: первая повторяемая ошибка даёт `DEAD_LETTERED`.

#### Scenario: Повтор запланирован
- **WHEN** действует `RetryPolicy(max_attempts=3, base_delay=2, jitter=0)`, первая попытка падает с `TimeoutError("t")`
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равен «сейчас + 2 с», `error == "TimeoutError: t"`, `jobs.retried == 1`

#### Scenario: Попытки исчерпаны
- **WHEN** `max_attempts=3` и третья попытка падает с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` появилась запись, `jobs.dead_lettered == 1`

#### Scenario: max_attempts равно 1
- **WHEN** `max_attempts=1` и первая попытка падает с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, повтор не планируется

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** `non_retryable=(ValueError,)`, попытка — последняя, обработчик бросает наследника `ValueError`
- **THEN** статус `FAILED`, запись в dead-letter не создаётся

#### Scenario: PermanentJobError даёт FAILED
- **WHEN** обработчик бросает `PermanentJobError("no")` при действующей политике
- **THEN** статус `FAILED`

#### Scenario: Нет обработчика для типа
- **WHEN** для типа задания не зарегистрирован обработчик, даже при действующей политике
- **THEN** задание сразу получает `FAILED`, повтор не планируется

#### Scenario: Политика берётся в момент ошибки
- **WHEN** после постановки задания, но до падения обработчика, политика типа снята или заменена
- **THEN** решение принимается по политике, действующей при падении

### Requirement: Использование генератора случайных чисел
`Worker` SHALL принимать keyword-only параметр `rng: random.Random | None = None` (рядом с `name`) и передавать его в `delay_for`. Воркер SHALL обращаться к `rng` только когда реально планируется повтор: не более одного `uniform` на запланированную задержку и ни одного при `jitter == 0`, при `FAILED` и при dead-letter.

#### Scenario: FAILED и dead-letter не расходуют rng
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED` при `jitter > 0`
- **THEN** `rng` не используется

#### Scenario: Предсказуемый jitter
- **WHEN** планируется повтор при `jitter > 0` и передан `random.Random(seed)`
- **THEN** `run_at` равен «сейчас + delay_for(job.attempts, тот же rng с тем же состоянием)», использован ровно один `uniform`

### Requirement: Повторный запуск задания
Задание в `RETRY_SCHEDULED` SHALL браться воркером, когда наступил его `run_at` (`run_at <= now`), наравне с остальными готовыми заданиями (порядок: `run_at`, затем порядок постановки). До этого момента оно SHALL не выбираться. При каждом запуске `attempts` увеличивается, как и раньше. После успешного повтора задание SHALL получать `SUCCEEDED` и `error == None`.

#### Scenario: Задание ждёт run_at
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at` в будущем
- **THEN** `run_pending()` его не запускает; после `clock.advance` до `run_at` запускает

#### Scenario: Успех после повтора
- **WHEN** первая попытка упала, вторая прошла успешно
- **THEN** статус `SUCCEEDED`, `attempts == 2`, `error is None`

### Requirement: Новые статусы и переходы
`JobStatus` SHALL содержать `RETRY_SCHEDULED = "retry_scheduled"` с подписью «Ожидает повтора» и `DEAD_LETTERED = "dead_lettered"` с подписью «В dead-letter». `stats()` SHALL содержать ключи для обоих статусов. `RETRY_SCHEDULED` не терминален; из него возможны запуск и отмена. `DEAD_LETTERED` не берётся воркером, не отменяется и не удаляется `purge_finished`. Недопустимый по таблице переход SHALL давать `InvalidTransitionError`.

#### Scenario: Подписи и stats
- **WHEN** запрашиваются `JobStatus.RETRY_SCHEDULED.label`, `JobStatus.DEAD_LETTERED.label` и `queue.stats()`
- **THEN** подписи «Ожидает повтора» и «В dead-letter», в `stats()` есть ключи `retry_scheduled` и `dead_lettered`

#### Scenario: Отмена задания, ожидающего повтора
- **WHEN** вызывается `cancel` для задания в `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`

#### Scenario: Отмена задания в dead-letter
- **WHEN** вызывается `cancel` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: purge не трогает dead-letter
- **WHEN** вызывается `purge_finished()` при наличии задания в `DEAD_LETTERED`
- **THEN** задание остаётся в хранилище

### Requirement: Счётчик jobs.retried
Счётчик `jobs.retried` SHALL увеличиваться на 1 ровно в момент перехода задания в `RETRY_SCHEDULED`, по тем же правилам, что и существующие счётчики статусов (счётчик `jobs.failed` при этом не растёт).

#### Scenario: Подсчёт повторов
- **WHEN** задание дважды подряд уходит в `RETRY_SCHEDULED`, а затем завершается успехом
- **THEN** `jobs.retried == 2`, `jobs.started == 3`, `jobs.succeeded == 1`, `jobs.failed == 0`


### specs/retry-policy/spec.md

## Purpose

Описывает политику повторов `RetryPolicy`: допустимые параметры, расчёт задержки перед следующей попыткой и классификацию ошибок на повторяемые и неповторяемые.

## ADDED Requirements

### Requirement: Параметры RetryPolicy и значения по умолчанию
`RetryPolicy` из `jobq/retry.py` SHALL быть неизменяемым dataclass с полями `max_attempts: int = 3` (всего попыток, включая первую), `base_delay: float = 1.0`, `factor: float = 2.0`, `max_delay: float = 60.0`, `jitter: float = 0.0`, `non_retryable: tuple[type[BaseException], ...] = ()`. Значение `non_retryable` SHALL приниматься в виде списка или кортежа и храниться как `tuple`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список превращается в tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `policy.non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Политика неизменяема
- **WHEN** код присваивает полю созданной политики новое значение
- **THEN** присваивание отклоняется

### Requirement: Валидация параметров как ошибка конфигурации
Создание `RetryPolicy` с некорректными параметрами SHALL выбрасывать `ConfigError`. Некорректны: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент `non_retryable`, который не является классом исключения (наследником `BaseException`). Граничные значения (`max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay == base_delay`, `jitter` равный 0 или 1) SHALL быть допустимы. Значение NaN в числовых параметрах SHALL считаться некорректным. Встроенные `ValueError`/`TypeError` наружу не выпускаются.

#### Scenario: Недопустимые числовые параметры
- **WHEN** создаётся политика с `max_attempts=0`, либо `base_delay=-1`, либо `factor=0.5`, либо `max_delay=0.5` при `base_delay=1.0`, либо `jitter=1.5`, либо `jitter=-0.1`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** создаётся политика с `non_retryable=(ValueError("x"),)` или `non_retryable=("ValueError",)` или `non_retryable=(int,)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся `RetryPolicy(max_attempts=1, base_delay=0, factor=1, max_delay=0, jitter=1)`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки delay_for
`delay_for(attempt, rng=None)` SHALL возвращать в секундах задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, причём `uniform` вызывается ровно один раз на вызов; при `jitter == 0` `rng` SHALL не использоваться. При `attempt < 1` SHALL выбрасываться `ConfigError`. Метод SHALL работать для любого `attempt` (в том числе очень большого) и любых допустимых параметров, включая `base_delay == 0`, без `OverflowError`: слишком большое значение даёт `max_delay`, а при `base_delay == 0` результат равен 0.

#### Scenario: Экспоненциальный рост и ограничение
- **WHEN** политика `RetryPolicy(base_delay=1, factor=2, max_delay=10)`
- **THEN** `delay_for(1) == 1`, `delay_for(2) == 2`, `delay_for(3) == 4`, `delay_for(5) == 10`

#### Scenario: Очень большой номер попытки
- **WHEN** вызывается `delay_for(5000)` (или `delay_for(10**9)`) для политики с `factor=2.0` и `max_attempts=10000`
- **THEN** возвращается `max_delay` и `OverflowError` не возникает

#### Scenario: Нулевая базовая задержка
- **WHEN** политика с `base_delay=0` и вызывается `delay_for(5000)`
- **THEN** возвращается `0` (а не `NaN`) и ошибки нет

#### Scenario: Jitter применяется после ограничения
- **WHEN** политика с `max_delay=10`, `jitter=0.5`, ограниченная задержка равна 10, а `rng.uniform(0.5, 1.5)` вернул 1.2
- **THEN** `delay_for` возвращает 12

#### Scenario: Без jitter генератор не трогается
- **WHEN** `jitter == 0` и передан `rng`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Один uniform на задержку
- **WHEN** `jitter > 0` и `delay_for` вызван один раз
- **THEN** `rng.uniform` вызван ровно один раз с аргументами `(1 - jitter, 1 + jitter)`

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок is_retryable
`is_retryable(exc)` SHALL возвращать `False`, если `exc` является экземпляром одного из классов `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError` и её наследников независимо от `non_retryable`. Для остальных исключений SHALL возвращаться `True`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и проверяется исключение подкласса `ValueError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Остальные ошибки повторяемы
- **WHEN** `non_retryable=(ValueError,)` и проверяется `TimeoutError`
- **THEN** `is_retryable` возвращает `True`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** проверяется `PermanentJobError("no")` при пустом `non_retryable`
- **THEN** `is_retryable` возвращает `False`

### Requirement: Исключение PermanentJobError
Модуль `jobq/errors.py` SHALL содержать `PermanentJobError`, наследующий `JobqError`. Обработчик бросает его, когда точно знает, что повтор не поможет.

#### Scenario: Иерархия
- **WHEN** проверяется `issubclass(PermanentJobError, JobqError)`
- **THEN** результат `True`


### tasks.md

## 1. Базовые типы

- [ ] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` тестом
- [ ] 1.2 В `jobq/models.py` добавить `JobStatus.RETRY_SCHEDULED`, `JobStatus.DEAD_LETTERED`, подписи «Ожидает повтора» и «В dead-letter», `is_terminal` (True только для DEAD_LETTERED из новых) и frozen dataclass `DeadLetterEntry`; проверить тестом подписей и флагов терминальности
- [ ] 1.3 В `jobq/metrics.py` добавить константы `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` и дополнить описание в docstring; проверить, что константы доступны и неизвестные счётчики читаются как 0

## 2. RetryPolicy

- [ ] 2.1 Создать `jobq/retry.py` с `RetryPolicy` (поля, значения по умолчанию, frozen, нормализация `non_retryable` в tuple, валидация с `ConfigError`, включая NaN и не-классы); проверить тестами на каждое некорректное значение и на граничные допустимые
- [ ] 2.2 Реализовать `delay_for` без `OverflowError` (`attempt` 5000 и 10**9, `base_delay=0`, `factor=1`, ограничение `max_delay`, jitter после ограничения, один `uniform`, `rng` не трогается при `jitter=0`, `ConfigError` при `attempt < 1`); проверить unit-тестами со стаб-`rng`
- [ ] 2.3 Реализовать `is_retryable` (наследование `non_retryable`, `PermanentJobError` всегда False); проверить тестами

## 3. Очередь и хранилище

- [ ] 3.1 В `InMemoryJobStore.due` включить `RETRY_SCHEDULED`; проверить, что задание выбирается только при `run_at <= now`, порядок `(run_at, seq)` сохранён
- [ ] 3.2 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` (политика типа заменяет дефолт целиком, `ConfigError` на некорректные аргументы); проверить тестами, включая снятие политики и отсутствие слияния
- [ ] 3.3 Расширить `_TRANSITIONS`, добавить `mark_retry_scheduled` и `mark_dead_lettered` (запись `error`, `run_at`, `finished_at`, запись в dead-letter, счётчики `jobs.retried`/`jobs.dead_lettered`), очистку `error` в `mark_succeeded`; проверить тестами переходов, счётчиков и `InvalidTransitionError`
- [ ] 3.4 Реализовать `dead_letters()` (копия, порядок попадания) и `requeue_dead_letter` (то же задание, `PENDING`, `run_at=now`, `error=None`, удаление записи, `jobs.requeued`, ошибки без побочных эффектов); `purge_finished` пропускает `DEAD_LETTERED`; проверить тестами

## 4. Воркер

- [ ] 4.1 Добавить в `Worker` keyword-only `rng` и цепочку решений при падении обработчика (нет политики / неповторяемая → FAILED, исчерпано → DEAD_LETTERED, иначе RETRY_SCHEDULED с `delay_for(job.attempts, rng)`; нет обработчика → FAILED; политика берётся в момент ошибки); проверить тестами worker, включая `max_attempts=1`, неповторяемую ошибку на последней попытке и наследников
- [ ] 4.2 Проверить тестом с подсчитывающим `rng`, что `uniform` вызывается ровно один раз только при планировании повтора и ни разу при `jitter=0`, FAILED и dead-letter
- [ ] 4.3 Сквозной тест: упавшее задание повторяется после `clock.advance`, успех очищает `error`, dead-letter → `requeue_dead_letter` → повторное выполнение; проверить значения счётчиков

## 5. Оформление

- [ ] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`, обновить таблицу модулей и описание повторов в `README.md`; проверить импортом из `jobq`
- [ ] 5.2 Запустить `python -m pytest -q`: существующие тесты не изменены и проходят, `git diff` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты, отчёт `render_report` содержит подписи новых статусов
- [ ] 5.3 Сверить публичный API реализации с proposal и specs (имена, порядок и вид параметров, keyword-only, значения enum `"retry_scheduled"`/`"dead_lettered"`, поля `DeadLetterEntry`, имена счётчиков) и устранить расхождения
