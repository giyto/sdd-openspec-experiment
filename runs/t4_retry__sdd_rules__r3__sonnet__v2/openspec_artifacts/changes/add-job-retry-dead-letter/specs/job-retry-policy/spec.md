## Purpose

Описывает политику повторов упавших заданий: параметры и их валидацию, расчёт экспоненциальной задержки, классификацию ошибок, назначение политики и выбор исхода задания воркером.

## ADDED Requirements

### Requirement: Параметры и валидация RetryPolicy
Система SHALL предоставлять неизменяемый `RetryPolicy` в `jobq/retry.py` с полями `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`. Список в `non_retryable` SHALL приниматься и храниться как `tuple`. Некорректные параметры SHALL приводить к `ConfigError` при создании: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент `non_retryable`, не являющийся классом исключения (наследником `BaseException`). Нечисловые и нефинитные (NaN, бесконечность) числовые параметры SHALL также считаться некорректными.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список приводится к tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Некорректные числовые параметры
- **WHEN** создаётся `RetryPolicy` с `max_attempts=0`, или `base_delay=-1`, или `factor=0.5`, или `max_delay < base_delay`, или `jitter=1.5`, или `jitter=-0.1`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** создаётся `RetryPolicy(non_retryable=(ValueError("x"),))` или `RetryPolicy(non_retryable=(int,))`
- **THEN** выбрасывается `ConfigError`

### Requirement: Расчёт задержки delay_for
`delay_for(attempt, rng=None)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, затем результат SHALL быть ограничен `max_delay` (джиттер не пробивает потолок). Метод SHALL работать для любого `attempt >= 1` без исключений переполнения (в том числе при `attempt` порядка 5000 и более) и при `base_delay == 0` (результат `0`), а результат SHALL всегда лежать в `[0, max_delay]`. При `jitter == 0` `rng` SHALL NOT использоваться; при `jitter > 0` SHALL вызываться ровно один `rng.uniform` на одну задержку. Если `rng` не передан при `jitter > 0`, SHALL использоваться собственный генератор случайных чисел. При `attempt < 1` SHALL выбрасываться `ConfigError`.

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

#### Scenario: Джиттер применяется к ограниченной задержке
- **WHEN** `jitter=0.5`, `max_delay=60`, вызывается `delay_for(10, rng)` и `rng.uniform(0.5, 1.5)` возвращает `1.5`
- **THEN** результат равен `60.0`, а не `90.0`

#### Scenario: Джиттер уменьшает задержку
- **WHEN** `base_delay=10`, `jitter=0.2`, вызывается `delay_for(1, rng)` и `rng.uniform(0.8, 1.2)` возвращает `0.9`
- **THEN** возвращается `9.0`

#### Scenario: Без джиттера генератор не трогается
- **WHEN** `jitter == 0` и вызывается `delay_for(3, rng)`
- **THEN** у `rng` не происходит ни одного вызова

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок is_retryable
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError` (и её наследников), независимо от `non_retryable`. Для остальных исключений SHALL возвращаться `True`. `PermanentJobError` SHALL быть наследником `JobqError` и определена в `jobq/errors.py`.

#### Scenario: Наследник неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и проверяется `UnicodeDecodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Прочие ошибки повторяемы
- **WHEN** `non_retryable=(ValueError,)` и проверяется `TimeoutError`
- **THEN** `is_retryable` возвращает `True`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** `non_retryable=()` и проверяется `PermanentJobError("no")`
- **THEN** `is_retryable` возвращает `False`

