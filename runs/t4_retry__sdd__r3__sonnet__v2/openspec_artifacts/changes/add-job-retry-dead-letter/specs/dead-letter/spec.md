## Purpose

Описывает dead-letter: хранение заданий, исчерпавших попытки, и осознанный возврат их в работу оператором.

## ADDED Requirements

### Requirement: Список dead-letter
`dead_letters()` SHALL возвращать список `DeadLetterEntry` (`job_id`, `job_type`, `attempts`, `error`, `dead_lettered_at`) в порядке попадания в dead-letter. Запись фиксирует число попыток и последнюю ошибку на момент перехода, `dead_lettered_at` — время часов очереди. Возвращается копия списка; её изменение не влияет на очередь.

#### Scenario: Порядок и содержимое
- **WHEN** задание A, а затем B исчерпали попытки
- **THEN** `dead_letters()` содержит записи A и B именно в этом порядке с их `attempts`, `error` и временем

#### Scenario: Пустой список
- **WHEN** ни одно задание не исчерпало попытки
- **THEN** `dead_letters()` возвращает пустой список

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся, `id` и `payload` сохраняются): статус `PENDING`, `run_at = now`, `error = None`, `attempts = 0`; запись из dead-letter удаляется, счётчик `jobs.requeued` увеличивается на 1. Для задания не в `DEAD_LETTERED` MUST выбрасываться `InvalidTransitionError`, для неизвестного id — `JobNotFoundError`. Это единственный выход из `DEAD_LETTERED`.

#### Scenario: Успешный возврат
- **WHEN** вызван `requeue_dead_letter` для задания в dead-letter в момент T
- **THEN** возвращается тот же `Job` со статусом `PENDING`, `run_at = T`, `error = None`, `attempts = 0`; в `dead_letters()` его нет; `jobs.requeued = 1`

#### Scenario: Перезапущенное задание получает полный набор попыток
- **WHEN** вернувшееся задание падает один раз при `max_attempts=3`
- **THEN** оно уходит в `RETRY_SCHEDULED`, а не снова в dead-letter

#### Scenario: Задание не в dead-letter
- **WHEN** вызван `requeue_dead_letter` для задания в `PENDING`, `FAILED` или `RETRY_SCHEDULED`
- **THEN** выбрасывается `InvalidTransitionError`, счётчик `jobs.requeued` не меняется

#### Scenario: Неизвестное задание
- **WHEN** передан несуществующий id
- **THEN** выбрасывается `JobNotFoundError`

### Requirement: Защита от purge_finished
`purge_finished` SHALL НЕ удалять задания в `DEAD_LETTERED` независимо от `older_than`; они лежат в dead-letter до `requeue_dead_letter`. Остальное поведение `purge_finished` не меняется, `RETRY_SCHEDULED` не считается завершённым и не удаляется.

#### Scenario: Purge не трогает dead-letter
- **WHEN** в очереди есть давно завершившиеся `SUCCEEDED` и `DEAD_LETTERED` задания и вызван `purge_finished()`
- **THEN** удалено только `SUCCEEDED`; `dead_letters()` и число заданий в `DEAD_LETTERED` не изменились
