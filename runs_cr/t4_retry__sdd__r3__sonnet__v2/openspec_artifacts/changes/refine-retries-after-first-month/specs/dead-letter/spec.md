## ADDED Requirements

### Requirement: Массовый возврат из dead-letter
`requeue_all_dead_letters(job_type=None)` SHALL возвращать в работу все задания из dead-letter, а при заданном `job_type` — только записи этого типа. Каждое задание MUST возвращаться так же, как через `requeue_dead_letter` (тот же объект, `PENDING`, `run_at = now`, `error = None`, `attempts = 0`, запись удаляется, `jobs.requeued` растёт на 1 за каждое). Задания обрабатываются в порядке `dead_letters()`; возвращается список перезапущенных заданий в том же порядке. Если перезапускать нечего (dead-letter пуст или нет записей нужного типа), SHALL возвращаться пустой список без ошибок и без изменения счётчиков. Задания вне выборки не меняются. Значение `job_type`, не являющееся непустой строкой или `None`, MUST приводить к `ConfigError` до каких-либо изменений.

#### Scenario: Возврат всего содержимого
- **WHEN** в dead-letter лежат A (тип `a`), B (тип `b`), C (тип `a`) в этом порядке и вызван `requeue_all_dead_letters()`
- **THEN** возвращается `[A, B, C]` в статусе `PENDING` с `attempts = 0`, `dead_letters()` пуст, `jobs.requeued = 3`

#### Scenario: Фильтр по типу
- **WHEN** в dead-letter лежат A (`a`), B (`b`), C (`a`) и вызван `requeue_all_dead_letters("a")`
- **THEN** возвращается `[A, C]`, B остаётся в `DEAD_LETTERED` и в `dead_letters()`, `jobs.requeued = 2`

#### Scenario: Пустой dead-letter
- **WHEN** dead-letter пуст
- **THEN** возвращается `[]`, `jobs.requeued` не меняется

#### Scenario: Нет заданий нужного типа
- **WHEN** в dead-letter есть записи только типа `a` и вызван `requeue_all_dead_letters("zzz")`
- **THEN** возвращается `[]`, записи остались на месте, `jobs.requeued` не меняется

#### Scenario: Недопустимый тип
- **WHEN** передан `job_type=""` или не строка
- **THEN** выбрасывается `ConfigError`, dead-letter не изменяется

#### Scenario: Полный набор попыток после массового возврата
- **WHEN** вернувшееся задание падает один раз при `max_attempts=3`
- **THEN** оно уходит в `RETRY_SCHEDULED`, а не снова в dead-letter

### Requirement: Очистка dead-letter через purge_finished
`purge_finished(older_than)` SHALL удалять задания в `DEAD_LETTERED` по тому же правилу возраста, что и остальные завершённые задания, считая от момента попадания в dead-letter (`dead_lettered_at`): удаляется задание, у которого `dead_lettered_at <= now - older_than`. При удалении запись MUST исчезать и из `dead_letters()`; после этого `requeue_dead_letter` для такого id выбрасывает `JobNotFoundError`. Удалённые задания учитываются в возвращаемом числе и в счётчике `jobs.purged` наравне с остальными. Свежие записи dead-letter не затрагиваются. Остальное поведение `purge_finished` не меняется, `RETRY_SCHEDULED` не считается завершённым и не удаляется; сигнатура и вызов `purge_finished()` без аргументов остаются прежними.

#### Scenario: Purge удаляет старые записи dead-letter
- **WHEN** в очереди есть давно завершившееся `SUCCEEDED` и давно попавшее в dead-letter задание и вызван `purge_finished()`
- **THEN** удалены оба, возвращено 2, `dead_letters()` пуст, `jobs.purged = 2`

#### Scenario: Возраст считается от попадания в dead-letter
- **WHEN** задание попало в dead-letter 100 секунд назад и вызван `purge_finished(older_than=50)`
- **THEN** задание и его запись удалены; при `older_than=200` — остаются

#### Scenario: Возвращённое задание не удаляется как dead-letter
- **WHEN** задание возвращено из dead-letter (`PENDING`) и вызван `purge_finished()`
- **THEN** задание остаётся в очереди

#### Scenario: Ожидающие повтора не удаляются
- **WHEN** в очереди есть задание в `RETRY_SCHEDULED` и вызван `purge_finished()`
- **THEN** оно не удалено

## MODIFIED Requirements

### Requirement: Список dead-letter
`dead_letters()` SHALL возвращать список `DeadLetterEntry` (`job_id`, `job_type`, `attempts`, `error`, `dead_lettered_at`, `reason`) в порядке попадания в dead-letter. Запись фиксирует число попыток и последнюю ошибку на момент перехода, `dead_lettered_at` — время часов очереди, `reason` — причину попадания: `DeadLetterReason.EXHAUSTED` (`"exhausted"`, кончились попытки) или `DeadLetterReason.NON_RETRYABLE` (`"non_retryable"`, неповторяемая ошибка). `reason` — последнее поле записи; конструирование записи без `reason` остаётся допустимым и даёт `EXHAUSTED`. Причина при неповторяемой ошибке на последней попытке — `non_retryable`; при `RetryLaterError` на последней попытке — `exhausted`. Возвращается копия списка; её изменение не влияет на очередь.

#### Scenario: Порядок и содержимое
- **WHEN** задание A, а затем B попали в dead-letter
- **THEN** `dead_letters()` содержит записи A и B именно в этом порядке с их `attempts`, `error`, временем и `reason`

#### Scenario: Причины различаются
- **WHEN** A исчерпало попытки повторяемой ошибкой, а B получило `PermanentJobError`
- **THEN** у записи A `reason = DeadLetterReason.EXHAUSTED`, у записи B `reason = DeadLetterReason.NON_RETRYABLE`

#### Scenario: Причина обновляется при повторном попадании
- **WHEN** задание из dead-letter возвращено и затем снова попало в dead-letter по другой причине
- **THEN** в новой записи `reason` соответствует новой причине

#### Scenario: Пустой список
- **WHEN** ни одно задание не попало в dead-letter
- **THEN** `dead_letters()` возвращает пустой список

## REMOVED Requirements

### Requirement: Защита от purge_finished
**Reason**: JOBQ-237 отменяет договорённость JOBQ-212: dead-letter накапливается без ограничений (40 тысяч записей за месяц).
**Migration**: Использовать «Очистка dead-letter через purge_finished»; чтобы сохранить нужные задания, вернуть их через `requeue_dead_letter` или `requeue_all_dead_letters` до вызова `purge_finished`.
