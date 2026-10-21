## Purpose

Описывает, как воркер реагирует на падение обработчика при наличии политики повторов: выбор итогового статуса, планирование следующей попытки, использование генератора случайных чисел, новые статусы и счётчик повторов.

## ADDED Requirements

### Requirement: Новые статусы заданий
`JobStatus` SHALL содержать значения `RETRY_SCHEDULED = "retry_scheduled"` и `DEAD_LETTERED = "dead_lettered"` с подписями для отчёта дежурных `«Ожидает повтора»` и `«В dead-letter»` соответственно. `queue.stats()` SHALL включать новые статусы по их значениям. Оба статуса SHALL NOT считаться терминальными (`is_terminal == False`), и `purge_finished` SHALL NOT удалять задания в этих статусах. `dashboard.py` и `cli.py` не изменяются.

#### Scenario: Значения и подписи
- **WHEN** читаются `JobStatus.RETRY_SCHEDULED.value`, `JobStatus.DEAD_LETTERED.value` и их `label`
- **THEN** получаем `"retry_scheduled"`, `"dead_lettered"`, `"Ожидает повтора"`, `"В dead-letter"`

#### Scenario: Статусы в отчёте и stats
- **WHEN** строится `stats()` и `render_report(queue)`
- **THEN** в `stats()` есть ключи `"retry_scheduled"` и `"dead_lettered"`, а в отчёте — строки с подписями «Ожидает повтора» и «В dead-letter»

#### Scenario: Очистка не трогает ожидающие и dead-letter
- **WHEN** есть задания в `RETRY_SCHEDULED` и `DEAD_LETTERED`, вызывается `purge_finished()`
- **THEN** они остаются в хранилище

### Requirement: Исход упавшего задания
Когда обработчик бросил исключение `exc`, воркер SHALL определить политику через `queue.retry_policy_for(job.job_type)` на момент ошибки (а не на момент постановки) и перевести задание так:
1. политики нет — `FAILED`, как до изменения;
2. `policy.is_retryable(exc)` ложно — `FAILED`, даже если это последняя попытка; в dead-letter такое задание не попадает;
3. иначе, если `job.attempts >= policy.max_attempts` — `DEAD_LETTERED` и появляется запись в `dead_letters()`;
4. иначе — `RETRY_SCHEDULED` с `run_at` = текущее время очереди + `policy.delay_for(job.attempts, rng)`.

Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. Отсутствие обработчика для типа задания SHALL приводить к `FAILED` сразу, без повторов и независимо от политики.

#### Scenario: Повтор после временной ошибки
- **WHEN** политика `RetryPolicy(max_attempts=3, base_delay=2, factor=2, jitter=0)`, обработчик бросил `TimeoutError("gw")` на первой попытке в момент `T`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 2 с`, `error == "TimeoutError: gw"`, `attempts == 1`

#### Scenario: Задержка растёт с номером попытки
- **WHEN** вторая попытка упала в момент `T2` при той же политике
- **THEN** `run_at == T2 + 4 с`

#### Scenario: Попытки кончились
- **WHEN** `max_attempts=3` и упала третья попытка
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` одна запись для этого задания, `error` — последняя ошибка

#### Scenario: max_attempts=1 означает без повторов, но в dead-letter
- **WHEN** `max_attempts=1` и первая попытка упала повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка всегда FAILED
- **WHEN** `non_retryable=(ValueError,)` и обработчик бросил наследника `ValueError` — на первой или на последней попытке
- **THEN** статус `FAILED`, записи в dead-letter нет

#### Scenario: PermanentJobError
- **WHEN** обработчик бросил `PermanentJobError("no")` при любой политике
- **THEN** статус `FAILED`

#### Scenario: Нет политики
- **WHEN** нет ни дефолтной политики, ни политики типа и обработчик упал
- **THEN** статус `FAILED`, `error` заполнен, повторов нет

#### Scenario: Нет обработчика
- **WHEN** для типа задания не зарегистрирован обработчик, политика задана
- **THEN** статус `FAILED` сразу, `RETRY_SCHEDULED` и dead-letter не используются

#### Scenario: Политика берётся на момент ошибки
- **WHEN** после постановки задания, но до его падения, политика типа изменена или снята
- **THEN** исход определяется новой действующей политикой

### Requirement: Использование rng воркером
`Worker.__init__` SHALL принимать keyword-only параметр `rng: random.Random | None = None` (после `name`), существующие вызовы остаются валидными. Воркер SHALL передавать `rng` в `delay_for` только когда реально планирует повтор: при `FAILED` и `DEAD_LETTERED` задержка не считается и `rng` не используется; при `jitter == 0` `rng` не используется; при `jitter > 0` на один запланированный повтор приходится ровно один вызов `rng.uniform`.

#### Scenario: Предсказуемый rng
- **WHEN** `jitter=0.5`, воркер создан с `rng`, запланирован один повтор
- **THEN** `rng.uniform` вызван ровно один раз, а `run_at` равен сейчас плюс ограниченная задержка, умноженная на его результат

#### Scenario: rng не трогается без повтора
- **WHEN** задание ушло в `FAILED` или `DEAD_LETTERED`, либо `jitter == 0`
- **THEN** `rng` не использован

### Requirement: Выбор заданий в RETRY_SCHEDULED
Воркер SHALL брать задание в `RETRY_SCHEDULED`, когда `run_at <= now`, наравне с `PENDING` по общему порядку `(run_at, seq)`; раньше `run_at` задание не берётся. Взятое задание проходит обычный запуск (`attempts` увеличивается, статус `RUNNING`). При успехе статус становится `SUCCEEDED`, а `error` — `None`. Задание в `RETRY_SCHEDULED` можно отменить (`cancel`).

#### Scenario: Ожидание run_at
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at = T + 2 с`, текущее время `T + 1 с`
- **THEN** `worker.run_once()` возвращает `None`; после `clock.advance` до `T + 2 с` задание выполняется

#### Scenario: Успех после повтора
- **WHEN** первая попытка упала, вторая прошла успешно
- **THEN** статус `SUCCEEDED`, `attempts == 2`, `error is None`

#### Scenario: Общий порядок
- **WHEN** готовы задания `PENDING` и `RETRY_SCHEDULED`
- **THEN** первым берётся то, у которого меньше `(run_at, seq)`

#### Scenario: Отмена ожидающего повтора
- **WHEN** вызывается `cancel` для задания в `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`

### Requirement: Счётчик jobs.retried
Счётчик `jobs.retried` SHALL увеличиваться ровно на 1 в момент перехода задания в `RETRY_SCHEDULED` (как существующие счётчики статусов) и больше нигде. Остальные счётчики (`jobs.started`, `jobs.failed`, `jobs.succeeded` и т. д.) работают как прежде; `jobs.failed` не растёт при переходе в `RETRY_SCHEDULED` и `DEAD_LETTERED`.

#### Scenario: Подсчёт
- **WHEN** задание падает дважды с повтором и затем успешно выполняется
- **THEN** `jobs.retried == 2`, `jobs.started == 3`, `jobs.succeeded == 1`, `jobs.failed == 0`
