## MODIFIED Requirements

### Requirement: Исход падения обработчика
Когда обработчик бросает исключение, воркер SHALL перевести задание так: (1) если для типа нет обработчика — в `FAILED` без повторов, независимо от политики; (2) иначе, если политики нет — в `FAILED` (прежнее поведение); (3) иначе, если ошибка неповторяемая (`is_retryable` вернул `False`, включая `PermanentJobError`) — в `DEAD_LETTERED` с причиной `DeadLetterReason.NON_RETRYABLE`, на любой попытке, без повторов; (4) иначе, если `job.attempts >= max_attempts` — в `DEAD_LETTERED` с причиной `DeadLetterReason.EXHAUSTED`, в том числе когда последней ошибкой была `RetryLaterError`; (5) иначе — в `RETRY_SCHEDULED` с `run_at = now + delay`, где `now` берётся из часов очереди, а `delay` равен `delay_for(job.attempts, rng)`, либо, для `RetryLaterError`, `min(retry_after, max_delay)`. К задержке `RetryLaterError` джиттер SHALL NOT применяться. Неповторяемая ошибка на последней попытке SHALL получать `NON_RETRYABLE`, а не `EXHAUSTED`. Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. `max_attempts == 1` означает «без повторов, но в dead-letter», а не `FAILED`. Счётчик `jobs.failed` SHALL NOT расти при переходе в `DEAD_LETTERED`; `jobs.dead_lettered` растёт.

#### Scenario: Без политики
- **WHEN** политики нет и обработчик бросил исключение, в том числе `PermanentJobError`
- **THEN** статус `FAILED`, `jobs.failed` увеличен на 1, записи в dead-letter нет

#### Scenario: Планирование повтора
- **WHEN** действует `RetryPolicy(max_attempts=3, base_delay=1, factor=2)`, обработчик упал на первой попытке в момент `T`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 1s`, `error` содержит ошибку, `jobs.retried == 1`

#### Scenario: Исчерпание попыток
- **WHEN** `max_attempts=3` и обработчик упал обычной ошибкой на третьей попытке
- **THEN** статус `DEAD_LETTERED`, `dead_letters()` содержит запись с `attempts == 3`, последней ошибкой и `reason == DeadLetterReason.EXHAUSTED`, `jobs.dead_lettered == 1`, `jobs.failed` не изменён

#### Scenario: max_attempts равно 1
- **WHEN** `max_attempts=1` и обработчик упал обычной ошибкой
- **THEN** статус `DEAD_LETTERED` с причиной `exhausted`, а не `FAILED` и не `RETRY_SCHEDULED`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** политика есть, `max_attempts=3`, обработчик бросил `PermanentJobError`, либо ошибку из `non_retryable` (в том числе наследника), на первой попытке
- **THEN** статус `DEAD_LETTERED`, запись в `dead_letters()` с `attempts == 1` и `reason == NON_RETRYABLE`, повтор не планируется, `jobs.retried` не изменён, `jobs.failed` не изменён

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик бросил неповторяемую ошибку на последней попытке
- **THEN** статус `DEAD_LETTERED`, `reason == NON_RETRYABLE`

#### Scenario: RetryLaterError планирует повтор по времени сервера
- **WHEN** `RetryPolicy(max_attempts=3, base_delay=1, max_delay=60)` и обработчик бросил `RetryLaterError(retry_after=30)` на первой попытке в момент `T`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 30s`, `jobs.retried == 1`

#### Scenario: RetryLaterError режется потолком
- **WHEN** `max_delay=60` и обработчик бросил `RetryLaterError(retry_after=3600)` не на последней попытке
- **THEN** `run_at == now + 60s`

#### Scenario: RetryLaterError не использует джиттер и rng
- **WHEN** `jitter=0.5`, передан `rng`, обработчик бросил `RetryLaterError(retry_after=10)`
- **THEN** `run_at == now + 10s`, ни один метод `rng` не вызывался

#### Scenario: RetryLaterError с нулевой задержкой
- **WHEN** обработчик бросил `RetryLaterError(retry_after=0)` не на последней попытке
- **THEN** `run_at == now`, статус `RETRY_SCHEDULED`

#### Scenario: RetryLaterError на последней попытке
- **WHEN** обработчик бросил `RetryLaterError(retry_after=5)` на последней попытке
- **THEN** статус `DEAD_LETTERED`, `reason == EXHAUSTED`

#### Scenario: RetryLaterError без политики
- **WHEN** политики нет и брошена `RetryLaterError`
- **THEN** статус `FAILED`

#### Scenario: Нет обработчика
- **WHEN** для типа задания не зарегистрирован обработчик, а политика есть
- **THEN** статус `FAILED`, повтор не планируется, в dead-letter записи нет

#### Scenario: Повтор исполняется
- **WHEN** задание в `RETRY_SCHEDULED`, время `run_at` ещё не наступило
- **THEN** воркер его не берёт; после наступления `run_at` берёт как любое готовое задание, с сортировкой по `(run_at, seq)`

### Requirement: Использование rng воркером
`Worker` SHALL принимать keyword-only параметр `rng: random.Random | None = None` и передавать его в `delay_for`. Воркер SHALL обращаться к `rng` только когда реально планируется повтор по задержке политики (и только при `jitter > 0`): при исходах `FAILED` и `DEAD_LETTERED`, а также при повторе после `RetryLaterError`, задержка политики не вычисляется и `rng` не трогается. Один повтор с джиттером — ровно один вызов `rng.uniform`.

