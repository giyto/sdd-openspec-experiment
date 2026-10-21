## Purpose

Dead-letter очередь для заданий, которые исчерпали все попытки повтора. Такие задания хранятся до осознанного
возврата в работу оператором: их не удаляет очистка завершённых заданий и отменить их нельзя.

## ADDED Requirements

### Requirement: Dead-lettering of exhausted jobs
Когда задание с повторяемой ошибкой исчерпывает `max_attempts`, оно SHALL переходить в `JobStatus.DEAD_LETTERED`
(значение `"dead_lettered"`), а в список dead-letter SHALL добавляться запись `DeadLetterEntry` с полями `job_id`,
`job_type`, `attempts`, `error` (последняя ошибка) и `dead_lettered_at` (текущее время очереди).
`JobQueue.dead_letters()` SHALL возвращать записи в порядке попадания, от самой старой к самой новой.
Задание в `DEAD_LETTERED` SHALL получать `finished_at`, а счётчик `jobs.dead_lettered` увеличивается на 1.

Задания, упавшие с неповторяемой ошибкой, в dead-letter MUST NOT попадать.

#### Scenario: Исчерпание попыток
- **WHEN** политика с `max_attempts=3`, и все три попытки задания падают с `ConnectionError: 503`
- **THEN** статус `DEAD_LETTERED`, `dead_letters()` содержит одну запись с `attempts` = 3 и `error` = `"ConnectionError: 503"`

#### Scenario: Порядок записей
- **WHEN** задание A попадает в dead-letter раньше задания B
- **THEN** `dead_letters()` возвращает сначала запись A, затем запись B

#### Scenario: Неповторяемая ошибка не попадает в dead-letter
- **WHEN** задание падает с `PermanentJobError` на последней попытке
- **THEN** статус `FAILED`, `dead_letters()` не содержит запись для этого задания

### Requirement: Dead-lettered jobs are kept until requeued
Очистка завершённых заданий `purge_finished` MUST NOT удалять задания в `DEAD_LETTERED`. Запись остаётся в
dead-letter до `requeue_dead_letter`. Задание в `DEAD_LETTERED` SHALL NOT отменяться через `cancel()`:
выход из dead-letter только через `requeue_dead_letter`.

#### Scenario: Очистка не трогает dead-letter
- **WHEN** часы продвинуты вперёд, и вызван `purge_finished()` с `older_than=0`
- **THEN** возвращено 0, а `dead_letters()` по-прежнему содержит запись

#### Scenario: Отмена задания из dead-letter запрещена
- **WHEN** вызван `cancel()` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`, статус не меняется

### Requirement: Requeue of a dead-lettered job
`JobQueue.requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание, без создания нового: статус `PENDING`,
`run_at` = текущее время очереди, `error` = `None`, `finished_at` = `None`, `attempts` = 0. Запись из dead-letter
SHALL удаляться. Счётчик `jobs.requeued` SHALL увеличиваться на 1. Число попыток до перезапуска SHALL записываться в лог.

Вызов для идентификатора, которого нет в хранилище, SHALL выбрасывать `JobNotFoundError`. Вызов для задания, которого
нет в dead-letter, SHALL выбрасывать `InvalidTransitionError`.

#### Scenario: Возврат и повторное выполнение
- **WHEN** задание в dead-letter возвращается через `requeue_dead_letter`, и воркер выполняет очередь
- **THEN** возвращённый объект `Job` имеет тот же `id`, новое задание не создаётся, `attempts` стартует с 1 и запись удалена из `dead_letters()`

#### Scenario: После возврата снова действует политика повторов
- **WHEN** задание возвращено через requeue, политика `max_attempts=3`, и первая попытка падает с повторяемой ошибкой
- **THEN** статус `RETRY_SCHEDULED`, а не `DEAD_LETTERED`

#### Scenario: Возврат задания, которого нет в dead-letter
- **WHEN** вызван `requeue_dead_letter` для задания в статусе `PENDING`
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: Возврат несуществующего задания
- **WHEN** вызван `requeue_dead_letter("job-999999")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Счётчик возвратов
- **WHEN** задание успешно возвращено через requeue
- **THEN** счётчик `jobs.requeued` увеличен на 1

### Requirement: Dead-letter status label
`JobStatus.DEAD_LETTERED` SHALL иметь подпись «В dead-letter» для отчёта дежурных. Статус SHALL считаться
терминальным для `is_terminal`, потому что воркер его не выполняет.

#### Scenario: Подпись статуса
- **WHEN** запрашивается `JobStatus.DEAD_LETTERED.label`
- **THEN** возвращается «В dead-letter»
