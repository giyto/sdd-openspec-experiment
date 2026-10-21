## Purpose

Описывает dead-letter очередь: учёт заданий, исчерпавших попытки, и осознанный возврат их в работу.

## ADDED Requirements

### Requirement: Список dead-letter
`JobQueue.dead_letters()` SHALL возвращать список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` в порядке попадания в dead-letter. Запись фиксирует число попыток, последнюю ошибку и время (по часам очереди) на момент попадания. Возвращается копия: изменение списка не влияет на очередь. `DeadLetterEntry` SHALL быть неизменяемой.

#### Scenario: Порядок и содержимое
- **WHEN** в dead-letter последовательно попадают два задания
- **THEN** `dead_letters()` содержит две записи в порядке попадания с корректными `attempts`, `error`, `dead_lettered_at`

#### Scenario: Пустой список
- **WHEN** в dead-letter ничего не попадало
- **THEN** `dead_letters() == []`

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL вернуть в работу то же самое задание (новое не создаётся, `id` сохраняется): статус `PENDING`, `run_at = now`, `error = None`, запись удаляется из `dead_letters()`, счётчик `jobs.requeued` увеличивается. `attempts` SHALL сбрасываться в `0`, так что у задания снова полный набор попыток, как у нового; история прежних попыток доступна только в логах. `created_at` не изменяется. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`; для существующего задания не в dead-letter — `InvalidTransitionError`. Других способов выйти из dead-letter нет. Если задание снова попадёт в dead-letter, добавляется новая запись в конец списка.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter` для задания в dead-letter
- **THEN** возвращается тот же `Job` со статусом `PENDING`, `run_at == now`, `error is None`, `dead_letters()` не содержит его

#### Scenario: Задание не в dead-letter
- **WHEN** вызывается `requeue_dead_letter` для `PENDING`- или `FAILED`-задания
- **THEN** выбрасывается `InvalidTransitionError`, состояние не меняется

#### Scenario: Неизвестное задание
- **WHEN** вызывается `requeue_dead_letter("nope")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Счётчик попыток после возврата
- **WHEN** задание с `attempts == max_attempts` возвращено из dead-letter
- **THEN** `attempts == 0`, и первое же падение повторяемой ошибкой (при `max_attempts > 1`) приводит к `RETRY_SCHEDULED`, а не к `DEAD_LETTERED`

#### Scenario: Повторное попадание
- **WHEN** возвращённое задание снова падает и исчерпывает все `max_attempts` попыток
- **THEN** в конце `dead_letters()` появляется новая запись
