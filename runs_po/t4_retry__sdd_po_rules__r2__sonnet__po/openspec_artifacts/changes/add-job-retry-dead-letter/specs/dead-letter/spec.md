## Purpose

Описывает dead-letter очередь: учёт заданий, исчерпавших попытки, и осознанный возврат их в работу.

## ADDED Requirements

### Requirement: Запись в dead-letter
При переходе задания в `DEAD_LETTERED` очередь SHALL добавить в конец списка `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` (frozen dataclass в `jobq/models.py`), где `attempts` и `error` взяты у задания, а `dead_lettered_at` — время часов очереди. `dead_letters()` MUST возвращать новый список записей в порядке попадания; изменение этого списка не влияет на очередь. Счётчик `jobs.dead_lettered` увеличивается на 1 при каждом таком переходе.

#### Scenario: Содержимое записи
- **WHEN** задание `job-000001` типа `"mail"` исчерпало 3 попытки с последней ошибкой `TimeoutError: gw`
- **THEN** `dead_letters()` содержит запись с `job_id == "job-000001"`, `job_type == "mail"`, `attempts == 3`, `error == "TimeoutError: gw"` и `dead_lettered_at`, равным текущему времени очереди

#### Scenario: Порядок
- **WHEN** в dead-letter попадают сначала задание A, затем B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Список — копия
- **WHEN** вызывающий код очищает возвращённый `dead_letters()` список
- **THEN** следующий вызов `dead_letters()` по-прежнему возвращает все записи

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL вернуть в работу то же задание (новое не создаётся) и вернуть его: статус `PENDING`, `run_at` = текущее время часов очереди, `error = None`, `attempts = 0` (полный набор попыток, как у нового задания; история прежних попыток остаётся в логах); запись удаляется из dead-letter, `jobs.requeued` увеличивается на 1. Прочие поля (`id`, `payload`, `created_at`) не меняются. Это единственный выход из `DEAD_LETTERED`: `cancel` и `purge_finished` не должны затрагивать такие задания. Если задание не найдено — `JobNotFoundError`; если оно не в `DEAD_LETTERED` — `InvalidTransitionError`; в обоих случаях состояние не меняется.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter(id)` для задания в dead-letter
- **THEN** возвращён тот же объект `Job` со статусом `PENDING`, `run_at == now`, `error is None`, `attempts == 0`; `dead_letters()` не содержит его; `jobs.requeued == 1`; `next_due()` возвращает его

#### Scenario: Повторный возврат
- **WHEN** `requeue_dead_letter(id)` вызывается второй раз подряд
- **THEN** выбрасывается `InvalidTransitionError`, `jobs.requeued` остаётся 1

#### Scenario: Неизвестное задание
- **WHEN** вызывается `requeue_dead_letter("nope")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Задание не в dead-letter
- **WHEN** `requeue_dead_letter(id)` для задания в `FAILED` или `PENDING`
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: Отмена и очистка не затрагивают dead-letter
- **WHEN** вызываются `cancel(id)` и `purge_finished()` для задания в `DEAD_LETTERED`
- **THEN** `cancel` выбрасывает `InvalidTransitionError`, `purge_finished` задание не удаляет, запись остаётся

#### Scenario: Полный набор попыток после возврата
- **WHEN** возвращённое задание падает повторяемой ошибкой при `max_attempts=3`
- **THEN** оно уходит в `RETRY_SCHEDULED` (а не в `DEAD_LETTERED`), и только после 3 новых попыток снова попадает в dead-letter

#### Scenario: Повторное попадание в dead-letter
- **WHEN** возвращённое задание снова исчерпывает попытки
- **THEN** в конце `dead_letters()` появляется новая запись для того же `job_id`, дубликатов нет
