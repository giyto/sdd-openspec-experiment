## ADDED Requirements

### Requirement: RetryLaterError
Модуль `jobq/errors.py` SHALL содержать `RetryLaterError`, наследующий `JobqError`, с конструктором `RetryLaterError(message: str = "", *, retry_after: float)`, где `retry_after` — keyword-only обязательный параметр в секундах, и атрибутом `retry_after: float`. Значение `retry_after < 0` (а также нечисловое или NaN) MUST приводить к `ConfigError` при создании исключения. `retry_after == 0` допустим. `RetryLaterError` SHALL быть обычной повторяемой ошибкой: `RetryPolicy.is_retryable` возвращает для неё `True`, если класс не попал в `non_retryable`.

#### Scenario: Создание исключения
- **WHEN** создаётся `RetryLaterError("slow down", retry_after=30)`
- **THEN** `exc.retry_after == 30.0`, `str(exc) == "slow down"`, исключение является `JobqError`

#### Scenario: Отрицательный retry_after
- **WHEN** создаётся `RetryLaterError("x", retry_after=-1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Нулевой retry_after
- **WHEN** создаётся `RetryLaterError(retry_after=0)`
- **THEN** исключение создаётся без ошибки

#### Scenario: Классификация
- **WHEN** у политики пустой `non_retryable` и проверяется `RetryLaterError(retry_after=5)`
- **THEN** `is_retryable` возвращает `True`

## MODIFIED Requirements

### Requirement: Расчёт задержки delay_for
`RetryPolicy.delay_for(attempt, rng=None)` SHALL возвращать задержку в секундах перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка MUST умножаться на `rng.uniform(1 - jitter, 1)`, то есть джиттер только уменьшает задержку и результат никогда не превышает расчётную (ограниченную) задержку. Результат MUST всегда лежать в `[0, max_delay]` для любого `attempt >= 1`, включая очень большие значения и `base_delay == 0`; переполнение float (`OverflowError`) наружу выходить MUST NOT. При `jitter == 0` генератор `rng` SHALL NOT использоваться; при `jitter > 0` генератор вызывается ровно один раз (один `uniform`) на одну задержку. Если `rng` не передан, а `jitter > 0`, используется генератор по умолчанию. Значение `attempt < 1` SHALL давать `ConfigError`.

#### Scenario: Экспоненциальный рост без джиттера
- **WHEN** `RetryPolicy(base_delay=1.0, factor=2.0, max_delay=60.0).delay_for(n)` вызывается для `n = 1, 2, 3, 4`
- **THEN** возвращаются `1.0, 2.0, 4.0, 8.0`

#### Scenario: Ограничение потолком
- **WHEN** `RetryPolicy(base_delay=1.0, factor=2.0, max_delay=60.0).delay_for(10)`
- **THEN** возвращается `60.0`

#### Scenario: Огромный номер попытки
- **WHEN** `RetryPolicy(max_attempts=10000).delay_for(5000)` (где `2.0 ** 4999` не помещается в float)
- **THEN** возвращается `60.0` и исключение не выбрасывается

#### Scenario: Нулевая базовая задержка
- **WHEN** `RetryPolicy(base_delay=0.0).delay_for(5000)`
- **THEN** возвращается `0.0`

#### Scenario: Множитель 1
- **WHEN** `RetryPolicy(base_delay=3.0, factor=1.0).delay_for(1000)`
- **THEN** возвращается `3.0`

#### Scenario: Джиттер применяется к ограниченной задержке
- **WHEN** `jitter=0.5`, ограниченная задержка равна `10.0`, `rng.uniform(0.5, 1)` возвращает `0.8`
- **THEN** `delay_for` возвращает `8.0`

#### Scenario: Джиттер не пробивает потолок
- **WHEN** `jitter=0.5`, ограниченная задержка равна `60.0` (потолок), `rng.uniform(0.5, 1)` возвращает `1.0`
- **THEN** `delay_for` возвращает `60.0`, не больше

#### Scenario: Один вызов rng на задержку
- **WHEN** `delay_for` вызывается с `jitter > 0` и подсчитывающим генератором
- **THEN** `uniform` вызван ровно один раз с аргументами `(1 - jitter, 1)`

#### Scenario: Джиттер 1
- **WHEN** `jitter=1.0` и `rng.uniform(0.0, 1)` возвращает `0.0`
- **THEN** `delay_for` возвращает `0.0`

#### Scenario: Без джиттера rng не трогается
- **WHEN** `delay_for` вызывается с `jitter == 0` и подсчитывающим генератором
- **THEN** генератор не вызывается ни разу

#### Scenario: Недопустимый номер попытки
- **WHEN** вызывается `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`
