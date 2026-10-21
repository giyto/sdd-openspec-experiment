## ADDED Requirements

### Requirement: RetryLaterError
Система SHALL предоставлять `RetryLaterError` в `jobq/errors.py`, наследник `JobqError`, с конструктором `RetryLaterError(message: str = "", *, retry_after: float)` и атрибутом `retry_after: float` (секунды). `retry_after` SHALL быть keyword-only и обязательным. Значение `retry_after < 0`, а также нечисловое или нефинитное (NaN, бесконечность), SHALL приводить к `ConfigError` при создании исключения; `retry_after == 0` допустимо. Обработчик бросает её, когда внешний сервис сам указал время следующей попытки. Для политики повторов это обычная повторяемая ошибка (классификация `is_retryable` не меняется), отличающаяся только способом выбора задержки (см. «Исход упавшего задания в воркере»).

#### Scenario: Создание с retry_after
- **WHEN** создаётся `RetryLaterError("billing busy", retry_after=30)`
- **THEN** `retry_after == 30`, `str(exc) == "billing busy"`, исключение является `JobqError`

#### Scenario: Отрицательный retry_after
- **WHEN** создаётся `RetryLaterError(retry_after=-1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Нулевой retry_after
- **WHEN** создаётся `RetryLaterError(retry_after=0)`
- **THEN** исключение создано, `retry_after == 0`

## MODIFIED Requirements

### Requirement: Расчёт задержки delay_for
`delay_for(attempt, rng=None)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1)`, то есть джиттер только уменьшает задержку и никогда не увеличивает её. Метод SHALL работать для любого `attempt >= 1` без исключений переполнения (в том числе при `attempt` порядка 5000 и более) и при `base_delay == 0` (результат `0`), а результат SHALL всегда лежать в `[0, max_delay]`. При `jitter == 0` `rng` SHALL NOT использоваться; при `jitter > 0` SHALL вызываться ровно один `rng.uniform` на одну задержку. Если `rng` не передан при `jitter > 0`, SHALL использоваться собственный генератор случайных чисел. При `attempt < 1` SHALL выбрасываться `ConfigError`.

#### Scenario: Экспоненциальный рост
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=60)` и вызывается `delay_for(1)`, `delay_for(2)`, `delay_for(4)`
- **THEN** возвращаются `1.0`, `2.0`, `8.0`

#### Scenario: Ограничение потолком
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=60)` и вызывается `delay_for(10)`
- **THEN** возвращается `60.0`

#### Scenario: Огромный номер попытки
- **WHEN** `RetryPolicy(max_attempts=10000, factor=2.0)` и вызывается `delay_for(5000)`
- **THEN** возвращается `max_delay` без `OverflowError`

#### Scenario: Нулевая базовая задержка при огромном номере попытки
- **WHEN** `RetryPolicy(base_delay=0, factor=2.0)` и вызывается `delay_for(5000)`
- **THEN** возвращается `0` (не NaN)

#### Scenario: Джиттер уменьшает задержку
- **WHEN** `base_delay=10`, `jitter=0.2`, вызывается `delay_for(1, rng)` и `rng.uniform(0.8, 1)` возвращает `0.9`
- **THEN** возвращается `9.0`

#### Scenario: Диапазон джиттера односторонний
- **WHEN** `jitter=0.2` и вызывается `delay_for(1, rng)`
- **THEN** `rng.uniform` вызывается ровно один раз с аргументами `(0.8, 1)`, а результат не превышает расчётную задержку

#### Scenario: Джиттер применяется к ограниченной задержке
- **WHEN** `jitter=0.5`, `max_delay=60`, вызывается `delay_for(10, rng)` и `rng.uniform(0.5, 1)` возвращает `0.5`
- **THEN** результат равен `30.0` (ограниченные `60` умножены на `0.5`)

#### Scenario: Без джиттера генератор не трогается
- **WHEN** `jitter == 0` и вызывается `delay_for(3, rng)`
- **THEN** у `rng` не происходит ни одного вызова

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Исход упавшего задания в воркере
`Worker` SHALL принимать keyword-only `rng: random.Random | None = None` и при исключении обработчика выбирать исход по действующей политике типа задания:
1. политики нет — `FAILED` без повторов, как раньше;
2. ошибка неповторяемая (`is_retryable` is `False`, включая `PermanentJobError`) — `DEAD_LETTERED` сразу, без повторов, даже на первой попытке, с записью в `dead_letters()` и причиной `DeadLetterReason.NON_RETRYABLE`; эта причина ставится и на последней попытке («причина важнее счётчика»);
3. иначе, если `job.attempts >= max_attempts` — `DEAD_LETTERED` с причиной `DeadLetterReason.EXHAUSTED` (`max_attempts=1` означает «без повторов, но в dead-letter»); это же относится к `RetryLaterError` на последней попытке;
4. иначе — `RETRY_SCHEDULED` с `run_at = now + delay`, где `delay` равен `delay_for(job.attempts, rng)`, а для `RetryLaterError` — `min(retry_after, max_delay)` без джиттера.

Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. `rng` SHALL использоваться только при планировании повтора (исход 4), только при `jitter > 0` и только для ошибок, отличных от `RetryLaterError`; для исходов `FAILED` и `DEAD_LETTERED`, а также для `RetryLaterError` `rng` не используется. Для `RetryLaterError` потолок `max_delay` SHALL действовать (при `retry_after > max_delay` задержка равна `max_delay`), `retry_after == 0` даёт нулевую задержку. Если для типа нет обработчика, задание SHALL сразу получать `FAILED` независимо от политики. Задание в `RETRY_SCHEDULED` воркер SHALL брать, когда наступил его `run_at`, как любое другое готовое задание.

#### Scenario: Нет политики
- **WHEN** ни политики типа, ни дефолта нет и обработчик падает (в том числе с `PermanentJobError`)
- **THEN** задание получает `FAILED`, `jobs.failed` увеличивается на 1, в dead-letter записи нет

#### Scenario: Первая ошибка при max_attempts=3
- **WHEN** действует `RetryPolicy(max_attempts=3, base_delay=2, jitter=0)` и обработчик падает на первой попытке в момент `T`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 2 с`, `error` содержит последнюю ошибку

