# retry-policy Specification

## Purpose
Описывает политику повторов `RetryPolicy`: как считается задержка перед повтором, какие ошибки повторяются и какие параметры допустимы.

## Requirements

### Requirement: Параметры политики и значения по умолчанию
Политика SHALL иметь параметры `max_attempts=3` (всего попыток, включая первую), `base_delay=1.0`, `factor=2.0`, `max_delay=60.0` (секунды), `jitter=0.0` и `non_retryable=()`. Политика MUST быть неизменяемой. `non_retryable` MAY быть передан любой последовательностью классов исключений, хранится как `tuple`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()` без аргументов
- **THEN** `max_attempts` равен 3, `base_delay` 1.0, `factor` 2.0, `max_delay` 60.0, `jitter` 0.0, `non_retryable` равен `()`

#### Scenario: Список приводится к tuple
- **WHEN** в `non_retryable` передан список `[ValueError, KeyError]`
- **THEN** политика хранит `(ValueError, KeyError)` как `tuple`

### Requirement: Валидация параметров
Некорректные параметры SHALL приводить к `ConfigError` при создании политики: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент `non_retryable`, не являющийся классом-наследником `BaseException`. Нечисловые и нефинитные значения (NaN, бесконечность, не-`int` или `bool` в `max_attempts`) MUST тоже отвергаться с `ConfigError`. Наружу не должны выходить `ValueError`/`TypeError`.

#### Scenario: Недопустимые числа
- **WHEN** создаётся политика с `max_attempts=0`, либо `base_delay=-1`, либо `factor=0.5`, либо `max_delay` меньше `base_delay`, либо `jitter=1.5`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся политика с `max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay` равным `base_delay`, `jitter=0` или `jitter=1`
- **THEN** политика создаётся без ошибок

#### Scenario: Не-исключение в non_retryable
- **WHEN** в `non_retryable` передан экземпляр исключения, строка или не-класс
- **THEN** выбрасывается `ConfigError`

### Requirement: Расчёт задержки перед повтором
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка MUST умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, после чего результат снова ограничивается `max_delay` (потолок жёсткий). Результат MUST лежать в `[0, max_delay]` для любого `attempt >= 1`, включая очень большие значения (например, `attempt=5000` при `factor=2.0`) и `base_delay=0`; `OverflowError` и NaN недопустимы. `attempt < 1` MUST приводить к `ConfigError`.

#### Scenario: Экспоненциальный рост
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`, `jitter=0`
- **THEN** `delay_for(1)`, `delay_for(2)`, `delay_for(3)` равны 1, 2, 4

#### Scenario: Потолок
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60` и вызван `delay_for(10)`
- **THEN** результат равен 60

#### Scenario: Огромный номер попытки
- **WHEN** `factor=2.0` и вызван `delay_for(5000)` или `delay_for(10**9)`
- **THEN** возвращается `max_delay`, исключение не выбрасывается

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызван `delay_for(5000)`
- **THEN** возвращается 0.0

#### Scenario: Джиттер не пробивает потолок
- **WHEN** `jitter=0.5`, задержка уже равна `max_delay`, а `rng.uniform` вернул значение больше 1
- **THEN** результат равен `max_delay`

#### Scenario: Джиттер использует переданный rng
- **WHEN** `jitter>0` и передан `random.Random` с зафиксированным seed
- **THEN** выполняется ровно один вызов `uniform(1 - jitter, 1 + jitter)` и результат воспроизводим

#### Scenario: Без джиттера rng не трогается
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Недопустимый номер попытки
- **WHEN** вызван `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок
`is_retryable(exc)` SHALL возвращать `False` для экземпляров классов из `non_retryable` (с учётом наследования, как обычный `except`) и всегда `False` для `PermanentJobError` и его наследников, даже если он не указан в `non_retryable`. Для остальных исключений SHALL возвращать `True`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и проверяется `UnicodeDecodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError
- **WHEN** `non_retryable` пуст и проверяется `PermanentJobError("x")`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка
- **WHEN** `non_retryable=(ValueError,)` и проверяется `TimeoutError()`
- **THEN** `is_retryable` возвращает `True`

### Requirement: PermanentJobError
Пакет SHALL предоставлять `PermanentJobError`, наследник `JobqError`, экспортируемый из `jobq`, для обработчиков, которые точно знают, что повтор не поможет.

#### Scenario: Иерархия
- **WHEN** проверяется `issubclass(PermanentJobError, JobqError)`
- **THEN** результат истинен
