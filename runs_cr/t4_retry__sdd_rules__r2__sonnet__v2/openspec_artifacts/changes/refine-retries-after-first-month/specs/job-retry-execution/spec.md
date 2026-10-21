## ADDED Requirements

### Requirement: Повтор по RetryLaterError
Если обработчик бросил `RetryLaterError` и по решению воркера задание уходит в `RETRY_SCHEDULED`, воркер SHALL установить `run_at = now + min(exc.retry_after, policy.max_delay)` секунд, где `now` — текущее время часов очереди. Задержка из политики (`delay_for`) в этом случае не используется, джиттер не применяется, а `rng` MUST NOT вызываться. `max_delay` остаётся потолком для любой задержки. Во всём остальном (метрики, `attempts`, `error` в формате `"RetryLaterError: сообщение"`) `RetryLaterError` обрабатывается как обычная повторяемая ошибка: если действует политика и попытки не исчерпаны — `RETRY_SCHEDULED`; на последней попытке — `DEAD_LETTERED` с причиной `exhausted`; без политики — `FAILED`. Если класс `RetryLaterError` входит в `non_retryable` политики, применяется правило неповторяемой ошибки.

#### Scenario: Задержка из Retry-After
- **WHEN** действует `RetryPolicy(max_delay=60.0, jitter=0.5)`, обработчик на первой попытке бросает `RetryLaterError(retry_after=30)`, часы показывают T
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 30 секунд`, подсчитывающий `rng` не вызван

#### Scenario: Retry-After режется потолком
- **WHEN** `max_delay=60.0` и обработчик бросает `RetryLaterError(retry_after=3600)`
- **THEN** `run_at == T + 60 секунд`

#### Scenario: Нулевой retry_after
- **WHEN** обработчик бросает `RetryLaterError(retry_after=0)`
- **THEN** `run_at == T`, задание выбирается воркером сразу

#### Scenario: RetryLaterError на последней попытке
- **WHEN** `max_attempts=3` и на третьей попытке обработчик бросает `RetryLaterError(retry_after=5)`
- **THEN** статус `DEAD_LETTERED`, `reason == DeadLetterReason.EXHAUSTED`, `rng` не вызван

#### Scenario: RetryLaterError без политики
- **WHEN** политик нет и обработчик бросает `RetryLaterError(retry_after=5)`
- **THEN** статус `FAILED`, `error == "RetryLaterError: <сообщение>"`

#### Scenario: Счётчики
- **WHEN** задание уходит в `RETRY_SCHEDULED` по `RetryLaterError`
- **THEN** `jobs.retried` увеличивается на 1

## MODIFIED Requirements

### Requirement: Решение воркера при падении обработчика
Когда обработчик бросил исключение (`Exception`), воркер SHALL выбрать итоговый статус по политике, действующей в момент ошибки (а не при постановке), в таком порядке: (1) политики нет — `FAILED` (поведение до JOBQ-212); (2) ошибка неповторяемая по `is_retryable` (включая `PermanentJobError`) — `DEAD_LETTERED` с причиной `non_retryable` без повторов, в том числе на последней попытке; (3) `job.attempts >= max_attempts` — `DEAD_LETTERED` с причиной `exhausted`; (4) иначе `RETRY_SCHEDULED`. В `job.error` MUST лежать последняя ошибка в формате `"ИмяКласса: сообщение"`. `max_attempts=1` означает «без повторов, но в dead-letter», а не в `FAILED` (если политика действует). Отсутствие зарегистрированного обработчика не является ошибкой обработчика и по-прежнему даёт `FAILED`.

#### Scenario: Без политики — как раньше
- **WHEN** политик нет и обработчик бросает `RuntimeError("boom")` или `PermanentJobError("x")`
- **THEN** задание получает статус `FAILED`, `error == "RuntimeError: boom"` (соответственно `"PermanentJobError: x"`), счётчики `jobs.retried` и `jobs.dead_lettered` равны 0

#### Scenario: Повторяемая ошибка планирует повтор
- **WHEN** действует `RetryPolicy(max_attempts=3)` и обработчик бросает `TimeoutError("gw")` на первой попытке
- **THEN** статус задания `RETRY_SCHEDULED`, `attempts == 1`, `error == "TimeoutError: gw"`

#### Scenario: Попытки кончились
- **WHEN** действует `RetryPolicy(max_attempts=3)` и обработчик падает повторяемой ошибкой на третьей попытке
- **THEN** статус `DEAD_LETTERED`, `attempts == 3`, `error` содержит последнюю ошибку, причина `exhausted`

#### Scenario: max_attempts=1 ведёт в dead-letter
- **WHEN** действует `RetryPolicy(max_attempts=1)` и обработчик падает повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED`, причина `exhausted`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** действует политика и обработчик бросает `PermanentJobError("bad")` на первой из 3 попыток
- **THEN** статус `DEAD_LETTERED`, `attempts == 1`, в `dead_letters()` одна запись с причиной `non_retryable`, `jobs.retried` не растёт, `jobs.failed` не растёт, `jobs.dead_lettered == 1`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** `max_attempts=3`, `non_retryable=(ValueError,)` и на третьей попытке обработчик бросает `ValueError`
- **THEN** статус `DEAD_LETTERED`, причина `non_retryable` (а не `exhausted`)