### Requirement: Назначение политики очереди и типу задания
`JobQueue` SHALL принимать keyword-only параметр `default_retry_policy: RetryPolicy | None = None`. `set_retry_policy(job_type, policy)` SHALL задавать политику для типа задания, а `policy=None` — снимать её. `retry_policy_for(job_type)` SHALL возвращать действующую политику: политику типа, если она задана, иначе политику очереди по умолчанию, иначе `None`. Политика типа SHALL полностью заменять политику по умолчанию, поля не сливаются. Действующей считается политика на момент ошибки, а не на момент постановки задания. Значение, не являющееся `RetryPolicy` или `None`, SHALL приводить к `ConfigError`.

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** дефолт `RetryPolicy(non_retryable=(ValueError,))`, для типа `a` задана `RetryPolicy(max_attempts=5)`
- **THEN** `retry_policy_for("a")` возвращает политику типа с пустым `non_retryable`, а `retry_policy_for("b")` — дефолт

#### Scenario: Снятие политики типа
- **WHEN** для типа задана политика, затем вызывается `set_retry_policy(type, None)`
- **THEN** `retry_policy_for(type)` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Политика берётся на момент ошибки
- **WHEN** задание поставлено при одной политике, затем политика типа изменена, затем обработчик падает
- **THEN** применяется политика, действующая в момент падения

#### Scenario: Некорректный тип политики
- **WHEN** вызывается `set_retry_policy("a", "oops")`
- **THEN** выбрасывается `ConfigError`

### Requirement: Исход упавшего задания в воркере
`Worker` SHALL принимать keyword-only `rng: random.Random | None = None` и при исключении обработчика выбирать исход по действующей политике типа задания:
1. политики нет — `FAILED` без повторов, как сейчас;
2. ошибка неповторяемая (`is_retryable` is `False`) — `FAILED`, даже на последней попытке, в dead-letter не попадает;
3. иначе, если `job.attempts >= max_attempts` — `DEAD_LETTERED` и запись в `dead_letters()` (`max_attempts=1` означает «без повторов, но в dead-letter»);
4. иначе — `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`.

Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. `rng` SHALL использоваться только при реальном планировании повтора (исход 4) и только при `jitter > 0`; для исходов `FAILED` и `DEAD_LETTERED` задержка не вычисляется. Если для типа нет обработчика, задание SHALL сразу получать `FAILED` независимо от политики. Задание в `RETRY_SCHEDULED` воркер SHALL брать, когда наступил его `run_at`, как любое другое готовое задание.

#### Scenario: Нет политики
- **WHEN** ни политики типа, ни дефолта нет и обработчик падает
- **THEN** задание получает `FAILED`, `jobs.failed` увеличивается на 1

#### Scenario: Первая ошибка при max_attempts=3
- **WHEN** действует `RetryPolicy(max_attempts=3, base_delay=2, jitter=0)` и обработчик падает на первой попытке в момент `T`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 2 с`, `error` содержит последнюю ошибку

#### Scenario: Попытки исчерпаны
- **WHEN** `max_attempts=3` и обработчик падает третий раз
- **THEN** статус `DEAD_LETTERED`, запись появляется в `dead_letters()`

#### Scenario: max_attempts=1
- **WHEN** `max_attempts=1` и обработчик падает с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик на последней попытке бросает `PermanentJobError` или ошибку из `non_retryable`
- **THEN** статус `FAILED`, в dead-letter записи нет

#### Scenario: Нет обработчика
- **WHEN** для типа есть политика, но обработчик не зарегистрирован
- **THEN** задание сразу получает `FAILED`, повтор не планируется

#### Scenario: Повтор ждёт своего времени
- **WHEN** задание в `RETRY_SCHEDULED` и часы ещё не дошли до `run_at`
- **THEN** `run_once()` возвращает `None`; после наступления `run_at` задание запускается, а `attempts` увеличивается

#### Scenario: Успех после повтора
- **WHEN** повторный запуск завершается успешно
- **THEN** статус `SUCCEEDED`, `error` равен `None`

#### Scenario: Использование rng
- **WHEN** `jitter > 0` и планируется повтор
- **THEN** выполняется ровно один `rng.uniform`; при `FAILED`, `DEAD_LETTERED` или `jitter == 0` — ни одного
