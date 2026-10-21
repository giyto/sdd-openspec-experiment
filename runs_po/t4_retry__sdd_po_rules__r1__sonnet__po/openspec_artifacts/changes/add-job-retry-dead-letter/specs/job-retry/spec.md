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
