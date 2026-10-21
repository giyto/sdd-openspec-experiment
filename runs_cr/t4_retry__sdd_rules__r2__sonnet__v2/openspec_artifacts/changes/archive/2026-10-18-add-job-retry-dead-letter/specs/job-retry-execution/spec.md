## Purpose

Определяет, как очередь и воркер выбирают политику повторов и что происходит с заданием при падении обработчика: `FAILED`, ожидание повтора или dead-letter.

## ADDED Requirements

### Requirement: Конфигурация политик повторов в очереди
`JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy: RetryPolicy | None = None)` SHALL принимать политику по умолчанию только как keyword-only параметр; существующие вызовы конструктора MUST работать как раньше. `JobQueue.set_retry_policy(job_type, policy)` SHALL задавать политику для типа задания, `policy=None` снимает политику типа. `JobQueue.retry_policy_for(job_type)` SHALL возвращать действующую политику: политику типа, если она задана, иначе политику очереди по умолчанию, иначе `None`. Политика типа заменяет дефолт целиком, поля не сливаются. Пустой `job_type` и значение, не являющееся `RetryPolicy` или `None`, SHALL давать `ConfigError` (так же для `default_retry_policy`).

#### Scenario: Политика типа заменяет дефолт
- **WHEN** у очереди `default_retry_policy=RetryPolicy(non_retryable=(ValueError,))`, для типа `a` задано `RetryPolicy(max_attempts=5)`
- **THEN** `retry_policy_for("a")` возвращает политику типа с пустым `non_retryable`, а `retry_policy_for("b")` возвращает дефолт

#### Scenario: Снятие политики типа
- **WHEN** для типа `a` задана политика, затем вызван `set_retry_policy("a", None)`
- **THEN** `retry_policy_for("a")` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Политик нет
- **WHEN** очередь создана без `default_retry_policy` и политика типа не задана
- **THEN** `retry_policy_for(job_type)` возвращает `None`

#### Scenario: Некорректный аргумент
- **WHEN** вызывается `set_retry_policy("a", "oops")` или `set_retry_policy("", RetryPolicy())`
- **THEN** выбрасывается `ConfigError`

### Requirement: Решение воркера при падении обработчика
Когда обработчик бросил исключение (`Exception`), воркер SHALL выбрать итоговый статус по политике, действующей в момент ошибки (а не при постановке), в таком порядке: (1) политики нет — `FAILED` (поведение до этого изменения); (2) ошибка неповторяемая по `is_retryable` — `FAILED`, в том числе на последней попытке; (3) `job.attempts >= max_attempts` — `DEAD_LETTERED`; (4) иначе `RETRY_SCHEDULED`. В `job.error` MUST лежать последняя ошибка в формате `"ИмяКласса: сообщение"`. `max_attempts=1` означает «без повторов, но в dead-letter», а не в `FAILED` (если ошибка повторяемая).

#### Scenario: Без политики — как раньше
- **WHEN** политик нет и обработчик бросает `RuntimeError("boom")`
- **THEN** задание получает статус `FAILED`, `error == "RuntimeError: boom"`, счётчики `jobs.retried` и `jobs.dead_lettered` равны 0

#### Scenario: Повторяемая ошибка планирует повтор
- **WHEN** действует `RetryPolicy(max_attempts=3)` и обработчик бросает `TimeoutError("gw")` на первой попытке
- **THEN** статус задания `RETRY_SCHEDULED`, `attempts == 1`, `error == "TimeoutError: gw"`

#### Scenario: Попытки кончились
- **WHEN** действует `RetryPolicy(max_attempts=3)` и обработчик падает повторяемой ошибкой на третьей попытке
- **THEN** статус `DEAD_LETTERED`, `attempts == 3`, `error` содержит последнюю ошибку

#### Scenario: max_attempts=1 ведёт в dead-letter
- **WHEN** действует `RetryPolicy(max_attempts=1)` и обработчик падает повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** действует политика и обработчик бросает `PermanentJobError("bad")`
- **THEN** статус `FAILED`, запись в `dead_letters()` не создаётся, `jobs.retried` не растёт

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** `max_attempts=3`, `non_retryable=(ValueError,)` и на третьей попытке обработчик бросает `ValueError`
- **THEN** статус `FAILED`, в dead-letter задание не попадает

#### Scenario: Наследник неповторяемой ошибки
- **WHEN** `non_retryable=(ValueError,)` и обработчик бросает наследника `ValueError`
- **THEN** статус `FAILED`

