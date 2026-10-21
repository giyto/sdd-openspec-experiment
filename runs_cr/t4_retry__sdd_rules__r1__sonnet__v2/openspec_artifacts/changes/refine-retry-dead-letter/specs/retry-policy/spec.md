## MODIFIED Requirements

### Requirement: Расчёт задержки
`delay_for(attempt, rng=None)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1)`: джиттер только уменьшает задержку и никогда не увеличивает её. Результат SHALL всегда лежать в `[0, max_delay]`. Метод SHALL работать для любого `attempt >= 1`, включая очень большие значения, без `OverflowError`, и при `base_delay == 0` (результат `0`). При `jitter == 0` `rng` SHALL NOT использоваться; при `jitter > 0` SHALL делаться ровно один вызов `rng.uniform` на одну задержку. Если `rng` не передан, SHALL использоваться независимый источник случайности. `attempt < 1` SHALL давать `ConfigError`.

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
- **WHEN** `jitter=0.5`, ограниченная задержка равна 10.0, а `rng.uniform` возвращает максимум диапазона, `1`
- **THEN** результат равен 10.0, то есть не больше расчётной задержки

#### Scenario: Джиттер применяется к ограниченной задержке
- **WHEN** `jitter=0.2`, ограниченная задержка равна 4.0 и `rng.uniform(0.8, 1)` возвращает 0.9
- **THEN** результат равен 3.6, `uniform` вызван ровно один раз с аргументами `(0.8, 1)`

#### Scenario: Полный джиттер
- **WHEN** `jitter=1` и `rng.uniform(0, 1)` возвращает 0
- **THEN** результат равен `0.0`

#### Scenario: Без джиттера rng не трогаем
- **WHEN** `jitter=0` и передан `rng`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Неверный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

## ADDED Requirements

### Requirement: RetryLaterError
`jobq/errors.py` SHALL объявлять `RetryLaterError(JobqError)` с `__init__(self, message: str = "", *, retry_after: float) -> None` и атрибутом `retry_after: float` (секунды); `retry_after` SHALL быть только keyword-only и обязательным. Обработчик бросает её, когда внешний сервис сам назвал время повтора. `retry_after < 0`, `NaN`, `bool` и нечисловое значение SHALL давать `ConfigError` при создании исключения; `0` и `inf` допустимы. `RetryPolicy.is_retryable` SHALL классифицировать её по обычным правилам, без особого случая. `RetryLaterError` и `DeadLetterReason` SHALL экспортироваться из `jobq`.

#### Scenario: Создание
- **WHEN** создаётся `RetryLaterError("busy", retry_after=30)`
- **THEN** `retry_after == 30`, `str(exc) == "busy"`, исключение является `JobqError`

#### Scenario: Сообщение по умолчанию
- **WHEN** создаётся `RetryLaterError(retry_after=5)`
- **THEN** ошибки нет, `str(exc) == ""`

#### Scenario: Отрицательное значение
- **WHEN** создаётся `RetryLaterError(retry_after=-1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: retry_after только по имени
- **WHEN** `retry_after` передаётся позиционно или не передаётся
- **THEN** выбрасывается `TypeError`

#### Scenario: Обычная классификация
- **WHEN** `non_retryable=()` и брошена `RetryLaterError`
- **THEN** `is_retryable` возвращает `True`
