# dead-letter-queue Specification

## Purpose
Описывает dead-letter: хранение заданий, исчерпавших попытки, просмотр записей, осознанный возврат в работу, а также влияние на очистку, метрики и отчёт дежурных.

## Requirements

### Requirement: Статусы и подписи
`JobStatus` SHALL содержать `RETRY_SCHEDULED` со значением `"retry_scheduled"` и подписью «Ожидает повтора» и `DEAD_LETTERED` со значением `"dead_lettered"` и подписью «В dead-letter». Ни один из двух статусов не является терминальным (`is_terminal == False`). `JobQueue.stats()` SHALL содержать ключи для обоих статусов, а отчёт дежурных (`render_report`) показывать их с этими подписями без изменения `jobq/dashboard.py`.

#### Scenario: Значения и подписи
- **WHEN** читаются `JobStatus.RETRY_SCHEDULED` и `JobStatus.DEAD_LETTERED`
- **THEN** их `.value` равны `"retry_scheduled"` и `"dead_lettered"`, `.label` равны «Ожидает повтора» и «В dead-letter»

#### Scenario: Статистика
- **WHEN** запрашивается `queue.stats()`
- **THEN** ключи `retry_scheduled` и `dead_lettered` присутствуют (значение 0, если заданий нет)

#### Scenario: Отчёт дежурных
- **WHEN** строится `render_report(queue)`
- **THEN** в блоке «Статусы» есть строки «Ожидает повтора» и «В dead-letter» с количеством заданий

### Requirement: Попадание в dead-letter
Когда у задания исчерпаны попытки (см. решение воркера), очередь SHALL перевести его в `DEAD_LETTERED` и добавить `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` (неизменяемый dataclass), где `attempts` — число попыток на момент попадания, `error` — последняя ошибка, `dead_lettered_at` — текущее время часов очереди. `JobQueue.dead_letters()` SHALL возвращать список записей в порядке попадания. Возвращаемый список MUST быть копией: его изменение не влияет на очередь.

#### Scenario: Запись создаётся
- **WHEN** задание типа `billing` упало повторяемой ошибкой на последней из 3 попыток
- **THEN** `dead_letters()` содержит одну запись с `job_id` задания, `job_type == "billing"`, `attempts == 3`, `error` с последней ошибкой и `dead_lettered_at` равным времени часов

#### Scenario: Порядок записей
- **WHEN** в dead-letter последовательно попадают задания A, затем B
- **THEN** `dead_letters()` возвращает записи в порядке `[A, B]`

#### Scenario: Пустой dead-letter
- **WHEN** ничего не попадало в dead-letter
- **THEN** `dead_letters() == []`

### Requirement: Возврат из dead-letter
`JobQueue.requeue_dead_letter(job_id)` SHALL вернуть в работу то же задание (новое не создаётся) и вернуть его как `Job`: статус `PENDING`, `run_at` равен текущему времени часов, `error` очищается (`None`), `attempts` обнуляется (иначе после первой же ошибки задание сразу ушло бы обратно в dead-letter), запись удаляется из `dead_letters()`. Идентификатор и `payload` сохраняются. Счётчик `jobs.requeued` увеличивается на 1. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`; при ошибке состояние не меняется. Единственный способ выйти из `DEAD_LETTERED` — `requeue_dead_letter`: `cancel` для такого задания MUST давать `InvalidTransitionError`.

#### Scenario: Успешный возврат
- **WHEN** задание в `DEAD_LETTERED` с `attempts == 3` и вызывается `requeue_dead_letter(job_id)` в момент T
- **THEN** возвращается тот же `Job` (`id` не изменился): `status == PENDING`, `run_at == T`, `error is None`, `attempts == 0`; `dead_letters()` не содержит записи; `jobs.requeued == 1`

#### Scenario: Возвращённое задание снова выполняется
- **WHEN** после возврата воркер запускает задание и обработчик падает повторяемой ошибкой при `max_attempts=3`
- **THEN** задание получает `RETRY_SCHEDULED`, а не `DEAD_LETTERED`

#### Scenario: Задание не в dead-letter
- **WHEN** `requeue_dead_letter` вызывается для задания в статусе `PENDING` или `FAILED`
- **THEN** выбрасывается `InvalidTransitionError`, `jobs.requeued` не меняется

#### Scenario: Неизвестное задание
- **WHEN** `requeue_dead_letter("nope")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Отмена из dead-letter запрещена
- **WHEN** вызывается `cancel(job_id)` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`, задание остаётся в dead-letter

### Requirement: Очистка не затрагивает dead-letter
`JobQueue.purge_finished` SHALL удалять только терминальные задания и MUST NOT удалять задания в `DEAD_LETTERED` (и в `RETRY_SCHEDULED`); они остаются до `requeue_dead_letter` (соответственно до выполнения или отмены).

#### Scenario: purge_finished и dead-letter
- **WHEN** есть задания `SUCCEEDED`, `FAILED` и `DEAD_LETTERED`, давно завершённые, и вызывается `purge_finished()`
- **THEN** удалены `SUCCEEDED` и `FAILED`, задание `DEAD_LETTERED` осталось, `dead_letters()` не изменился

### Requirement: Метрика dead-letter
Счётчик `jobs.dead_lettered` SHALL увеличиваться ровно в момент перехода задания в `DEAD_LETTERED`; `jobs.requeued` — при каждом успешном `requeue_dead_letter`. Задание, ушедшее в `FAILED`, `jobs.dead_lettered` не увеличивает.

#### Scenario: Счётчики
- **WHEN** задание уходит в dead-letter, затем возвращается через `requeue_dead_letter`
- **THEN** `jobs.dead_lettered == 1`, `jobs.requeued == 1`
