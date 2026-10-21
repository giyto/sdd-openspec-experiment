## ADDED Requirements

### Requirement: Массовый возврат из dead-letter
`JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]` SHALL перезапустить все задания из dead-letter (при `job_type=None`) или только задания указанного типа, причём каждое — ровно так же, как `requeue_dead_letter` (тот же `Job`, `PENDING`, `run_at` равен текущему времени часов, `error is None`, `attempts == 0`, запись удалена, `jobs.requeued` +1 за каждое задание). Задания SHALL перезапускаться и возвращаться в порядке `dead_letters()` на момент вызова. Если перезапускать нечего (dead-letter пуст или заданий нужного типа нет), метод MUST вернуть `[]`, не менять состояние и не изменять `jobs.requeued`. Существующий метод `requeue_dead_letter` не меняется.

#### Scenario: Перезапуск всего dead-letter
- **WHEN** в dead-letter попали задания A (`billing`), B (`mail`), C (`billing`) и вызывается `requeue_all_dead_letters()`
- **THEN** возвращается `[A, B, C]` (те же `Job`) в этом порядке, все в `PENDING` с `attempts == 0` и `error is None`, `dead_letters() == []`, `jobs.requeued == 3`

#### Scenario: Перезапуск по типу
- **WHEN** в dead-letter A (`billing`), B (`mail`), C (`billing`) и вызывается `requeue_all_dead_letters("billing")`
- **THEN** возвращается `[A, C]`, B остаётся в `DEAD_LETTERED` и в `dead_letters()`, `jobs.requeued == 2`

#### Scenario: Пустой dead-letter
- **WHEN** dead-letter пуст и вызывается `requeue_all_dead_letters()`
- **THEN** возвращается `[]`, `jobs.requeued == 0`

#### Scenario: Нет заданий нужного типа
- **WHEN** в dead-letter только задания `mail` и вызывается `requeue_all_dead_letters("billing")`
- **THEN** возвращается `[]`, dead-letter не изменился

#### Scenario: Возвращённый список независим
- **WHEN** изменяется список, вернувшийся из `requeue_all_dead_letters`
- **THEN** состояние очереди не меняется

## MODIFIED Requirements

### Requirement: Попадание в dead-letter
Когда задание по решению воркера (см. job-retry-execution) уходит в dead-letter, очередь SHALL перевести его в `DEAD_LETTERED` и добавить `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at, reason)` (неизменяемый dataclass), где `attempts` — число попыток на момент попадания, `error` — последняя ошибка, `dead_lettered_at` — текущее время часов очереди, `reason` — `DeadLetterReason` (новое поле, последнее по порядку; по умолчанию `DeadLetterReason.EXHAUSTED`, чтобы существующее создание записи пятью аргументами работало). `DeadLetterReason(str, Enum)` содержит `EXHAUSTED = "exhausted"` (кончились попытки) и `NON_RETRYABLE = "non_retryable"` (неповторяемая ошибка); причина важнее счётчика попыток: неповторяемая ошибка на последней попытке даёт `NON_RETRYABLE`, а `RetryLaterError` на последней попытке — `EXHAUSTED`. `JobQueue.dead_letters()` SHALL возвращать список записей в порядке попадания. Возвращаемый список MUST быть копией: его изменение не влияет на очередь.

#### Scenario: Запись создаётся при исчерпании попыток
- **WHEN** задание типа `billing` упало повторяемой ошибкой на последней из 3 попыток
- **THEN** `dead_letters()` содержит одну запись с `job_id` задания, `job_type == "billing"`, `attempts == 3`, `error` с последней ошибкой, `dead_lettered_at` равным времени часов и `reason == DeadLetterReason.EXHAUSTED`

#### Scenario: Запись при неповторяемой ошибке
- **WHEN** задание типа `billing` на первой из 3 попыток бросило `PermanentJobError("bad")` при действующей политике
- **THEN** запись имеет `attempts == 1`, `error == "PermanentJobError: bad"`, `reason == DeadLetterReason.NON_RETRYABLE`

#### Scenario: Значения причин
- **WHEN** читаются `DeadLetterReason.EXHAUSTED` и `DeadLetterReason.NON_RETRYABLE`
- **THEN** их `.value` равны `"exhausted"` и `"non_retryable"`

#### Scenario: Порядок записей
- **WHEN** в dead-letter последовательно попадают задания A, затем B
- **THEN** `dead_letters()` возвращает записи в порядке `[A, B]`

#### Scenario: Пустой dead-letter
- **WHEN** ничего не попадало в dead-letter
- **THEN** `dead_letters() == []`

### Requirement: Метрика dead-letter
Счётчик `jobs.dead_lettered` SHALL увеличиваться ровно в момент перехода задания в `DEAD_LETTERED` (по любой причине, включая `non_retryable`); `jobs.requeued` — при каждом успешном возврате задания из dead-letter (`requeue_dead_letter` и каждое задание в `requeue_all_dead_letters`). Задание, ушедшее в `FAILED` (в том числе при отсутствии политики или обработчика), `jobs.dead_lettered` не увеличивает. Задания, удалённые очисткой из dead-letter, учитываются в `jobs.purged`.

#### Scenario: Счётчики
- **WHEN** задание уходит в dead-letter, затем возвращается через `requeue_dead_letter`
- **THEN** `jobs.dead_lettered == 1`, `jobs.requeued == 1`

#### Scenario: Неповторяемая ошибка считается
- **WHEN** задание уходит в dead-letter по причине `non_retryable`
- **THEN** `jobs.dead_lettered == 1`, `jobs.failed == 0`

## RENAMED Requirements

- FROM: `### Requirement: Очистка не затрагивает dead-letter`
- TO: `### Requirement: Очистка затрагивает dead-letter`

## MODIFIED Requirements

### Requirement: Очистка затрагивает dead-letter
`JobQueue.purge_finished(older_than)` SHALL удалять терминальные задания по существующему правилу (`finished_at <= now - older_than`) и, кроме того, задания в `DEAD_LETTERED`, у которых `dead_lettered_at <= now - older_than` (возраст считается от момента попадания в dead-letter). Вместе с заданием из хранилища SHALL исчезать его запись из `dead_letters()`; остальные записи сохраняют порядок. Возвращаемое число и счётчик `jobs.purged` MUST учитывать и удалённые задания из dead-letter. Задания в `RETRY_SCHEDULED` очисткой по-прежнему MUST NOT удаляться. Сигнатура `purge_finished` не меняется.

#### Scenario: purge_finished и dead-letter
- **WHEN** есть давно завершённые `SUCCEEDED`, `FAILED` и `DEAD_LETTERED` и вызывается `purge_finished()`
- **THEN** удалены все три задания, `dead_letters() == []`, возвращено `3`, `jobs.purged == 3`

#### Scenario: Возраст считается от попадания в dead-letter
- **WHEN** задание попало в dead-letter 100 секунд назад и вызывается `purge_finished(older_than=50)`, затем для другого задания, попавшего 10 секунд назад, то же
- **THEN** первое удалено вместе с записью, второе остаётся в `DEAD_LETTERED` и в `dead_letters()`

#### Scenario: Порядок оставшихся записей
- **WHEN** в dead-letter A, B, C и очистка удаляет только B
- **THEN** `dead_letters()` возвращает записи `[A, C]`

#### Scenario: Ожидающие повтора не удаляются
- **WHEN** есть давно созданное задание в `RETRY_SCHEDULED` и вызывается `purge_finished()`
- **THEN** оно остаётся