#### Scenario: Политика берётся на момент ошибки
- **WHEN** задание поставлено без политики, затем до запуска вызван `set_retry_policy` для его типа, и обработчик падает
- **THEN** применяется заданная политика, и задание получает `RETRY_SCHEDULED`

#### Scenario: Нет обработчика — не повторяем
- **WHEN** для типа задания нет зарегистрированного обработчика, а политика действует
- **THEN** задание сразу получает `FAILED` с ошибкой `UnknownJobTypeError`, `rng` не используется, повтор не планируется

### Requirement: Планирование повтора
При переходе в `RETRY_SCHEDULED` воркер SHALL установить `run_at = now + delay_for(job.attempts, rng)`, где `now` — текущее время часов очереди, а `rng` — генератор, переданный в `Worker(queue, registry, *, name="worker", rng: random.Random | None = None)`. `rng` MUST использоваться только при реальном планировании повтора: для заданий, ушедших в `FAILED` или `DEAD_LETTERED`, задержка не считается и `rng` не вызывается. Задание в `RETRY_SCHEDULED` воркер SHALL брать в работу, когда наступил его `run_at`, наравне с `PENDING` (порядок по `run_at`, затем по порядку постановки); раньше `run_at` оно не выбирается.

#### Scenario: Время следующей попытки
- **WHEN** задание упало на второй попытке, `RetryPolicy(base_delay=1.0, factor=2.0)`, часы показывают T
- **THEN** `run_at == T + 2 секунды`

#### Scenario: Повтор не выбирается раньше срока
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at = T + 2s`, часы показывают `T + 1s`
- **THEN** `run_pending()` возвращает 0, задание остаётся в `RETRY_SCHEDULED`

#### Scenario: Повтор выполняется в срок
- **WHEN** часы сдвинуты до `T + 2s` и следующая попытка успешна
- **THEN** задание проходит `RUNNING` и становится `SUCCEEDED`, `error is None`

#### Scenario: rng не трогается без повтора
- **WHEN** `jitter > 0`, задание уходит в `FAILED` или `DEAD_LETTERED`
- **THEN** подсчитывающий `rng` не вызван ни разу

#### Scenario: Один uniform на один повтор
- **WHEN** `jitter > 0` и задание уходит в `RETRY_SCHEDULED`
- **THEN** `rng.uniform` вызван ровно один раз

### Requirement: Отмена ожидающего повтора и переходы
Задание в `RETRY_SCHEDULED` SHALL отменяться через `JobQueue.cancel` так же, как обычное ожидающее: статус `CANCELLED`, `jobs.cancelled` увеличивается. Допустимые переходы: `RUNNING → RETRY_SCHEDULED | DEAD_LETTERED`, `RETRY_SCHEDULED → RUNNING | CANCELLED`. Все прочие переходы из новых статусов MUST отклоняться `InvalidTransitionError`.

#### Scenario: Отмена задания, ожидающего повтора
- **WHEN** задание в `RETRY_SCHEDULED` и вызывается `cancel(job_id)`
- **THEN** статус `CANCELLED`, воркер его больше не берёт

### Requirement: Метрики повторов
Счётчик `jobs.retried` SHALL увеличиваться ровно в момент перехода задания в `RETRY_SCHEDULED` — по тем же правилам, что и существующие счётчики статусов. `jobs.started` продолжает считать каждый запуск обработчика, `jobs.failed` — только переходы в `FAILED`.

#### Scenario: Счётчики при двух повторах и успехе
- **WHEN** обработчик дважды падает повторяемой ошибкой при `max_attempts=3`, затем успешен
- **THEN** `jobs.started == 3`, `jobs.retried == 2`, `jobs.succeeded == 1`, `jobs.failed == 0`, `jobs.dead_lettered == 0`

### Requirement: Обратная совместимость
Сигнатуры существующих публичных методов MUST NOT меняться; новые параметры только keyword-only. Новые публичные имена (`RetryPolicy`, `PermanentJobError`, `DeadLetterEntry`) SHALL экспортироваться из пакета `jobq`. `jobq/dashboard.py` и `jobq/cli.py` MUST NOT изменяться.

#### Scenario: Старые вызовы
- **WHEN** используются `JobQueue()`, `JobQueue(store, clock=c, metrics=m)`, `Worker(queue, registry)`, `Worker(queue, registry, name="w")`
- **THEN** они работают как до изменения
