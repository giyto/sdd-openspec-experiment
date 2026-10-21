## Purpose

Описывает настраиваемую политику повторов (`RetryPolicy`): параметры, их проверку, расчёт задержки между попытками, классификацию ошибок на повторяемые и неповторяемые, а также назначение политики очереди и типу задания.

## ADDED Requirements

### Requirement: Параметры RetryPolicy и их проверка
`RetryPolicy` в `jobq/retry.py` SHALL быть неизменяемым dataclass с полями `max_attempts: int = 3` (всего попыток, включая первую), `base_delay: float = 1.0`, `factor: float = 2.0`, `max_delay: float = 60.0` (секунды), `jitter: float = 0.0` и `non_retryable: tuple[type[BaseException], ...] = ()`. Значение `non_retryable` можно передать списком; оно SHALL храниться как `tuple`. Некорректные параметры SHALL приводить к `ConfigError` при создании политики: `max_attempts < 1` (или не `int`), `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, NaN или бесконечные значения вещественных полей, элемент `non_retryable`, не являющийся классом-наследником `BaseException`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список non_retryable хранится как tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `policy.non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Некорректные параметры отвергаются
- **WHEN** создаётся `RetryPolicy` с `max_attempts=0`, либо `base_delay=-1`, либо `factor=0.5`, либо `base_delay=5, max_delay=1`, либо `jitter=1.5` (или `-0.1`), либо `non_retryable=(int,)`, либо `non_retryable=("ValueError",)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся `RetryPolicy(max_attempts=1, base_delay=0, factor=1, max_delay=0, jitter=1)`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки delay_for
`RetryPolicy.delay_for(attempt: int, rng: random.Random | None = None) -> float` SHALL возвращать задержку перед следующей попыткой, если упала попытка номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)` — ровно один вызов `uniform` на одну задержку; результат SHALL NOT превышать `max_delay` (`max_delay` — жёсткий потолок: если с разбросом получилось больше, возвращается ровно `max_delay`); при `jitter == 0` генератор SHALL NOT использоваться. Если `rng` не передан, SHALL использоваться генератор по умолчанию. Метод SHALL работать для любого `attempt >= 1` (включая очень большие, например `5000` и больше, и `base_delay == 0`) без `OverflowError`; при `attempt < 1` SHALL выбрасываться `ConfigError`.

#### Scenario: Экспоненциальный рост с ограничением
- **WHEN** политика `RetryPolicy(base_delay=1, factor=2, max_delay=10)`
- **THEN** `delay_for(1) == 1`, `delay_for(2) == 2`, `delay_for(3) == 4`, `delay_for(5) == 10`

#### Scenario: Огромный номер попытки
- **WHEN** вызывается `RetryPolicy(max_attempts=10000, max_delay=60).delay_for(5000)`
- **THEN** результат равен `60.0` и `OverflowError` не возникает

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(5000)` (и `delay_for(1)`)
- **THEN** результат равен `0.0`

#### Scenario: factor равен 1
- **WHEN** `factor=1`, `base_delay=3`
- **THEN** `delay_for(n) == 3` для любого `n`

#### Scenario: Джиттер не превышает max_delay
- **WHEN** `jitter=0.5`, `base_delay=1`, `max_delay=10`, `attempt=10` и `rng.uniform(0.5, 1.5)` возвращает `1.2`
- **THEN** результат равен `10.0` (`10 * 1.2 = 12` ограничено до `max_delay`), а `uniform` вызван один раз с аргументами `(0.5, 1.5)`

#### Scenario: Джиттер уменьшает задержку
- **WHEN** те же параметры и `rng.uniform(0.5, 1.5)` возвращает `0.8`
- **THEN** результат равен `8.0`

#### Scenario: Без джиттера генератор не трогается
- **WHEN** `jitter=0` и передан `rng`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок is_retryable
`RetryPolicy.is_retryable(exc: BaseException) -> bool` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError`. Для остальных исключений SHALL возвращаться `True`. В `jobq/errors.py` SHALL быть класс `PermanentJobError(JobqError)`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и ошибка — `UnicodeError` (наследник `ValueError`) или `ValueError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Прочие ошибки повторяемы
- **WHEN** `non_retryable=(ValueError,)` и ошибка — `TimeoutError`
- **THEN** `is_retryable` возвращает `True`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** `non_retryable=()` и ошибка — `PermanentJobError("no")`
- **THEN** `is_retryable` возвращает `False`

### Requirement: Назначение политик очереди и типам заданий
`JobQueue.__init__` SHALL принимать keyword-only параметр `default_retry_policy: RetryPolicy | None = None`. `JobQueue.set_retry_policy(job_type: str, policy: RetryPolicy | None) -> None` SHALL задавать политику типа; `None` SHALL снимать политику типа. `JobQueue.retry_policy_for(job_type: str) -> RetryPolicy | None` SHALL возвращать действующую политику: политику типа, если она задана, иначе дефолт очереди, иначе `None`. Политика типа заменяет дефолт целиком, поля не сливаются. Значение, не являющееся `RetryPolicy` или `None`, а также пустой `job_type` SHALL приводить к `ConfigError`. Вызовы `JobQueue(...)` без нового параметра SHALL работать как раньше.

#### Scenario: Приоритет политик
- **WHEN** у очереди дефолт `A`, для типа `"mail"` задана `B`
- **THEN** `retry_policy_for("mail") is B`, а `retry_policy_for("billing") is A`

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** дефолт `RetryPolicy(non_retryable=(ValueError,))`, а для типа задана `RetryPolicy()`
- **THEN** `retry_policy_for(тип).non_retryable == ()`

#### Scenario: Снятие политики типа
- **WHEN** вызывается `set_retry_policy("mail", None)` после назначения политики
- **THEN** `retry_policy_for("mail")` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Политик нет
- **WHEN** нет ни дефолта, ни политики типа
- **THEN** `retry_policy_for(тип)` возвращает `None`

#### Scenario: Неверный аргумент
- **WHEN** вызывается `set_retry_policy("mail", "x")` или `JobQueue(default_retry_policy=5)`
- **THEN** выбрасывается `ConfigError`
