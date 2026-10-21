## Purpose

Описывает dead-letter очередь: учёт заданий, исчерпавших попытки, просмотр записей и осознанный возврат заданий в работу.

## ADDED Requirements

### Requirement: Запись DeadLetterEntry и просмотр dead_letters
`DeadLetterEntry` в `jobq/models.py` SHALL быть неизменяемым dataclass с полями `job_id: str`, `job_type: str`, `attempts: int`, `error: str`, `dead_lettered_at: datetime`. `JobQueue.dead_letters() -> list[DeadLetterEntry]` SHALL возвращать записи в порядке попадания в dead-letter; изменение возвращённого списка SHALL NOT влиять на очередь. Запись создаётся при переходе задания в `DEAD_LETTERED` со значениями `attempts` и `error` задания и временем очереди в `dead_lettered_at`. Единственный способ убрать запись — `requeue_dead_letter`.

#### Scenario: Содержимое записи
- **WHEN** задание типа `"mail"` исчерпало 3 попытки с последней ошибкой `TimeoutError: gw` в момент `T`
- **THEN** `dead_letters()` содержит `DeadLetterEntry(job_id=<id>, job_type="mail", attempts=3, error="TimeoutError: gw", dead_lettered_at=T)`

#### Scenario: Порядок попадания
- **WHEN** сначала в dead-letter попало задание A, затем B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Пустой dead-letter
- **WHEN** ни одно задание не исчерпало попытки
- **THEN** `dead_letters()` возвращает пустой список

#### Scenario: Копия списка
- **WHEN** вызывающий очищает возвращённый список
- **THEN** следующий `dead_letters()` по-прежнему возвращает все записи

### Requirement: Возврат из dead-letter
`JobQueue.requeue_dead_letter(job_id: str) -> Job` SHALL возвращать в работу то же задание (новое не создаётся, `id` и `seq` те же): статус `PENDING`, `run_at` = текущее время очереди, `attempts = 0` (счётчик попыток начинается заново, у задания снова полный набор попыток, как у нового), `error = None`, `finished_at = None`, запись о задании удаляется из `dead_letters()`. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`; для задания, не находящегося в `DEAD_LETTERED`, — `InvalidTransitionError`. Других выходов из `DEAD_LETTERED` (в том числе `cancel`) нет.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter(job_id)` для задания в `DEAD_LETTERED` в момент `T`
- **THEN** возвращается то же задание (тот же объект в хранилище) со статусом `PENDING`, `run_at == T`, `attempts == 0`, `error is None`; `dead_letters()` больше не содержит его; число заданий в хранилище не изменилось

#### Scenario: Возвращённое задание выполняется
- **WHEN** после возврата вызывается `worker.run_once()` и обработчик теперь успешен
- **THEN** задание получает `SUCCEEDED`

#### Scenario: Задание не в dead-letter
- **WHEN** вызывается `requeue_dead_letter` для задания в статусе `FAILED`, `PENDING` или повторно для уже возвращённого
- **THEN** выбрасывается `InvalidTransitionError`, состояние не меняется

#### Scenario: Неизвестный id
- **WHEN** вызывается `requeue_dead_letter("job-999999")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Отмена недоступна
- **WHEN** вызывается `cancel` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: Свежий набор попыток после возврата
- **WHEN** задание с `max_attempts=3` вернулось из dead-letter и его первая попытка снова упала повторяемой ошибкой
- **THEN** статус `RETRY_SCHEDULED`, `attempts == 1`, в dead-letter задание не попадает

#### Scenario: Повторное попадание
- **WHEN** возвращённое задание снова исчерпало все `max_attempts` попыток
- **THEN** в конец `dead_letters()` добавляется новая запись с `attempts == max_attempts`

### Requirement: Счётчики jobs.dead_lettered и jobs.requeued
Счётчик `jobs.dead_lettered` SHALL увеличиваться на 1 ровно в момент перехода задания в `DEAD_LETTERED`, а `jobs.requeued` — на 1 ровно при успешном `requeue_dead_letter`. При ошибке `requeue_dead_letter` счётчики не меняются. Неизвестные счётчики по-прежнему читаются как 0, а `metrics.snapshot()` показывает только ненулевые.

#### Scenario: Подсчёт
- **WHEN** задание ушло в dead-letter, затем возвращено
- **THEN** `jobs.dead_lettered == 1`, `jobs.requeued == 1`

#### Scenario: Неудачный возврат
- **WHEN** `requeue_dead_letter` завершился ошибкой
- **THEN** `jobs.requeued` не изменился
