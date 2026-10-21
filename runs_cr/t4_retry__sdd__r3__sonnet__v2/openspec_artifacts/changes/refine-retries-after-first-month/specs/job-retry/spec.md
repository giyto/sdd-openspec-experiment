## MODIFIED Requirements

### Requirement: Исход падения обработчика
Когда обработчик бросил `Exception`, воркер SHALL использовать политику, действующую в момент ошибки (а не в момент постановки), и выбрать исход в таком порядке:
1. политики нет → `FAILED` (как раньше);
2. ошибка неповторяемая (`is_retryable` ложно, включая `PermanentJobError`) → `DEAD_LETTERED` с причиной `non_retryable`, сразу и без повторов, в том числе на последней попытке;
3. `job.attempts >= max_attempts` → `DEAD_LETTERED` с причиной `exhausted`; это относится и к `RetryLaterError` на последней попытке;
4. иначе → `RETRY_SCHEDULED` с `run_at = now + задержка`, где задержка равна `delay_for(job.attempts, rng)` для обычных ошибок, а для `RetryLaterError` — `min(retry_after, max_delay)` политики (без джиттера).

Приоритет причины: неповторяемая ошибка на последней попытке получает `non_retryable`, а не `exhausted`. `RetryLaterError` классифицируется как обычная временная ошибка по тем же правилам `is_retryable`; она неповторяемая, только если политика явно относит её к `non_retryable`. В `job.error` MUST всегда лежать последняя ошибка в формате `"ИмяКласса: сообщение"`. При `max_attempts=1` первое же падение повторяемой ошибкой даёт `DEAD_LETTERED`, а не `FAILED`.

#### Scenario: Повтор запланирован
- **WHEN** политика `max_attempts=3, base_delay=1, factor=2`, обработчик упал с `TimeoutError("gw")` на первой попытке в момент T
- **THEN** статус `RETRY_SCHEDULED`, `run_at = T + 1s`, `error = "TimeoutError: gw"`, `attempts = 1`

#### Scenario: Попытки кончились
- **WHEN** обработчик падает повторяемой ошибкой на третьей попытке при `max_attempts=3`
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` запись с `reason = exhausted`, повтор не планируется

#### Scenario: max_attempts=1
- **WHEN** политика с `max_attempts=1` и обработчик упал повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED` с `reason = exhausted`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** действует политика с `max_attempts=5`, обработчик бросил `PermanentJobError("bad data")` (или класс из `non_retryable`) на первой попытке
- **THEN** статус `DEAD_LETTERED`, запись в `dead_letters()` с `reason = non_retryable`, `attempts = 1`, `error = "PermanentJobError: bad data"`, повтор не планируется, `jobs.failed` не растёт

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик бросил неповторяемую ошибку на последней попытке (`attempts == max_attempts`)
- **THEN** статус `DEAD_LETTERED`, `reason = non_retryable`

#### Scenario: Нет обработчика для типа
- **WHEN** для типа задания не зарегистрирован обработчик, даже при действующей политике
- **THEN** задание сразу получает `FAILED` без повторов и без записи в dead-letter

#### Scenario: Политика берётся на момент ошибки
- **WHEN** между постановкой и падением политика типа была изменена или снята
- **THEN** решение принимается по политике, действующей в момент падения

#### Scenario: Без политики
- **WHEN** ни дефолта, ни политики типа нет и обработчик упал (в том числе неповторяемой ошибкой или `RetryLaterError`)
- **THEN** задание получает `FAILED`, как и до изменения, в dead-letter не попадает

#### Scenario: RetryLaterError планирует повтор по времени сервера
- **WHEN** политика `max_attempts=3, max_delay=60, jitter=0.5`, обработчик на первой попытке в момент T бросил `RetryLaterError("billing", retry_after=30)`
- **THEN** статус `RETRY_SCHEDULED`, `run_at = T + 30s`, `error = "RetryLaterError: billing"`, `attempts = 1`

#### Scenario: Retry-After режется до max_delay
- **WHEN** `max_delay=60`, обработчик бросил `RetryLaterError(retry_after=3600)` не на последней попытке в момент T
- **THEN** `run_at = T + 60s`

#### Scenario: RetryLaterError с нулевым ожиданием
- **WHEN** обработчик бросил `RetryLaterError(retry_after=0)` не на последней попытке в момент T
- **THEN** `run_at = T`, статус `RETRY_SCHEDULED`

#### Scenario: RetryLaterError на последней попытке
- **WHEN** обработчик бросил `RetryLaterError` на последней попытке
- **THEN** статус `DEAD_LETTERED`, `reason = exhausted`

### Requirement: Использование rng воркером
Воркер SHALL принимать keyword-only `rng: random.Random | None`. `rng` MUST использоваться только при планировании повтора обычной ошибки: один вызов `uniform` на одну задержку при `jitter > 0`, ни одного при `jitter = 0`. При исходах `FAILED` и `DEAD_LETTERED`, а также при повторе после `RetryLaterError` (задержка берётся из `retry_after`, джиттер не применяется) задержка по политике не вычисляется и `rng` не трогается.

#### Scenario: Предсказуемый rng
- **WHEN** воркер создан с `random.Random(seed)`, `jitter>0`, и запланирован один повтор обычной ошибки
- **THEN** `run_at` равен `now + delay_for(attempts, Random(seed))` для того же seed, а задержка не больше расчётной без джиттера

#### Scenario: rng не расходуется без повтора
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED` (по любой причине)
- **THEN** состояние `rng` не меняется

#### Scenario: rng не расходуется при RetryLaterError
- **WHEN** при `jitter>0` запланирован повтор после `RetryLaterError`
- **THEN** состояние `rng` не меняется, `uniform` не вызывался
