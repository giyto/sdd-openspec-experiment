## Purpose

Описывает политику повторов `RetryPolicy`: расчёт задержки, классификацию ошибок на повторяемые и неповторяемые, валидацию параметров и назначение политик очереди и типам заданий.

## ADDED Requirements

### Requirement: Параметры и валидация политики
`RetryPolicy` SHALL быть неизменяемой и иметь параметры `max_attempts=3` (всего попыток, включая первую), `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`. Некорректные параметры SHALL приводить к `ConfigError` при создании политики: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, нечисловые или нефинитные (NaN, бесконечность) числовые значения, элемент `non_retryable`, не являющийся классом исключения. `non_retryable` SHALL принимать любую последовательность классов и храниться как `tuple`. Встроенные `ValueError`/`TypeError` наружу не выпускаются.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список превращается в tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `non_retryable == (ValueError, KeyError)`

#### Scenario: Некорректный параметр
- **WHEN** создаётся политика с `max_attempts=0`, `base_delay=-1`, `factor=0.5`, `max_delay` меньше `base_delay`, `jitter=1.5` или `non_retryable=[int]`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные допустимые значения
- **WHEN** создаётся политика с `max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay == base_delay`, `jitter=0` или `jitter=1`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой, если упала попытка номер `attempt` (с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. Функция SHALL работать для любого `attempt >= 1` (включая очень большие значения и `base_delay=0`) без `OverflowError`; при переполнении результат равен `max_delay` (при `base_delay=0` — `0`). `attempt < 1` SHALL приводить к `ConfigError`.

#### Scenario: Экспоненциальный рост с ограничением
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`
- **THEN** `delay_for(1) == 1`, `delay_for(4) == 8`, `delay_for(7) == 60`

#### Scenario: Огромный номер попытки
- **WHEN** `max_attempts=10000`, `base_delay=1`, `factor=2`, `max_delay=60` и вызывается `delay_for(5000)`
- **THEN** результат `60`, исключения нет

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(5000)`
- **THEN** результат `0`

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Джиттер
При `jitter > 0` `delay_for` SHALL умножать уже ограниченную `max_delay` задержку на `rng.uniform(1 - jitter, 1 + jitter)`, делая ровно один вызов `uniform` на одну задержку, и затем снова ограничивать результат значением `max_delay`. `max_delay` — жёсткий потолок: если с разбросом получается больше максимума, результат равен ровно `max_delay`. При `jitter == 0` генератор SHALL NOT использоваться. Если `rng` не передан, SHALL использоваться собственный источник случайности.

#### Scenario: Один uniform на задержку
- **WHEN** `jitter=0.5` и `delay_for(2, rng)` вызывается с предсказуемым `rng`
- **THEN** результат равен ограниченной задержке, умноженной на единственное значение `rng.uniform(0.5, 1.5)`

#### Scenario: Нулевой джиттер не трогает rng
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Джиттер не превышает max_delay
- **WHEN** задержка уже упёрлась в `max_delay` и `jitter=0.2`
- **THEN** результат лежит в `[0.8 * max_delay, max_delay]`, а при `rng.uniform`, вернувшем `1.2`, равен ровно `max_delay`

### Requirement: Классификация ошибок
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами (с учётом наследования, как обычный `except`) любого класса из `non_retryable`, и всегда `False` для `PermanentJobError` и его наследников; иначе `True`. `PermanentJobError` SHALL наследоваться от `JobqError`.

#### Scenario: Наследники неповторяемых классов
- **WHEN** `non_retryable=(ValueError,)` и ошибка — `UnicodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError всегда неповторяем
- **WHEN** политика с пустым `non_retryable` и ошибка `PermanentJobError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка
- **WHEN** ошибка `TimeoutError`, не входящая в `non_retryable`
- **THEN** `is_retryable` возвращает `True`

### Requirement: Назначение политик
`JobQueue` SHALL принимать keyword-only `default_retry_policy`; `set_retry_policy(job_type, policy)` SHALL задавать политику типа, `None` снимает её; `retry_policy_for(job_type)` SHALL возвращать политику типа, иначе политику по умолчанию, иначе `None`. Политика типа SHALL заменять политику по умолчанию целиком, без слияния полей. Значение, не являющееся `RetryPolicy` или `None`, и пустой `job_type` SHALL приводить к `ConfigError`. Старые вызовы `JobQueue(...)` без нового параметра SHALL работать как раньше.

#### Scenario: Приоритет политики типа
- **WHEN** задан дефолт с `non_retryable=(ValueError,)` и политика типа `email` без `non_retryable`
- **THEN** `retry_policy_for("email")` возвращает политику типа, а `retry_policy_for("other")` — дефолт

#### Scenario: Снятие политики типа
- **WHEN** вызывается `set_retry_policy("email", None)`
- **THEN** `retry_policy_for("email")` возвращает дефолт очереди или `None`, если дефолта нет

#### Scenario: Нет политик
- **WHEN** ни дефолта, ни политики типа нет
- **THEN** `retry_policy_for(...)` возвращает `None`