#### Scenario: Исходы без повтора не трогают rng
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED`, в том числе по неповторяемой ошибке
- **THEN** вызовов `rng.uniform` не было

#### Scenario: Один вызов на повтор
- **WHEN** планируется повтор обычной ошибки при `jitter > 0`
- **THEN** выполнен ровно один вызов `rng.uniform`

#### Scenario: RetryLaterError не трогает rng
- **WHEN** планируется повтор после `RetryLaterError` при `jitter > 0`
- **THEN** вызовов `rng.uniform` не было

### Requirement: Dead-letter очередь
`DeadLetterReason(str, Enum)` в `jobq/models.py` SHALL иметь значения `EXHAUSTED = "exhausted"` и `NON_RETRYABLE = "non_retryable"`. `dead_letters()` SHALL возвращать новый список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at, reason)` в порядке попадания; `dead_lettered_at` берётся из часов очереди, `reason` — причина попадания (последнее поле, по умолчанию `EXHAUSTED`). `JobQueue.mark_dead_lettered` SHALL принимать дополнительный keyword-only `reason` со значением по умолчанию `EXHAUSTED`. `requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` равен текущему времени, `error = None`, `attempts = 0`, запись из dead-letter удаляется, `jobs.requeued` увеличивается на 1. Для неизвестного id SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`. `requeue_all_dead_letters(job_type: str | None = None) -> list[Job]` SHALL перезапускать каждую запись dead-letter (при `job_type` не `None` — только записи этого типа) ровно так же, как `requeue_dead_letter`, в порядке `dead_letters()`, и возвращать список перезапущенных заданий в этом порядке; если перезапускать нечего, SHALL возвращаться пустой список без ошибки; пустая строка `job_type` SHALL давать `ConfigError`. `purge_finished(older_than)` SHALL удалять также задания в `DEAD_LETTERED`, у которых `dead_lettered_at <= now - older_than`, вместе с их записями в `dead_letters()`; прочие правила очистки и возвращаемое значение (число удалённых заданий, включая dead-letter) не меняются.

#### Scenario: Порядок записей
- **WHEN** сначала в dead-letter попало задание A, затем B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Причина в записи
- **WHEN** задание A исчерпало попытки, а задание B упало неповторяемой ошибкой
- **THEN** `reason` записи A равен `DeadLetterReason.EXHAUSTED` (`"exhausted"`), записи B — `DeadLetterReason.NON_RETRYABLE` (`"non_retryable"`)

#### Scenario: Старый вызов mark_dead_lettered
- **WHEN** вызывается `mark_dead_lettered(job_id, error)` без `reason`
- **THEN** запись создаётся с `reason == EXHAUSTED`

#### Scenario: Возврат в работу
- **WHEN** вызывается `requeue_dead_letter(id)` для задания с `attempts == 3`
- **THEN** возвращается тот же объект `Job` со статусом `PENDING`, `attempts == 0`, `error is None`, `run_at == now`; `dead_letters()` его не содержит; после первой же новой ошибки (при `max_attempts > 1`) задание не уходит снова в dead-letter

#### Scenario: Requeue не из dead-letter
- **WHEN** `requeue_dead_letter` вызывается для `FAILED` или `PENDING` задания
- **THEN** выбрасывается `InvalidTransitionError`, состояние не меняется

#### Scenario: Массовый requeue всего dead-letter
- **WHEN** в dead-letter лежат задания A (тип `a`), B (тип `b`), C (тип `a`) в этом порядке и вызывается `requeue_all_dead_letters()`
- **THEN** возвращается `[A, B, C]` (те же объекты `Job`), все в `PENDING` с `attempts == 0`, `dead_letters()` пуст, `jobs.requeued` увеличен на 3

#### Scenario: Массовый requeue по типу
- **WHEN** в dead-letter лежат A (тип `a`), B (тип `b`), C (тип `a`) и вызывается `requeue_all_dead_letters("a")`
- **THEN** возвращается `[A, C]`, B остаётся в `DEAD_LETTERED` и в `dead_letters()`

#### Scenario: Массовый requeue нечего перезапускать
- **WHEN** dead-letter пуст, либо в нём нет заданий запрошенного типа
- **THEN** возвращается `[]`, состояние и счётчики не меняются

#### Scenario: Purge чистит dead-letter по возрасту
- **WHEN** задание попало в dead-letter в момент `T`, часы на `T + 100s` и вызывается `purge_finished(50)`
- **THEN** задание удалено из хранилища, `dead_letters()` его не содержит, возвращаемое число и `jobs.purged` учитывают его

#### Scenario: Purge не трогает dead-letter
- **WHEN** задание попало в dead-letter в момент `T`, часы на `T + 10s` и вызывается `purge_finished(50)`
- **THEN** задание остаётся в хранилище и в `dead_letters()`

#### Scenario: Возраст считается от попадания в dead-letter
- **WHEN** задание давно создано и запущено, но попало в dead-letter только что, и вызывается `purge_finished(60)`
- **THEN** оно не удаляется

#### Scenario: Purge с нулевым возрастом
- **WHEN** выполняется `purge_finished(0)` при наличии заданий `DEAD_LETTERED`, `FAILED`, `SUCCEEDED`, `CANCELLED`
- **THEN** удаляются все эти задания, `dead_letters()` пуст
