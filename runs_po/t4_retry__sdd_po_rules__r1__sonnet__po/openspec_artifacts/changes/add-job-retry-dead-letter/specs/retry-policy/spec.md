## Purpose

Описывает политику повторов `RetryPolicy`: допустимые параметры, расчёт задержки перед следующей попыткой и классификацию ошибок на повторяемые и неповторяемые.

## ADDED Requirements

### Requirement: Параметры RetryPolicy и значения по умолчанию
`RetryPolicy` из `jobq/retry.py` SHALL быть неизменяемым dataclass с полями `max_attempts: int = 3` (всего попыток, включая первую), `base_delay: float = 1.0`, `factor: float = 2.0`, `max_delay: float = 60.0`, `jitter: float = 0.0`, `non_retryable: tuple[type[BaseException], ...] = ()`. Значение `non_retryable` SHALL приниматься в виде списка или кортежа и храниться как `tuple`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список превращается в tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `policy.non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Политика неизменяема
- **WHEN** код присваивает полю созданной политики новое значение
- **THEN** присваивание отклоняется

### Requirement: Валидация параметров как ошибка конфигурации
Создание `RetryPolicy` с некорректными параметрами SHALL выбрасывать `ConfigError`. Некорректны: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент `non_retryable`, который не является классом исключения (наследником `BaseException`). Граничные значения (`max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay == base_delay`, `jitter` равный 0 или 1) SHALL быть допустимы. Значение NaN в числовых параметрах SHALL считаться некорректным. Встроенные `ValueError`/`TypeError` наружу не выпускаются.

#### Scenario: Недопустимые числовые параметры
- **WHEN** создаётся политика с `max_attempts=0`, либо `base_delay=-1`, либо `factor=0.5`, либо `max_delay=0.5` при `base_delay=1.0`, либо `jitter=1.5`, либо `jitter=-0.1`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** создаётся политика с `non_retryable=(ValueError("x"),)` или `non_retryable=("ValueError",)` или `non_retryable=(int,)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся `RetryPolicy(max_attempts=1, base_delay=0, factor=1, max_delay=0, jitter=1)`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки delay_for
`delay_for(attempt, rng=None)` SHALL возвращать в секундах задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, а результат SHALL ограничиваться сверху `max_delay` повторно: `max_delay` — жёсткий потолок, и если с разбросом получается больше, возвращается ровно `max_delay`. При этом `uniform` вызывается ровно один раз на вызов; при `jitter == 0` `rng` SHALL не использоваться. При `attempt < 1` SHALL выбрасываться `ConfigError`. Метод SHALL работать для любого `attempt` (в том числе очень большого) и любых допустимых параметров, включая `base_delay == 0`, без `OverflowError`: слишком большое значение даёт `max_delay`, а при `base_delay == 0` результат равен 0.

#### Scenario: Экспоненциальный рост и ограничение
- **WHEN** политика `RetryPolicy(base_delay=1, factor=2, max_delay=10)`
- **THEN** `delay_for(1) == 1`, `delay_for(2) == 2`, `delay_for(3) == 4`, `delay_for(5) == 10`

#### Scenario: Очень большой номер попытки
- **WHEN** вызывается `delay_for(5000)` (или `delay_for(10**9)`) для политики с `factor=2.0` и `max_attempts=10000`
- **THEN** возвращается `max_delay` и `OverflowError` не возникает

#### Scenario: Нулевая базовая задержка
- **WHEN** политика с `base_delay=0` и вызывается `delay_for(5000)`
- **THEN** возвращается `0` (а не `NaN`) и ошибки нет

#### Scenario: Jitter не превышает max_delay
- **WHEN** политика с `max_delay=10`, `jitter=0.5`, ограниченная задержка равна 10, а `rng.uniform(0.5, 1.5)` вернул 1.2
- **THEN** `delay_for` возвращает 10 (не 12)

#### Scenario: Jitter уменьшает задержку
- **WHEN** политика с `max_delay=10`, `jitter=0.5`, ограниченная задержка равна 10, а `rng.uniform(0.5, 1.5)` вернул 0.8
- **THEN** `delay_for` возвращает 8

#### Scenario: Без jitter генератор не трогается
- **WHEN** `jitter == 0` и передан `rng`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Один uniform на задержку
- **WHEN** `jitter > 0` и `delay_for` вызван один раз
- **THEN** `rng.uniform` вызван ровно один раз с аргументами `(1 - jitter, 1 + jitter)`

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок is_retryable
`is_retryable(exc)` SHALL возвращать `False`, если `exc` является экземпляром одного из классов `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError` и её наследников независимо от `non_retryable`. Для остальных исключений SHALL возвращаться `True`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и проверяется исключение подкласса `ValueError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Остальные ошибки повторяемы
- **WHEN** `non_retryable=(ValueError,)` и проверяется `TimeoutError`
- **THEN** `is_retryable` возвращает `True`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** проверяется `PermanentJobError("no")` при пустом `non_retryable`
- **THEN** `is_retryable` возвращает `False`

### Requirement: Исключение PermanentJobError
Модуль `jobq/errors.py` SHALL содержать `PermanentJobError`, наследующий `JobqError`. Обработчик бросает его, когда точно знает, что повтор не поможет.

#### Scenario: Иерархия
- **WHEN** проверяется `issubclass(PermanentJobError, JobqError)`
- **THEN** результат `True`
