## Purpose

Описывает dead-letter очередь: учёт заданий, исчерпавших попытки, и осознанный возврат их в работу.

## ADDED Requirements

### Requirement: Содержимое dead-letter
Очередь SHALL предоставлять `dead_letters()` — список записей `DeadLetterEntry` (frozen) с полями `job_id`, `job_type`, `attempts`, `error` (тот же текст, что в `job.error`) и `dead_lettered_at` (время по часам очереди), в порядке попадания в dead-letter.

#### Scenario: Запись после исчерпания попыток
- **WHEN** задание исчерпало попытки
- **THEN** `dead_letters()` содержит запись с id, типом, числом попыток, последней ошибкой и временем часов очереди

#### Scenario: Порядок записей
- **WHEN** сначала в dead-letter попало задание B, затем A
- **THEN** `dead_letters()` возвращает сначала B, затем A

#### Scenario: Окончательно упавшие задания не попадают сюда
- **WHEN** задание завершилось `FAILED`
- **THEN** его нет в `dead_letters()`

### Requirement: Возврат задания в работу
`requeue_dead_letter(job_id)` SHALL возвращать то же задание (тот же `job_id`, новое не создаётся, `jobs.enqueued` не растёт) в статус `PENDING` с `run_at` = текущее время очереди, `attempts` = 0, `error` = `None`; запись SHALL исчезать из `dead_letters()`, `jobs.requeued` SHALL увеличиваться на 1. Неизвестный id SHALL давать `JobNotFoundError`, задание не в dead-letter — `InvalidTransitionError`. Если задание вновь исчерпает попытки, его запись SHALL оказаться в конце `dead_letters()`.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter` для задания из dead-letter
- **THEN** задание `PENDING`, `attempts == 0`, `error is None`, `run_at` = now, записи в dead-letter нет, `jobs.requeued` +1, `jobs.enqueued` не изменился

#### Scenario: Полный набор попыток после возврата
- **WHEN** возвращённое задание снова падает
- **THEN** ему доступно `max_attempts` попыток, после чего оно снова в конце `dead_letters()`

#### Scenario: Неизвестный id
- **WHEN** id неизвестен
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Задание не в dead-letter
- **WHEN** задание существует, но не в dead-letter (например, `FAILED` или `PENDING`)
- **THEN** выбрасывается `InvalidTransitionError`, состояние не меняется
