## ADDED Requirements

### Requirement: RetryLaterError
Пакет SHALL предоставлять `RetryLaterError`, наследник `JobqError`, экспортируемый из `jobq`. Конструктор принимает необязательное сообщение и обязательный keyword-only `retry_after` (секунды); значение доступно как атрибут `retry_after`. Обработчик бросает её, когда внешний сервис сам назвал время следующей попытки. `retry_after < 0`, а также нечисловое значение, `bool`, NaN или бесконечность MUST приводить к `ConfigError` при создании исключения. `retry_after = 0` допустим. Вызов без `retry_after` — обычная ошибка вызова Python (`TypeError`).

#### Scenario: Иерархия и атрибут
- **WHEN** создаётся `RetryLaterError("billing", retry_after=30)`
- **THEN** `issubclass(RetryLaterError, JobqError)` истинно, `retry_after == 30`, текст исключения равен `"billing"`

#### Scenario: Сообщение по умолчанию
- **WHEN** создаётся `RetryLaterError(retry_after=5)`
- **THEN** сообщение пустое, исключение создаётся без ошибок

#### Scenario: Отрицательное значение
- **WHEN** создаётся `RetryLaterError("x", retry_after=-1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Недопустимые значения
- **WHEN** `retry_after` равен NaN, бесконечности, `True` или строке
- **THEN** выбрасывается `ConfigError`

#### Scenario: Ноль допустим
- **WHEN** создаётся `RetryLaterError("x", retry_after=0)`
- **THEN** исключение создаётся без ошибок

## MODIFIED Requirements

### Requirement: Расчёт задержки перед повтором
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка MUST умножаться на `rng.uniform(1 - jitter, 1)`, то есть джиттер только уменьшает задержку и никогда не увеличивает её; результат после этого всё равно ограничивается диапазоном `[0, max_delay]` (потолок жёсткий, в том числе если `rng` вернул значение больше 1). Результат MUST лежать в `[0, max_delay]` для любого `attempt >= 1`, включая очень большие значения (например, `attempt=5000` при `factor=2.0`) и `base_delay=0`; `OverflowError` и NaN недопустимы. `attempt < 1` MUST приводить к `ConfigError`.

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

#### Scenario: Джиттер только уменьшает задержку
- **WHEN** `jitter=0.5`, расчётная задержка 8, а `rng.uniform` вызван и вернул 0.75
- **THEN** `uniform` вызван с аргументами `(0.5, 1)`, результат равен 6, и он никогда не больше расчётной задержки

#### Scenario: Джиттер не пробивает потолок
- **WHEN** `jitter=0.5`, задержка уже равна `max_delay`, а `rng.uniform` вернул значение больше 1
- **THEN** результат равен `max_delay`

#### Scenario: Джиттер использует переданный rng
- **WHEN** `jitter>0` и передан `random.Random` с зафиксированным seed
- **THEN** выполняется ровно один вызов `uniform(1 - jitter, 1)` и результат воспроизводим

#### Scenario: Без джиттера rng не трогается
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Недопустимый номер попытки
- **WHEN** вызван `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`
