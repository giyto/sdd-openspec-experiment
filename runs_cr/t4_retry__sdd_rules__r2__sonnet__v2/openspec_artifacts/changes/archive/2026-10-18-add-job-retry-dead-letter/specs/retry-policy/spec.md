## Purpose

Описывает политику повторов `RetryPolicy`: допустимые параметры, расчёт задержки перед следующей попыткой и классификацию ошибок на повторяемые и неповторяемые.

## ADDED Requirements

### Requirement: Параметры RetryPolicy и значения по умолчанию
Модуль `jobq/retry.py` SHALL предоставлять неизменяемый dataclass `RetryPolicy` с полями `max_attempts: int = 3` (всего попыток, включая первую), `base_delay: float = 1.0`, `factor: float = 2.0`, `max_delay: float = 60.0`, `jitter: float = 0.0` и `non_retryable: tuple[type[BaseException], ...] = ()`. Задержки задаются в секундах. Если в `non_retryable` передан список (или другая последовательность), политика MUST хранить его как `tuple`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список non_retryable хранится кортежем
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `policy.non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Политика неизменяема
- **WHEN** код присваивает полю созданной политики новое значение
- **THEN** присваивание отклоняется как для frozen dataclass

### Requirement: Валидация параметров политики
Некорректные параметры SHALL приводить к `ConfigError` (наследнику `JobqError`) при создании `RetryPolicy`. Некорректны: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне отрезка `[0, 1]`, а также элемент `non_retryable`, который не является классом исключения (классом-наследником `BaseException`). Встроенные `ValueError`/`TypeError` из публичного API выпускаться MUST NOT.

#### Scenario: Недопустимое число попыток
- **WHEN** создаётся `RetryPolicy(max_attempts=0)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Отрицательная базовая задержка
- **WHEN** создаётся `RetryPolicy(base_delay=-0.1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Множитель меньше единицы
- **WHEN** создаётся `RetryPolicy(factor=0.5)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Потолок меньше базовой задержки
- **WHEN** создаётся `RetryPolicy(base_delay=10.0, max_delay=5.0)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Джиттер вне диапазона
- **WHEN** создаётся `RetryPolicy(jitter=1.5)` или `RetryPolicy(jitter=-0.1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся `RetryPolicy(max_attempts=1, base_delay=0, factor=1, max_delay=0, jitter=1)`
- **THEN** политика создаётся без ошибки

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** создаётся `RetryPolicy(non_retryable=(ValueError("x"),))` или `RetryPolicy(non_retryable=(int,))`
- **THEN** выбрасывается `ConfigError`

### Requirement: Расчёт задержки delay_for
`RetryPolicy.delay_for(attempt, rng=None)` SHALL возвращать задержку в секундах перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка MUST умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, после чего результат снова ограничивается сверху значением `max_delay`. Результат MUST всегда лежать в `[0, max_delay]` для любого `attempt >= 1`, включая очень большие значения и `base_delay == 0`; переполнение float (`OverflowError`) наружу выходить MUST NOT. При `jitter == 0` генератор `rng` SHALL NOT использоваться; при `jitter > 0` генератор вызывается ровно один раз (один `uniform`) на одну задержку. Если `rng` не передан, а `jitter > 0`, используется генератор по умолчанию. Значение `attempt < 1` SHALL давать `ConfigError`.

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
- **WHEN** `jitter=0.5`, `rng.uniform(0.5, 1.5)` возвращает `1.2`, а ограниченная задержка равна `10.0` и `max_delay` не меньше `12.0`
- **THEN** `delay_for` возвращает `12.0`

#### Scenario: Джиттер не пробивает потолок
- **WHEN** `max_delay=60.0`, `jitter=0.5`, ограниченная задержка равна `60.0`, `rng.uniform(0.5, 1.5)` возвращает `1.4`
- **THEN** `delay_for` возвращает `60.0`

#### Scenario: Один вызов rng на задержку
- **WHEN** `delay_for` вызывается с `jitter > 0` и подсчитывающим генератором
- **THEN** `uniform` вызван ровно один раз с аргументами `(1 - jitter, 1 + jitter)`

#### Scenario: Без джиттера rng не трогается
- **WHEN** `delay_for` вызывается с `jitter == 0` и подсчитывающим генератором
- **THEN** генератор не вызывается ни разу

#### Scenario: Недопустимый номер попытки
- **WHEN** вызывается `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок is_retryable
`RetryPolicy.is_retryable(exc)` SHALL возвращать `False` для исключения, являющегося экземпляром любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError` и его наследников. Для остальных исключений MUST возвращаться `True`. Модуль `jobq/errors.py` SHALL содержать `PermanentJobError`, наследующий `JobqError`.

#### Scenario: Исключение из non_retryable
- **WHEN** `non_retryable=(ValueError,)` и проверяется `ValueError("x")`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Наследник исключения из non_retryable
- **WHEN** `non_retryable=(ValueError,)` и проверяется `UnicodeDecodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** у политики пустой `non_retryable` и проверяется `PermanentJobError("no")`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка повторяема
- **WHEN** `non_retryable=(ValueError,)` и проверяется `TimeoutError()`
- **THEN** `is_retryable` возвращает `True`
