## Purpose

Описывает, как очередь хранит политики повторов и как воркер обрабатывает падение обработчика: выбор статуса, время следующего запуска, счётчики и отображение в отчёте.

## ADDED Requirements

### Requirement: Настройка политик в очереди
Очередь SHALL принимать `default_retry_policy` (keyword-only, по умолчанию `None`), позволять задавать политику типа задания через `set_retry_policy(job_type, policy)` (`None` снимает политику типа) и возвращать действующую политику через `retry_policy_for(job_type)`. Политика типа MUST полностью заменять политику по умолчанию, без слияния полей. Если нет ни той, ни другой, `retry_policy_for` возвращает `None`. Значение, не являющееся `RetryPolicy` или `None`, а также пустой `job_type` MUST приводить к `ConfigError`.

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** у очереди дефолт `RetryPolicy(non_retryable=(ValueError,))`, а для типа `a` задана `RetryPolicy(max_attempts=5)`
- **THEN** `retry_policy_for("a")` возвращает политику типа с пустым `non_retryable`, а для другого типа — дефолт

#### Scenario: Снятие политики типа
- **WHEN** для типа задана политика и затем вызван `set_retry_policy(type, None)`
- **THEN** `retry_policy_for(type)` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Совместимость
- **WHEN** очередь создаётся как раньше, без новых параметров
- **THEN** все существующие вызовы работают без изменений

### Requirement: Исход падения обработчика
Когда обработчик бросил `Exception`, воркер SHALL использовать политику, действующую в момент ошибки (а не в момент постановки), и выбрать исход в таком порядке:
1. политики нет → `FAILED` (как раньше);
2. ошибка неповторяемая (`is_retryable` ложно) → `FAILED`, в том числе на последней попытке; в dead-letter такие задания не попадают;
3. `job.attempts >= max_attempts` → `DEAD_LETTERED` и запись в dead-letter;
4. иначе → `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`.

В `job.error` MUST всегда лежать последняя ошибка в формате `"ИмяКласса: сообщение"`. При `max_attempts=1` первое же падение повторяемой ошибкой даёт `DEAD_LETTERED`, а не `FAILED`.

#### Scenario: Повтор запланирован
- **WHEN** политика `max_attempts=3, base_delay=1, factor=2`, обработчик упал с `TimeoutError("gw")` на первой попытке в момент T
- **THEN** статус `RETRY_SCHEDULED`, `run_at = T + 1s`, `error = "TimeoutError: gw"`, `attempts = 1`

#### Scenario: Попытки кончились
- **WHEN** обработчик падает повторяемой ошибкой на третьей попытке при `max_attempts=3`
- **THEN** статус `DEAD_LETTERED`, появляется запись в `dead_letters()`, повтор не планируется

#### Scenario: max_attempts=1
- **WHEN** политика с `max_attempts=1` и обработчик упал повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик бросил `PermanentJobError` (или класс из `non_retryable`) на любой попытке, в том числе последней
- **THEN** статус `FAILED`, запись в dead-letter не добавляется

#### Scenario: Нет обработчика для типа
- **WHEN** для типа задания не зарегистрирован обработчик, даже при действующей политике
- **THEN** задание сразу получает `FAILED` без повторов

#### Scenario: Политика берётся на момент ошибки
- **WHEN** между постановкой и падением политика типа была изменена или снята
- **THEN** решение принимается по политике, действующей в момент падения

#### Scenario: Без политики
- **WHEN** ни дефолта, ни политики типа нет и обработчик упал
- **THEN** задание получает `FAILED`, как и до изменения

### Requirement: Использование rng воркером
Воркер SHALL принимать keyword-only `rng: random.Random | None`. `rng` MUST использоваться только при планировании повтора: один вызов `uniform` на одну задержку при `jitter > 0`, ни одного при `jitter = 0`. При исходах `FAILED` и `DEAD_LETTERED` задержка не вычисляется и `rng` не трогается.

#### Scenario: Предсказуемый rng
- **WHEN** воркер создан с `random.Random(seed)`, `jitter>0`, и запланирован один повтор
- **THEN** `run_at` равен `now + delay_for(attempts, Random(seed))` для того же seed

#### Scenario: rng не расходуется без повтора
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED`
- **THEN** состояние `rng` не меняется

### Requirement: Повторный запуск и успех после повтора
Задание в `RETRY_SCHEDULED` SHALL браться воркером, когда `run_at <= now`, наравне с `PENDING` (порядок по `run_at`, затем по порядку постановки); раньше этого момента не берётся. Повторный запуск увеличивает `attempts`. Если повтор завершился успехом, статус `SUCCEEDED` и `error` MUST быть `None`.

#### Scenario: Ещё рано
- **WHEN** часы не дошли до `run_at` задания в `RETRY_SCHEDULED`
- **THEN** `run_once` возвращает `None` и задание не запускается

#### Scenario: Успех после повтора
- **WHEN** первая попытка упала, а вторая прошла успешно
- **THEN** статус `SUCCEEDED`, `attempts = 2`, `error = None`

### Requirement: Отмена ожидающего повтора
Задание в `RETRY_SCHEDULED` SHALL отменяться через `cancel` так же, как `PENDING` (статус `CANCELLED`, счётчик `jobs.cancelled`). Отмена задания в `DEAD_LETTERED` MUST отклоняться с `InvalidTransitionError`.

#### Scenario: Отмена повтора
- **WHEN** вызван `cancel` для задания в `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`, воркер его больше не берёт

#### Scenario: Отмена dead-letter
- **WHEN** вызван `cancel` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`, статус не меняется

### Requirement: Счётчики и отчёт
Счётчики `jobs.retried` и `jobs.dead_lettered` SHALL увеличиваться ровно в момент перехода в `RETRY_SCHEDULED` и `DEAD_LETTERED` соответственно (по тем же правилам, что `jobs.failed`); `jobs.started` увеличивается при каждом запуске, включая повторные. `jobs.failed` не увеличивается для заданий, ушедших в повтор или dead-letter. `JobQueue.stats()` MUST содержать ключи `retry_scheduled` и `dead_lettered`. Подписи статусов в отчёте дежурных: «Ожидает повтора» и «В dead-letter».

#### Scenario: Счётчики при повторе и dead-letter
- **WHEN** задание дважды упало повторяемой ошибкой и ушло в dead-letter при `max_attempts=2`
- **THEN** `jobs.retried = 1`, `jobs.dead_lettered = 1`, `jobs.failed = 0`, `jobs.started = 2`

#### Scenario: Подписи в отчёте
- **WHEN** формируется отчёт дежурных
- **THEN** в нём есть строки «Ожидает повтора» и «В dead-letter» с количеством заданий, без изменений в модуле отчёта
