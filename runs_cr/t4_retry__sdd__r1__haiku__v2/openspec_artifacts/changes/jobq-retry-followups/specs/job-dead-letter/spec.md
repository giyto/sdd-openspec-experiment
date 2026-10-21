## REMOVED Requirements

### Requirement: Dead-lettering of exhausted jobs
**Reason**: Требование расширено: неповторяемые ошибки теперь тоже попадают в dead-letter, а запись получает причину.
Старый текст несовместим с новым поведением (в нём сказано, что неповторяемые ошибки в dead-letter не попадают).
**Migration**: Вместо него действует требование «Dead-lettering of failed jobs» ниже. Вызовы `mark_dead_lettered(job_id, error)`
без изменений.

### Requirement: Dead-lettered jobs are kept until requeued
**Reason**: Очистка `purge_finished` теперь удаляет задания в dead-letter по возрасту, поэтому формулировка «не удаляются»
устарела.
**Migration**: Вместо него действуют требования «Dead-lettered jobs are kept until requeued or purged» ниже. Запрет на
`cancel()` сохранён в новом требовании.

## ADDED Requirements

### Requirement: Dead-lettering of failed jobs
Задание SHALL переходить в `JobStatus.DEAD_LETTERED` (значение `"dead_lettered"`) и попадать в dead-letter в двух случаях,
которые задаются причиной `DeadLetterReason`:

- `EXHAUSTED`: задание с повторяемой ошибкой исчерпало `max_attempts`;
- `NON_RETRYABLE`: задание упало с неповторяемой ошибкой (исключение из `non_retryable` или `PermanentJobError`)
  на любой попытке, при действующей политике повторов для его типа.

В список dead-letter SHALL добавляться запись `DeadLetterEntry` с полями `job_id`, `job_type`, `attempts`, `error`
(последняя ошибка), `dead_lettered_at` (текущее время очереди) и `reason`. `JobQueue.dead_letters()` SHALL возвращать
записи в порядке попадания, от самой старой к самой новой. Задание в `DEAD_LETTERED` SHALL получать `finished_at`,
а счётчик `jobs.dead_lettered` увеличивается на 1 независимо от причины.

Задания без действующей политики повторов и задания с неизвестным типом переходят в `FAILED` и в dead-letter
MUST NOT попадать.

#### Scenario: Исчерпание попыток
- **WHEN** политика с `max_attempts=3`, и все три попытки задания падают с `ConnectionError: 503`
- **THEN** статус `DEAD_LETTERED`, `dead_letters()` содержит одну запись с `attempts` = 3, `error` = `"ConnectionError: 503"` и `reason` = `EXHAUSTED`

#### Scenario: Порядок записей
- **WHEN** задание A попадает в dead-letter раньше задания B
- **THEN** `dead_letters()` возвращает сначала запись A, затем запись B

#### Scenario: Неповторяемая ошибка попадает в dead-letter
- **WHEN** задание падает с `PermanentJobError` на последней попытке при `max_attempts=3`
- **THEN** статус `DEAD_LETTERED`, `dead_letters()` содержит запись для этого задания с `reason` = `NON_RETRYABLE`

#### Scenario: Без политики неповторяемая ошибка остаётся в FAILED
- **WHEN** ни политика типа, ни политика по умолчанию не заданы, и задание падает с `PermanentJobError`
- **THEN** статус `FAILED`, `dead_letters()` не содержит запись для этого задания

### Requirement: Dead-lettered jobs are kept until requeued or purged
Задание в `DEAD_LETTERED` SHALL сохраняться до `requeue_dead_letter` или до очистки `purge_finished`. Очистка
`purge_finished(older_than)` SHALL удалять задание в `DEAD_LETTERED`, если `dead_lettered_at` не позже
`now - older_than` секунд, так же как завершённые задания других статусов; при этом соответствующая запись
исчезает из `dead_letters()`. Число удалённых заданий, включая задания из dead-letter, SHALL возвращаться из
`purge_finished` и учитываться в счётчике `jobs.purged`.

Задание в `DEAD_LETTERED` SHALL NOT отменяться через `cancel()`: выход из dead-letter только через
`requeue_dead_letter` или `requeue_all_dead_letters`, либо через очистку по возрасту.

