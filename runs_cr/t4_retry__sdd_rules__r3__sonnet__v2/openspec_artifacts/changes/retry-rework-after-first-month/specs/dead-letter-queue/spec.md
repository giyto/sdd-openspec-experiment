## ADDED Requirements

### Requirement: Причина попадания в dead-letter
Система SHALL предоставлять `DeadLetterReason(str, Enum)` в `jobq/models.py` со значениями `EXHAUSTED = "exhausted"` (кончились попытки) и `NON_RETRYABLE = "non_retryable"` (неповторяемая ошибка). `DeadLetterEntry` SHALL получить новое поле `reason: DeadLetterReason`, последним по порядку; оно SHALL иметь значение по умолчанию `EXHAUSTED`, чтобы создание записи без `reason` продолжало работать. Причина фиксируется на момент попадания в dead-letter. Если неповторяемая ошибка случилась на последней попытке, причина SHALL быть `NON_RETRYABLE`; если на последней попытке брошена `RetryLaterError` — `EXHAUSTED`.

#### Scenario: Причина — исчерпание
- **WHEN** задание исчерпало все попытки повторяемой ошибкой
- **THEN** запись в `dead_letters()` имеет `reason == DeadLetterReason.EXHAUSTED`

#### Scenario: Причина — неповторяемая ошибка
- **WHEN** задание упало с `PermanentJobError` при действующей политике
- **THEN** запись в `dead_letters()` имеет `reason == DeadLetterReason.NON_RETRYABLE`

#### Scenario: Значения как строки
- **WHEN** читается `DeadLetterReason.NON_RETRYABLE.value`
- **THEN** возвращается `"non_retryable"`, а `DeadLetterReason("exhausted")` равно `EXHAUSTED`

#### Scenario: Совместимость создания записи
- **WHEN** `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` создаётся без `reason`
- **THEN** создание успешно и `reason == DeadLetterReason.EXHAUSTED`

### Requirement: Массовый возврат из dead-letter
`JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]` SHALL перезапускать все задания из dead-letter, а при заданном `job_type` — только записи этого типа. Каждое задание SHALL перезапускаться так же, как через `requeue_dead_letter` (тот же объект `Job`, статус `PENDING`, `run_at` = текущее время часов, `error = None`, `attempts = 0`, запись удаляется из `dead_letters()`, `jobs.requeued` +1 за каждое задание). Порядок перезапуска и порядок возвращаемого списка SHALL совпадать с порядком `dead_letters()` на момент вызова. Если перезапускать нечего (dead-letter пуст или нет записей нужного типа), SHALL возвращаться пустой список без ошибок и без изменения счётчиков. Задания других типов при заданном `job_type` не затрагиваются.

#### Scenario: Перезапуск всего dead-letter
- **WHEN** в dead-letter задания B (попало первым) и A, вызывается `requeue_all_dead_letters()`
- **THEN** возвращается `[B, A]`, оба в `PENDING`, `dead_letters()` пуст, `jobs.requeued` вырос на 2

#### Scenario: Фильтр по типу
- **WHEN** в dead-letter задания типов `a` и `b` и вызывается `requeue_all_dead_letters("a")`
- **THEN** возвращаются только задания типа `a` в порядке `dead_letters()`, задания типа `b` остаются в `DEAD_LETTERED` и в `dead_letters()`

#### Scenario: Пустой dead-letter
- **WHEN** dead-letter пуст и вызывается `requeue_all_dead_letters()`
- **THEN** возвращается `[]`, счётчики не изменились

#### Scenario: Нет заданий нужного типа
- **WHEN** в dead-letter только задания типа `a` и вызывается `requeue_all_dead_letters("zzz")`
- **THEN** возвращается `[]`, dead-letter не изменился

## MODIFIED Requirements

### Requirement: Просмотр dead-letter
`JobQueue.dead_letters()` SHALL возвращать список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at, reason)` в порядке попадания в dead-letter. `attempts`, `error` и `reason` SHALL фиксировать значения на момент попадания, `dead_lettered_at` — время часов очереди. Возвращается копия: изменение списка не влияет на очередь.

#### Scenario: Порядок записей
- **WHEN** задание B попадает в dead-letter раньше задания A (A поставлено раньше)
- **THEN** `dead_letters()` возвращает сначала запись B, затем A

#### Scenario: Содержимое записи
- **WHEN** задание типа `send_email` исчерпало 3 попытки, последняя ошибка `TimeoutError: gateway`
- **THEN** запись содержит `job_type == "send_email"`, `attempts == 3`, `error == "TimeoutError: gateway"`, `dead_lettered_at` равен времени часов в момент попадания и `reason == DeadLetterReason.EXHAUSTED`

#### Scenario: Копия списка
- **WHEN** результат `dead_letters()` изменяется вызывающим кодом
- **THEN** следующий вызов `dead_letters()` возвращает исходное содержимое

### Requirement: Отмена ожидающего повтора и purge
Задание в `RETRY_SCHEDULED` SHALL отменяться через `cancel` так же, как ожидающее (`CANCELLED`, `finished_at` выставлен, `jobs.cancelled` +1). `purge_finished(older_than)` SHALL удалять задания в `DEAD_LETTERED`, попавшие в dead-letter не позже `now - older_than` секунд (отсчёт от `dead_lettered_at`, граница включительно, как для завершённых заданий); задание удаляется из хранилища, а его запись исчезает из `dead_letters()`. Возвращаемое число и счётчик `jobs.purged` SHALL учитывать и удалённые задания из dead-letter. Задания в `DEAD_LETTERED` моложе порога и задания в `RETRY_SCHEDULED` SHALL NOT удаляться. Правило для завершённых заданий (`SUCCEEDED`, `FAILED`, `CANCELLED`) не меняется.

#### Scenario: Отмена задания, ждущего повтора
- **WHEN** задание в `RETRY_SCHEDULED` и вызывается `cancel(id)`
- **THEN** статус `CANCELLED` и воркер его больше не берёт

#### Scenario: purge удаляет dead-letter
- **WHEN** есть задание в `DEAD_LETTERED` и вызывается `purge_finished()` (в том числе с `older_than=0`)
- **THEN** задание удалено из хранилища, записи в `dead_letters()` нет, возвращаемое число включает его

#### Scenario: purge считает возраст от попадания в dead-letter
- **WHEN** задание попало в dead-letter 100 с назад и вызывается `purge_finished(older_than=3600)`, затем `purge_finished(older_than=60)`
- **THEN** первый вызов его не удаляет, второй удаляет

#### Scenario: purge не трогает dead-letter
- **WHEN** задание попало в dead-letter 10 с назад и вызывается `purge_finished(older_than=3600)`
- **THEN** задание остаётся в хранилище и в `dead_letters()` (прежняя гарантия сохраняется только для записей моложе порога; при `older_than=0` запись удаляется, см. выше)

#### Scenario: purge не трогает ожидающий повтор
- **WHEN** есть задание в `RETRY_SCHEDULED` и вызывается `purge_finished()`
- **THEN** оно остаётся в хранилище

#### Scenario: Счётчик purge
- **WHEN** удалены одно завершённое задание и два задания из dead-letter
- **THEN** `purge_finished` возвращает `3`, а `jobs.purged` растёт на 3
