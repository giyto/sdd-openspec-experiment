## Purpose

Описывает политику повторов: параметры, их проверку, расчёт задержки между попытками, определение повторяемых ошибок и назначение политики очереди и типам заданий.

## ADDED Requirements

### Requirement: Параметры политики и их проверка
Политика повторов SHALL быть неизменяемой и иметь параметры `max_attempts=3` (всего попыток, включая первую), `base_delay=1.0`, `factor=2.0`, `max_delay=60.0` (секунды), `jitter=0.0` и `non_retryable=()`. Параметр `non_retryable` SHALL принимать любую последовательность классов (например, список) и храниться как tuple. Создание политики с `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]` или элементом `non_retryable`, который не является классом-наследником `BaseException`, MUST завершаться `ConfigError`. Значения NaN MUST считаться некорректными.

#### Scenario: Значения по умолчанию
- **WHEN** создана политика без аргументов
- **THEN** `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`

#### Scenario: Список превращается в tuple
- **WHEN** в `non_retryable` передан список `[ValueError]`
- **THEN** у политики `non_retryable == (ValueError,)`

#### Scenario: Некорректный параметр
- **WHEN** создаётся политика с `max_attempts=0`, или `base_delay=-1`, или `factor=0.5`, или `max_delay` меньше `base_delay`, или `jitter=1.5`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** в `non_retryable` передана строка, экземпляр исключения или класс, не являющийся исключением
- **THEN** выбрасывается `ConfigError`

#### Scenario: max_attempts=1 допустим
- **WHEN** создаётся политика с `max_attempts=1`
- **THEN** ошибки нет; повторов не будет

### Requirement: Расчёт задержки перед повтором
`delay_for(attempt)` SHALL возвращать задержку в секундах перед следующей попыткой, если упала попытка номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на ровно одно значение `rng.uniform(1 - jitter, 1 + jitter)`, но `max_delay` — жёсткий потолок: если результат с разбросом превышает `max_delay`, возвращается ровно `max_delay`; при `jitter == 0` генератор MUST NOT вызываться. Расчёт MUST работать для любого `attempt >= 1` (включая очень большие, например 5000 и 10000) и любых допустимых параметров, включая `base_delay=0`, без `OverflowError`. Для `attempt < 1` SHALL выбрасываться `ConfigError`. Если `rng` не передан, а `jitter > 0`, SHALL использоваться генератор по умолчанию.

#### Scenario: Экспоненциальный рост
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`, `jitter=0`
- **THEN** `delay_for(1)=1`, `delay_for(2)=2`, `delay_for(3)=4`

#### Scenario: Ограничение max_delay
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`
- **THEN** `delay_for(10)=60`

#### Scenario: Огромный номер попытки
- **WHEN** вызывается `delay_for(5000)` или `delay_for(10000)` при `factor=2`
- **THEN** результат равен `max_delay`, исключения нет

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(10000)`
- **THEN** результат `0.0`, исключения нет

#### Scenario: factor=1
- **WHEN** `factor=1`
- **THEN** при любом `attempt` задержка равна `base_delay`

#### Scenario: Jitter не превышает max_delay
- **WHEN** `jitter=0.5`, задержка до jitter ограничена `max_delay=60`, а `rng.uniform` вернул 1.25
- **THEN** результат 60.0 (не 75.0), и `uniform` вызван ровно один раз с аргументами `(0.5, 1.5)`

#### Scenario: Без jitter генератор не трогаем
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Номер попытки меньше 1
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация повторяемых ошибок
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError` и его наследников, независимо от `non_retryable`. Для остальных исключений SHALL возвращаться `True`. `PermanentJobError` SHALL наследоваться от `JobqError`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и проверяется `UnicodeDecodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError
- **WHEN** `non_retryable=()` и проверяется `PermanentJobError("x")`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка
- **WHEN** проверяется `TimeoutError` при `non_retryable=(ValueError,)`
- **THEN** `is_retryable` возвращает `True`

### Requirement: Назначение политики очереди и типам заданий
Очередь SHALL принимать политику по умолчанию (`default_retry_policy`, keyword-only) и политики по типу задания через `set_retry_policy(job_type, policy)`; `set_retry_policy(job_type, None)` SHALL снимать политику типа. `retry_policy_for(job_type)` SHALL возвращать политику типа, а если её нет — политику по умолчанию, а если нет и её — `None`. Политика типа MUST заменять политику по умолчанию целиком, без слияния по полям. Политика MUST определяться на момент ошибки, а не на момент постановки задания. Значение, не являющееся `RetryPolicy` или `None`, и пустой `job_type` MUST приводить к `ConfigError`.

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** у очереди дефолт с `non_retryable=(ValueError,)`, а для типа задана политика без `non_retryable`
- **THEN** `retry_policy_for(тип)` возвращает политику типа, и `ValueError` для этого типа повторяется

#### Scenario: Откат к дефолту
- **WHEN** для типа вызвано `set_retry_policy(тип, None)`
- **THEN** `retry_policy_for(тип)` возвращает дефолт очереди

#### Scenario: Политики нет совсем
- **WHEN** нет ни дефолта, ни политики типа
- **THEN** `retry_policy_for(тип)` возвращает `None`

#### Scenario: Политика меняется после постановки
- **WHEN** задание поставлено, затем политика типа изменена, затем обработчик упал
- **THEN** применяется политика, действующая в момент падения

#### Scenario: Некорректный аргумент
- **WHEN** в `set_retry_policy` передан не `RetryPolicy` и не `None`
- **THEN** выбрасывается `ConfigError`