#### Scenario: Очистка удаляет старые записи dead-letter
- **WHEN** задание попало в dead-letter, часы продвинуты вперёд, и вызван `purge_finished()` с `older_than=0`
- **THEN** возвращено 1, задание удалено из хранилища, а `dead_letters()` не содержит его запись

#### Scenario: Очистка не трогает свежие записи dead-letter
- **WHEN** задание попало в dead-letter 10 секунд назад, и вызван `purge_finished(older_than=60)`
- **THEN** возвращено 0, а `dead_letters()` по-прежнему содержит запись

#### Scenario: Возраст считается от попадания в dead-letter
- **WHEN** задание упало и попало в dead-letter в момент T, а вызов `purge_finished(older_than=60)` происходит в момент T + 30 секунд
- **THEN** задание не удаляется, даже если с момента его последнего запуска прошло больше 60 секунд

#### Scenario: Отмена задания из dead-letter запрещена
- **WHEN** вызван `cancel()` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`, статус не меняется

### Requirement: Dead-letter reason
`DeadLetterReason` SHALL быть строковым перечислением с значениями `EXHAUSTED` (`"exhausted"`, кончились попытки) и
`NON_RETRYABLE` (`"non_retryable"`, неповторяемая ошибка). `DeadLetterEntry` SHALL содержать поле `reason` последним
полем. Для совместимости `reason` SHALL иметь значение по умолчанию `EXHAUSTED`, поэтому создание записи без этого
поля продолжает работать. Метод `JobQueue.mark_dead_lettered(job_id, error)` SHALL сохранять прежнее поведение:
причина `EXHAUSTED`. Ключевой параметр `reason` (со значением по умолчанию `EXHAUSTED`) позволяет указать другую причину.

#### Scenario: Значения причины
- **WHEN** запрашиваются `DeadLetterReason.EXHAUSTED.value` и `DeadLetterReason.NON_RETRYABLE.value`
- **THEN** возвращаются `"exhausted"` и `"non_retryable"`

#### Scenario: Старый вызов mark_dead_lettered
- **WHEN** вызван `mark_dead_lettered(job_id, error)` без `reason`
- **THEN** запись dead-letter имеет `reason` = `EXHAUSTED`

### Requirement: Bulk requeue of dead-lettered jobs
`JobQueue.requeue_all_dead_letters(job_type: str | None = None)` SHALL перезапускать записи dead-letter в порядке
`dead_letters()`. Если `job_type` не указан (`None`), перезапускаются все записи; иначе только записи с этим типом
задания. Каждое задание SHALL перезапускаться так же, как через `requeue_dead_letter`: тот же `id`, статус `PENDING`,
счётчик `jobs.requeued` увеличивается на 1 за каждое задание, запись из dead-letter удаляется. Метод SHALL возвращать
список перезапущенных заданий в том же порядке. Если перезапускать нечего, метод SHALL возвращать пустой список и
MUST NOT выбрасывать исключение. Записи других типов SHALL оставаться в dead-letter.

#### Scenario: Перезапуск всего содержимого dead-letter
- **WHEN** в dead-letter три записи, и вызван `requeue_all_dead_letters()`
- **THEN** возвращается список из трёх заданий в порядке `dead_letters()`, все три в статусе `PENDING`, `dead_letters()` пуст, а `jobs.requeued` увеличен на 3

#### Scenario: Перезапуск только заданного типа
- **WHEN** в dead-letter есть задания типов `billing` и `mail`, и вызван `requeue_all_dead_letters("billing")`
- **THEN** возвращаются только задания типа `billing`, а запись типа `mail` остаётся в `dead_letters()`

#### Scenario: Пустой dead-letter
- **WHEN** dead-letter пуст, или в нём нет записей запрошенного типа, и вызван `requeue_all_dead_letters("billing")`
- **THEN** возвращается пустой список, без исключения

#### Scenario: Перезапущенные задания получают новые попытки
- **WHEN** задания возвращены через `requeue_all_dead_letters()`, и воркер выполняет очередь
- **THEN** `attempts` каждого задания стартует с 1, а новые задания не создаются