#### Scenario: Наследник неповторяемой ошибки
- **WHEN** `non_retryable=(ValueError,)` и обработчик бросает наследника `ValueError`
- **THEN** статус `DEAD_LETTERED`, причина `non_retryable`

#### Scenario: rng не трогается при неповторяемой ошибке
- **WHEN** `jitter > 0` и обработчик бросает неповторяемую ошибку
- **THEN** подсчитывающий `rng` не вызван

#### Scenario: Политика берётся на момент ошибки
- **WHEN** задание поставлено без политики, затем до запуска вызван `set_retry_policy` для его типа, и обработчик падает повторяемой ошибкой
- **THEN** применяется заданная политика, и задание получает `RETRY_SCHEDULED`

#### Scenario: Нет обработчика — не повторяем
- **WHEN** для типа задания нет зарегистрированного обработчика, а политика действует
- **THEN** задание сразу получает `FAILED` с ошибкой `UnknownJobTypeError`, в dead-letter не попадает, `rng` не используется, повтор не планируется

### Requirement: Планирование повтора
При переходе в `RETRY_SCHEDULED` воркер SHALL установить `run_at = now + delay`, где `now` — текущее время часов очереди, `delay` — `delay_for(job.attempts, rng)` политики (для `RetryLaterError` — задержка по требованию «Повтор по RetryLaterError»), а `rng` — генератор, переданный в `Worker(queue, registry, *, name="worker", rng: random.Random | None = None)`. `rng` MUST использоваться только при реальном планировании повтора по задержке политики: для заданий, ушедших в `FAILED` или `DEAD_LETTERED`, и для повторов по `RetryLaterError` задержка не считается и `rng` не вызывается. Задание в `RETRY_SCHEDULED` воркер SHALL брать в работу, когда наступил его `run_at`, наравне с `PENDING` (порядок по `run_at`, затем по порядку постановки); раньше `run_at` оно не выбирается.

#### Scenario: Время следующей попытки
- **WHEN** задание упало на второй попытке, `RetryPolicy(base_delay=1.0, factor=2.0)`, часы показывают T
- **THEN** `run_at == T + 2 секунды`

#### Scenario: Повтор не выбирается раньше срока
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at = T + 2s`, часы показывают `T + 1s`
- **THEN** `run_pending()` возвращает 0, задание остаётся в `RETRY_SCHEDULED`

#### Scenario: Повтор выполняется в срок
- **WHEN** часы сдвинуты до `T + 2s` и следующая попытка успешна
- **THEN** задание проходит `RUNNING` и становится `SUCCEEDED`, `error is None`

#### Scenario: rng не трогается без повтора
- **WHEN** `jitter > 0`, задание уходит в `FAILED` или `DEAD_LETTERED`
- **THEN** подсчитывающий `rng` не вызван ни разу

#### Scenario: Один uniform на один повтор
- **WHEN** `jitter > 0` и задание уходит в `RETRY_SCHEDULED` по обычной повторяемой ошибке
- **THEN** `rng.uniform` вызван ровно один раз, а `run_at` не позже `now + расчётная задержка`

### Requirement: Обратная совместимость
Сигнатуры существующих публичных методов MUST NOT меняться; новые параметры только keyword-only и необязательные. Публичные имена `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry`, `RetryLaterError`, `DeadLetterReason` SHALL экспортироваться из пакета `jobq`. `jobq/dashboard.py` и `jobq/cli.py` MUST NOT изменяться. Создание `DeadLetterEntry` пятью позиционными аргументами (без `reason`) SHALL продолжать работать; `reason` в этом случае равен `DeadLetterReason.EXHAUSTED`.

#### Scenario: Старые вызовы
- **WHEN** используются `JobQueue()`, `JobQueue(store, clock=c, metrics=m)`, `Worker(queue, registry)`, `Worker(queue, registry, name="w")`
- **THEN** они работают как до изменения

#### Scenario: Экспорт новых имён
- **WHEN** выполняется `from jobq import RetryLaterError, DeadLetterReason`
- **THEN** импорт успешен

#### Scenario: Запись без reason
- **WHEN** создаётся `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`
- **THEN** запись создаётся, `reason == DeadLetterReason.EXHAUSTED`
