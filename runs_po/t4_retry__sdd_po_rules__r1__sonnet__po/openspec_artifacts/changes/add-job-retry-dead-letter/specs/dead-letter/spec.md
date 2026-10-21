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
`JobQueue.requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` равен текущему времени очереди, `error` очищается (`None`), запись удаляется из `dead_letters()`. Метод SHALL возвращать это задание. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`; в обоих случаях состояние очереди не меняется. Единственный выход из `DEAD_LETTERED` — `requeue_dead_letter`. Счётчик `attempts` SHALL сбрасываться в 0, так что у задания снова полный набор попыток, как у нового. Остальные поля задания (`id`, `payload`) не меняются.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter(job.id)` для задания в `DEAD_LETTERED`
- **THEN** возвращается тот же `Job` (тот же `id`), статус `PENDING`, `run_at == now`, `error is None`, `attempts == 0`, `dead_letters()` не содержит запись, число заданий в очереди не изменилось

#### Scenario: Возвращённое задание выполняется
- **WHEN** после возврата вызывается `run_pending()`
- **THEN** задание запускается воркером

#### Scenario: Полный набор попыток после возврата
- **WHEN** задание с `max_attempts=3` попало в dead-letter, было возвращено, и первая же попытка снова падает с повторяемой ошибкой
- **THEN** статус `RETRY_SCHEDULED`, `attempts == 1`, в dead-letter задание не попадает

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
