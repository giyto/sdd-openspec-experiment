## Purpose

Описывает политику повторов `RetryPolicy`: допустимые параметры, расчёт задержки перед следующей попыткой и определение, можно ли повторять задание после данной ошибки.

## ADDED Requirements

### Requirement: Параметры политики повторов
`jobq/retry.py` SHALL предоставлять `RetryPolicy` — неизменяемый dataclass с полями `max_attempts: int = 3` (всего попыток, включая первую), `base_delay: float = 1.0` (секунды), `factor: float = 2.0`, `max_delay: float = 60.0` (секунды), `jitter: float = 0.0` и `non_retryable: tuple[type[BaseException], ...] = ()`. В `non_retryable` MUST приниматься любой список/кортеж классов, а храниться — `tuple`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список приводится к tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `policy.non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Политика неизменяема
- **WHEN** выполняется присваивание `policy.max_attempts = 5`
- **THEN** возникает ошибка изменения frozen dataclass

### Requirement: Валидация параметров
Создание `RetryPolicy` с некорректными параметрами SHALL завершаться `ConfigError`. Некорректны: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]` и элемент `non_retryable`, не являющийся классом исключения (подкласс `BaseException`). Граничные значения (`max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay == base_delay`, `jitter` 0 и 1) MUST быть допустимы.

#### Scenario: Недопустимое число попыток
- **WHEN** создаётся `RetryPolicy(max_attempts=0)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Недопустимые задержки и множитель
- **WHEN** создаётся `RetryPolicy(base_delay=-1)`, `RetryPolicy(factor=0.5)` или `RetryPolicy(base_delay=10, max_delay=5)`
- **THEN** в каждом случае выбрасывается `ConfigError`

#### Scenario: Jitter вне диапазона
- **WHEN** создаётся `RetryPolicy(jitter=1.5)` или `RetryPolicy(jitter=-0.1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError("x")])`, `RetryPolicy(non_retryable=[int])` или `RetryPolicy(non_retryable=["ValueError"])`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся `RetryPolicy(max_attempts=1, base_delay=0, factor=1, max_delay=0, jitter=1)`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки
`delay_for(attempt, rng=None)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1) как `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка MUST умножаться на `rng.uniform(1 - jitter, 1 + jitter)` — ровно один вызов `uniform` на одну задержку, — а результат MUST быть снова ограничен `max_delay`: `max_delay` — жёсткий потолок, джиттер его не превышает (если с разбросом получается больше, возвращается ровно `max_delay`); при `jitter == 0` `rng` MUST NOT использоваться. Если `rng` не передан, а `jitter > 0`, используется источник случайности по умолчанию. `attempt < 1` — `ConfigError`. Метод MUST работать для любого `attempt` (включая очень большие, например 5000 и более) без `OverflowError`, в том числе при `base_delay == 0` (результат `0.0`) и `factor == 1`.

#### Scenario: Экспоненциальный рост
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=60)` вычисляет `delay_for` для попыток 1, 2, 3
- **THEN** результаты равны `1.0`, `2.0`, `4.0`

#### Scenario: Ограничение max_delay
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=60).delay_for(10)`
- **THEN** результат равен `60.0`

#### Scenario: Огромный номер попытки
- **WHEN** `RetryPolicy(max_attempts=10000).delay_for(5000)` и `delay_for(10000)`
- **THEN** возвращается `60.0` без `OverflowError`

#### Scenario: Нулевая базовая задержка
- **WHEN** `RetryPolicy(base_delay=0).delay_for(5000)`
- **THEN** результат равен `0.0` без `OverflowError` и без `nan`

#### Scenario: Jitter не превышает max_delay
- **WHEN** `RetryPolicy(base_delay=1, max_delay=60, jitter=0.5).delay_for(10, rng)` и `rng.uniform(0.5, 1.5)` вернул `1.25`
- **THEN** результат равен `60.0` (не `75.0`), а `uniform` вызван ровно один раз с аргументами `(0.5, 1.5)`

#### Scenario: Без jitter rng не трогается
- **WHEN** `delay_for(1, rng)` вызывается для политики с `jitter == 0`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Недопустимый номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Определение повторяемости ошибки
`is_retryable(exc)` SHALL возвращать `False` для экземпляров любого класса из `non_retryable` (с учётом наследования, как обычный `except`) и всегда для `PermanentJobError` (и её наследников), независимо от `non_retryable`; для остальных исключений — `True`.

#### Scenario: Ошибка из non_retryable
- **WHEN** `RetryPolicy(non_retryable=(ValueError,)).is_retryable(ValueError())`
- **THEN** результат `False`

#### Scenario: Наследник класса из non_retryable
- **WHEN** `is_retryable(UnicodeDecodeError(...))` при `non_retryable=(ValueError,)`
- **THEN** результат `False`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** `RetryPolicy().is_retryable(PermanentJobError("no"))`
- **THEN** результат `False`

#### Scenario: Обычная ошибка повторяема
- **WHEN** `RetryPolicy(non_retryable=(ValueError,)).is_retryable(TimeoutError())`
- **THEN** результат `True`

### Requirement: PermanentJobError
`jobq/errors.py` SHALL определять `PermanentJobError`, наследующую `JobqError`. Обработчик бросает её, когда точно знает, что повтор не поможет.

#### Scenario: Иерархия
- **WHEN** проверяется `issubclass(PermanentJobError, JobqError)`
- **THEN** результат `True`
