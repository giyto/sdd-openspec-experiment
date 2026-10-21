## Purpose

Описывает неизменяемую политику повторов: параметры, их проверку, расчёт задержки между попытками и определение ошибок, после которых повторять нельзя.

## ADDED Requirements

### Requirement: Параметры политики и значения по умолчанию
Политика SHALL создаваться с именованными параметрами `max_attempts=3` (общее число попыток, включая первую), `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`. Созданная политика SHALL быть неизменяемой, а `non_retryable` SHALL храниться как `tuple`, даже если передан список.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся политика без аргументов
- **THEN** параметры равны `3`, `1.0`, `2.0`, `60.0`, `0.0`, `()`

#### Scenario: Список превращается в tuple
- **WHEN** в `non_retryable` передан список классов исключений
- **THEN** в политике значение является `tuple` с теми же классами

#### Scenario: Политику нельзя изменить
- **WHEN** код присваивает полю созданной политики новое значение
- **THEN** присваивание отклоняется

### Requirement: Валидация параметров
Создание политики SHALL завершаться `ConfigError`, если: `max_attempts < 1`; `base_delay < 0`; `factor < 1`; `max_delay < base_delay`; `jitter` вне `[0, 1]`; в `non_retryable` есть что-то, что не является классом исключения. Нечисловые и нефинитные (NaN, inf) значения числовых параметров, нецелый `max_attempts` и не-итерируемое значение `non_retryable` SHALL также приводить к `ConfigError`.

#### Scenario: Недопустимые значения
- **WHEN** передано `max_attempts=0`, `base_delay=-1`, `factor=0.5`, `max_delay` меньше `base_delay` или `jitter=1.5`
- **THEN** создание политики завершается `ConfigError`

#### Scenario: Граничные допустимые значения
- **WHEN** передано `max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay` равный `base_delay`, `jitter=0` или `jitter=1`
- **THEN** политика создаётся

#### Scenario: Не класс исключения
- **WHEN** в `non_retryable` передан экземпляр исключения, строка или класс, не являющийся исключением
- **THEN** создание политики завершается `ConfigError`

### Requirement: Задержка перед повтором
`delay_for(attempt, rng=None)` SHALL возвращать задержку в секундах перед следующей попыткой, если попытка номер `attempt` (с 1) упала. Базовое значение SHALL быть `base_delay * factor ** (attempt - 1)`, ограниченное сверху `max_delay`. При `attempt < 1` SHALL выбрасываться `ConfigError`.

#### Scenario: Экспоненциальный рост
- **WHEN** политика с `base_delay=1`, `factor=2`, `max_delay=60` и `attempt` равен 1, 2, 3
- **THEN** задержки равны 1, 2, 4

#### Scenario: Ограничение сверху
- **WHEN** расчётная задержка превышает `max_delay`
- **THEN** возвращается `max_delay`

#### Scenario: Некорректный номер попытки
- **WHEN** `delay_for` вызван с `attempt=0`
- **THEN** выбрасывается `ConfigError`

### Requirement: Устойчивость к большим номерам попыток
`delay_for` SHALL работать для любого `attempt >= 1`, включая очень большие (например, 5000 и больше), без `OverflowError` и без нечисловых результатов; для таких попыток результат равен `max_delay` (при `base_delay=0` — `0`).

#### Scenario: Попытка 5000
- **WHEN** политика с `max_attempts=10_000` и `factor=2.0` и `attempt=5000`
- **THEN** возвращается `max_delay`, исключений нет

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и очень большой `attempt`
- **THEN** возвращается `0.0`

### Requirement: Джиттер
Если `jitter > 0`, ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, ровно один вызов `uniform` на одну задержку; итог SHALL быть не больше `max_delay`. Если `jitter == 0`, генератор SHALL не использоваться вообще. Если `jitter > 0`, а `rng` не передан, SHALL использоваться собственный генератор.

#### Scenario: Один вызов uniform
- **WHEN** `jitter=0.2` и передан генератор
- **THEN** `uniform(0.8, 1.2)` вызывается ровно один раз, результат — база, умноженная на его значение

#### Scenario: Джиттер не превышает потолок
- **WHEN** база уже равна `max_delay`, а `uniform` возвращает значение больше 1
- **THEN** итог равен `max_delay`

#### Scenario: Без джиттера генератор не трогается
- **WHEN** `jitter=0` и передан генератор
- **THEN** ни один его метод не вызывается

### Requirement: Классификация повторяемости ошибок
`is_retryable(exc)` SHALL возвращать `False`, если `exc` — экземпляр одного из `non_retryable` (включая подклассы) или `PermanentJobError`, и `True` в остальных случаях. `PermanentJobError` (наследник `JobqError`) SHALL быть неповторяемой при любой политике, даже если её нет в `non_retryable`.

#### Scenario: Подкласс неповторяемого типа
- **WHEN** `non_retryable=(ValueError,)` и проверяется `UnicodeError`
- **THEN** результат `False`

#### Scenario: PermanentJobError всегда неповторяема
- **WHEN** политика с пустым `non_retryable` и проверяется `PermanentJobError`
- **THEN** результат `False`

#### Scenario: Прочие ошибки повторяемы
- **WHEN** проверяется `TimeoutError` при пустом `non_retryable`
- **THEN** результат `True`