#### Scenario: Попытки исчерпаны
- **WHEN** `max_attempts=3` и обработчик падает третий раз повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, запись в `dead_letters()` с `reason == DeadLetterReason.EXHAUSTED`

#### Scenario: max_attempts=1
- **WHEN** `max_attempts=1` и обработчик падает с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED` с причиной `EXHAUSTED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** действует политика с `max_attempts=3` и обработчик на первой попытке бросает `PermanentJobError` или ошибку из `non_retryable`
- **THEN** статус `DEAD_LETTERED`, запись с `reason == DeadLetterReason.NON_RETRYABLE` и `attempts == 1`, повтор не планируется, `jobs.retried` и `jobs.failed` не растут

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик на последней попытке бросает `PermanentJobError` или ошибку из `non_retryable`
- **THEN** статус `DEAD_LETTERED`, `reason == DeadLetterReason.NON_RETRYABLE`

#### Scenario: Неповторяемая ошибка не использует rng
- **WHEN** `jitter > 0` и обработчик бросает неповторяемую ошибку
- **THEN** у `rng` нет ни одного вызова

#### Scenario: Нет обработчика
- **WHEN** для типа есть политика, но обработчик не зарегистрирован
- **THEN** задание сразу получает `FAILED`, повтор не планируется, в dead-letter записи нет

#### Scenario: RetryLaterError задаёт задержку
- **WHEN** действует `RetryPolicy(max_attempts=3, base_delay=2, max_delay=60, jitter=0.5)`, обработчик на первой попытке в момент `T` бросает `RetryLaterError(retry_after=10)` и передан `rng`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 10 с`, у `rng` нет ни одного вызова

#### Scenario: RetryLaterError режется потолком
- **WHEN** `max_delay=60` и обработчик бросает `RetryLaterError(retry_after=3600)` в момент `T`
- **THEN** `run_at == T + 60 с`

#### Scenario: RetryLaterError на последней попытке
- **WHEN** `max_attempts=3` и на третьей попытке обработчик бросает `RetryLaterError(retry_after=5)`
- **THEN** статус `DEAD_LETTERED`, `reason == DeadLetterReason.EXHAUSTED`

#### Scenario: RetryLaterError без политики
- **WHEN** политики нет и обработчик бросает `RetryLaterError(retry_after=5)`
- **THEN** статус `FAILED`

#### Scenario: Повтор ждёт своего времени
- **WHEN** задание в `RETRY_SCHEDULED` и часы ещё не дошли до `run_at`
- **THEN** `run_once()` возвращает `None`; после наступления `run_at` задание запускается, а `attempts` увеличивается

#### Scenario: Успех после повтора
- **WHEN** повторный запуск завершается успешно
- **THEN** статус `SUCCEEDED`, `error` равен `None`

#### Scenario: Использование rng
- **WHEN** `jitter > 0` и планируется повтор после ошибки, не являющейся `RetryLaterError`
- **THEN** выполняется ровно один `rng.uniform`; при `FAILED`, `DEAD_LETTERED`, `RetryLaterError` или `jitter == 0` — ни одного
