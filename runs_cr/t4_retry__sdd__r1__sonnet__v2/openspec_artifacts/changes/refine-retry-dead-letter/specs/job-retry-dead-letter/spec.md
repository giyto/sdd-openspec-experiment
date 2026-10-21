## MODIFIED Requirements

### Requirement: Статус задания после падения обработчика
Когда обработчик бросил исключение и действует политика, воркер SHALL выбирать статус в таком порядке: (1) если ошибка неповторяемая (`is_retryable` ложно) — `DEAD_LETTERED` с причиной `non_retryable`, даже на последней попытке, без повторов; (2) иначе, если `job.attempts >= max_attempts` — `DEAD_LETTERED` с причиной `exhausted`; (3) иначе — `RETRY_SCHEDULED` с `run_at = now + задержка`, где задержка равна `delay_for(job.attempts, rng)`, а для `RetryLaterError` определяется отдельным требованием. Неповторяемая ошибка на последней попытке получает `non_retryable`. `max_attempts=1` означает «без повторов, но в dead-letter». Если действующей политики для типа нет, любое исключение SHALL переводить задание в `FAILED`. Отсутствие обработчика для типа задания — ошибка конфигурации: `FAILED` сразу, без повтора, независимо от политики. Переход в `DEAD_LETTERED` по любой причине увеличивает `jobs.dead_lettered`, `jobs.failed` при этом не меняется. В `job.error` SHALL всегда лежать последняя ошибка в формате `"ИмяКласса: сообщение"`, а при успешном выполнении `error` SHALL быть `None`. `attempts` не сбрасывается при повторах.

#### Scenario: Повтор запланирован
- **WHEN** политика `max_attempts=3, base_delay=1, factor=2`, время 12:00:00, обработчик упал на первой попытке с `TimeoutError`
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равен 12:00:01, `error` начинается с `"TimeoutError"`, `jobs.retried` равен 1

#### Scenario: Попытки исчерпаны
- **WHEN** обработчик упал с повторяемой ошибкой на третьей попытке при `max_attempts=3`
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` есть запись с `attempts=3`, последней ошибкой и `reason == exhausted`

#### Scenario: max_attempts равен 1
- **WHEN** `max_attempts=1` и обработчик упал с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED` с причиной `exhausted`, не `FAILED`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** при `max_attempts=3` обработчик бросил `PermanentJobError` (или класс из `non_retryable`) на первой попытке
- **THEN** статус `DEAD_LETTERED`, запись с `reason == non_retryable` и `attempts=1`, повтор не планируется, `jobs.dead_lettered` +1, `jobs.failed` и `jobs.retried` не меняются

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик бросил `PermanentJobError` на последней попытке
- **THEN** статус `DEAD_LETTERED`, `reason == non_retryable`

#### Scenario: Нет политики
- **WHEN** для типа нет действующей политики и обработчик бросил `PermanentJobError`
- **THEN** задание `FAILED`, записи в dead-letter нет

#### Scenario: Нет обработчика для типа
- **WHEN** для типа задания не зарегистрирован обработчик, а политика есть
- **THEN** задание сразу `FAILED`, повтор не планируется, записи в dead-letter нет

#### Scenario: Успех после повтора
- **WHEN** задание в `RETRY_SCHEDULED` при следующем запуске выполнилось успешно
- **THEN** статус `SUCCEEDED` и `error` равен `None`

### Requirement: Генератор случайных чисел воркера
`Worker` SHALL принимать keyword-only параметр `rng` (`random.Random | None`) и использовать его только при планировании повтора по задержке политики: задержка не рассчитывается и `rng` не трогается при уходе в `DEAD_LETTERED` (по любой причине) или `FAILED`, а также при планировании повтора после `RetryLaterError`. При `jitter == 0` `rng` не вызывается и при планировании повтора.

#### Scenario: rng не трогается без повтора
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED` (в том числе по неповторяемой ошибке) при `jitter > 0`
- **THEN** `rng.uniform` не вызывался

#### Scenario: Один вызов на один повтор
- **WHEN** планируется один повтор по политике при `jitter > 0`
- **THEN** `rng.uniform` вызван ровно один раз

#### Scenario: RetryLaterError не трогает rng
- **WHEN** планируется повтор после `RetryLaterError` при `jitter > 0`
- **THEN** `rng.uniform` не вызывался

### Requirement: Dead-letter очередь
`dead_letters()` SHALL возвращать список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at, reason)` в порядке попадания в dead-letter; изменение возвращённого списка не влияет на очередь. `dead_lettered_at` — время очереди в момент перехода. `reason` имеет тип `DeadLetterReason` и принимает значения `exhausted` (кончились попытки) или `non_retryable` (неповторяемая ошибка); поле идёт в `DeadLetterEntry` последним и имеет значение по умолчанию `exhausted`, так что прежние вызовы конструктора с пятью аргументами работают. `purge_finished` SHALL удалять задания `DEAD_LETTERED` по тому же правилу возраста, что и завершённые, считая возраст от `dead_lettered_at`: удаляется задание с `dead_lettered_at <= now - older_than`. Удалённое задание SHALL исчезать и из хранилища, и из `dead_letters()`; оно учитывается в возвращаемом количестве и в счётчике `jobs.purged`. Не достигшие возраста записи остаются до `requeue_dead_letter`.

