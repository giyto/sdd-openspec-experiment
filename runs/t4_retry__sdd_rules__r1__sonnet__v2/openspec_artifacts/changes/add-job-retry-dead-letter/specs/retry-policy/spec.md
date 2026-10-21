## Purpose

Описывает значение `RetryPolicy`: как проверяются параметры, как считается задержка перед повтором и какие ошибки считаются повторяемыми.

## ADDED Requirements

### Requirement: Параметры и значения по умолчанию
`RetryPolicy` в `jobq/retry.py` SHALL быть неизменяемым dataclass с полями `max_attempts: int = 3`, `base_delay: float = 1.0`, `factor: float = 2.0`, `max_delay: float = 60.0`, `jitter: float = 0.0`, `non_retryable: tuple[type[BaseException], ...] = ()`. Значение `non_retryable`, переданное списком, SHALL храниться как `tuple`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список превращается в tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Политика неизменяема
- **WHEN** присваивается значение полю созданной политики
- **THEN** возникает ошибка (frozen dataclass)

### Requirement: Валидация параметров
Создание `RetryPolicy` SHALL выбрасывать `ConfigError` при `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]` и при элементе `non_retryable`, который не является классом исключения (подкласс `BaseException`). Значения `NaN` в числовых полях SHALL отвергаться тем же `ConfigError`.

#### Scenario: Некорректные числа
- **WHEN** создаётся политика с `max_attempts=0`, либо `base_delay=-1`, либо `factor=0.5`, либо `max_delay` меньше `base_delay`, либо `jitter=1.5`, либо `jitter=-0.1`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Не класс исключения
- **WHEN** `non_retryable` содержит экземпляр исключения, строку или класс, не наследующий `BaseException`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся политика с `max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay` равным `base_delay`, `jitter=0` либо `jitter=1`
- **THEN** ошибки нет

### Requirement: Расчёт задержки
`delay_for(attempt, rng=None)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, после чего результат SHALL быть снова ограничен `max_delay`: `max_delay` — жёсткий потолок. Результат SHALL всегда лежать в `[0, max_delay]`. Метод SHALL работать для любого `attempt >= 1`, включая очень большие значения, без `OverflowError`, и при `base_delay == 0` (результат `0`). При `jitter == 0` `rng` SHALL NOT использоваться; при `jitter > 0` SHALL делаться ровно один вызов `rng.uniform` на одну задержку. Если `rng` не передан, SHALL использоваться независимый источник случайности. `attempt < 1` SHALL давать `ConfigError`.

#### Scenario: Экспоненциальный рост
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=60)` и `attempt` равен 1, 2, 3
- **THEN** `delay_for` возвращает 1.0, 2.0, 4.0

#### Scenario: Потолок
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=10)` и `attempt=10`
- **THEN** `delay_for` возвращает 10.0

#### Scenario: Огромный номер попытки
- **WHEN** `RetryPolicy(max_attempts=10000)` и `attempt=5000`
- **THEN** `delay_for` возвращает `max_delay` без исключения

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и любой `attempt`, в том числе огромный
- **THEN** `delay_for` возвращает `0.0`

#### Scenario: Джиттер не пробивает потолок
- **WHEN** `jitter=0.5`, задержка уже равна `max_delay`, а `rng.uniform` вернул значение больше 1
- **THEN** результат равен `max_delay`

#### Scenario: Джиттер применяется к ограниченной задержке
- **WHEN** `jitter=0.2`, ограниченная задержка равна 4.0 и `rng.uniform(0.8, 1.2)` возвращает 1.1
- **THEN** результат равен 4.4 (если не больше `max_delay`), `uniform` вызван ровно один раз с аргументами `(0.8, 1.2)`

#### Scenario: Без джиттера rng не трогаем
- **WHEN** `jitter=0` и передан `rng`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Неверный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок
`is_retryable(exc)` SHALL возвращать `False` для исключения, которое является экземпляром любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError` и её наследников. Для остальных исключений SHALL возвращать `True`. `PermanentJobError` SHALL быть объявлена в `jobq/errors.py` как подкласс `JobqError`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и обработчик бросил `UnicodeDecodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError всегда неповторяема
- **WHEN** `non_retryable=()` и брошена `PermanentJobError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка
- **WHEN** брошена `TimeoutError`, а `non_retryable=(ValueError,)`
- **THEN** `is_retryable` возвращает `True`