#### Scenario: Порядок записей
- **WHEN** сначала в dead-letter попало задание A, затем B
- **THEN** `dead_letters()` возвращает записи A, B

#### Scenario: Причина в записи
- **WHEN** одно задание исчерпало попытки, другое упало с `PermanentJobError`
- **THEN** их записи имеют `reason` `exhausted` и `non_retryable` соответственно

#### Scenario: purge_finished
- **WHEN** есть `DEAD_LETTERED` задание, вызван `purge_finished()` с `older_than=0`
- **THEN** задание удалено из хранилища и из `dead_letters()`

#### Scenario: purge_finished удаляет старый dead-letter
- **WHEN** задание попало в dead-letter 100 секунд назад, вызван `purge_finished(older_than=50)`
- **THEN** возвращено 1, задание отсутствует в хранилище и в `dead_letters()`, `jobs.purged` +1

#### Scenario: purge_finished не трогает свежий dead-letter
- **WHEN** задание попало в dead-letter 10 секунд назад, вызван `purge_finished(older_than=50)`
- **THEN** возвращено 0, задание остаётся в хранилище и в `dead_letters()`

#### Scenario: Возраст считается от попадания в dead-letter
- **WHEN** задание создано давно, но попало в dead-letter только что
- **THEN** `purge_finished(older_than=50)` его не удаляет

## ADDED Requirements

### Requirement: Повтор по запросу внешнего сервиса
Пакет SHALL предоставлять `RetryLaterError(message="", *, retry_after)`, наследник `JobqError`, с атрибутом `retry_after` (секунды, `float`). `retry_after < 0` и NaN SHALL вызывать `ConfigError` при создании исключения. `RetryLaterError` — обычная временная ошибка: при действующей политике она планирует повтор; если её класс входит в `non_retryable` политики, действует правило неповторяемых ошибок. Задержка до следующей попытки SHALL равна `min(retry_after, max_delay)` политики вместо задержки по `delay_for`; джиттер SHALL NOT применяться, `rng` SHALL NOT вызываться. Если `job.attempts >= max_attempts`, задание уходит в `DEAD_LETTERED` с причиной `exhausted`. Без действующей политики — `FAILED`, как для любой ошибки. `job.error` имеет формат `"RetryLaterError: сообщение"`.

#### Scenario: Retry-After в пределах потолка
- **WHEN** политика с `max_delay=60`, `jitter=0.5`, время 12:00:00, обработчик бросил `RetryLaterError(retry_after=10)` на первой попытке
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равен 12:00:10, `rng.uniform` не вызывался, `jobs.retried` +1

#### Scenario: Retry-After выше потолка
- **WHEN** `max_delay=60` и `RetryLaterError(retry_after=3600)`
- **THEN** `run_at` равен текущему времени плюс 60 секунд

#### Scenario: RetryLaterError на последней попытке
- **WHEN** `RetryLaterError(retry_after=5)` брошена на последней попытке
- **THEN** статус `DEAD_LETTERED`, `reason == exhausted`

#### Scenario: Нулевой retry_after
- **WHEN** `RetryLaterError(retry_after=0)` брошена не на последней попытке
- **THEN** повтор запланирован на текущее время

#### Scenario: Отрицательный retry_after
- **WHEN** создаётся `RetryLaterError(retry_after=-1)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Массовый возврат из dead-letter
`JobQueue.requeue_all_dead_letters(job_type=None)` SHALL возвращать в работу все задания из dead-letter или, если `job_type` задан, только задания этого типа. Каждое задание SHALL перезапускаться так же, как через `requeue_dead_letter` (`PENDING`, `run_at` равен текущему времени, `error is None`, `attempts == 0`, запись удалена, `jobs.requeued` +1 на каждое). Порядок перезапуска и порядок возвращаемого списка SHALL совпадать с порядком `dead_letters()` на момент вызова. Если перезапускать нечего (dead-letter пуст или нет заданий нужного типа), SHALL возвращаться пустой список без побочных эффектов и без ошибки. Задания других типов остаются в dead-letter.

#### Scenario: Перезапуск всего dead-letter
- **WHEN** в dead-letter задания A (`email`), B (`billing`), C (`email`) в таком порядке, вызван `requeue_all_dead_letters()`
- **THEN** возвращены A, B, C в этом порядке, все `PENDING` с `attempts == 0`, `dead_letters()` пуст, `jobs.requeued` +3

#### Scenario: Фильтр по типу
- **WHEN** тот же состав, вызван `requeue_all_dead_letters("email")`
- **THEN** возвращены A, C; B остаётся в dead-letter в статусе `DEAD_LETTERED`

#### Scenario: Нечего перезапускать
- **WHEN** dead-letter пуст либо нет заданий запрошенного типа
- **THEN** возвращён `[]`, `jobs.requeued` не меняется
