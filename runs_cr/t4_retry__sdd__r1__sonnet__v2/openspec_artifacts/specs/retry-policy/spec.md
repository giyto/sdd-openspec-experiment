# retry-policy Specification

## Purpose
Описывает неизменяемую политику повторов `RetryPolicy`: допустимые параметры, расчёт задержки перед повтором и определение того, стоит ли повторять упавшее задание.

## Requirements

### Requirement: Параметры политики и значения по умолчанию
Политика SHALL иметь параметры `max_attempts=3` (всего попыток, включая первую), `base_delay=1.0`, `factor=2.0`, `max_delay=60.0` (секунды), `jitter=0.0` и `non_retryable=()`. Политика SHALL быть неизменяемой. `non_retryable` SHALL принимать любую последовательность классов исключений и храниться как кортеж.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()` без аргументов
- **THEN** `max_attempts` равен 3, `base_delay` 1.0, `factor` 2.0, `max_delay` 60.0, `jitter` 0.0, `non_retryable` равен `()`

#### Scenario: Список приводится к кортежу
- **WHEN** в `non_retryable` передан список `[ValueError, KeyError]`
- **THEN** `policy.non_retryable == (ValueError, KeyError)`

### Requirement: Некорректные параметры отвергаются
Создание политики с некорректными параметрами SHALL завершаться `ConfigError`. Некорректны: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент `non_retryable`, не являющийся классом исключения (подкласс `BaseException`). Значения NaN в числовых параметрах SHALL тоже отвергаться. Граничные значения (`max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay == base_delay`, `jitter` 0 и 1) SHALL быть допустимы.

#### Scenario: Недопустимые числа
- **WHEN** создаётся политика с `max_attempts=0`, либо `base_delay=-1`, либо `factor=0.5`, либо `max_delay` меньше `base_delay`, либо `jitter=1.5`, либо `jitter=-0.1`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент не класс исключения
- **WHEN** в `non_retryable` передан экземпляр исключения `ValueError("x")`, строка или класс, не наследующий `BaseException`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения
- **WHEN** создаётся политика с `max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay=0`, `jitter=1`
- **THEN** ошибки нет

### Requirement: Расчёт задержки
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. Результат SHALL всегда лежать в `[0, max_delay]` для любого `attempt >= 1`, в том числе очень большого (например, 5000 при `factor=2.0`) и при `base_delay=0`. Переполнение float SHALL NOT приводить к исключению: переполненная задержка равна `max_delay`, а при `base_delay=0` результат равен 0. `attempt < 1` SHALL вызывать `ConfigError`.

#### Scenario: Экспоненциальный рост
- **WHEN** политика `base_delay=1, factor=2, max_delay=60` и вызывается `delay_for(1)`, `delay_for(2)`, `delay_for(3)`
- **THEN** результаты 1.0, 2.0, 4.0

#### Scenario: Потолок
- **WHEN** `delay_for(10)` при `base_delay=1, factor=2, max_delay=60`
- **THEN** результат 60.0

#### Scenario: Огромный номер попытки
- **WHEN** `max_attempts=10000` и вызывается `delay_for(5000)` при `factor=2.0`
- **THEN** результат равен `max_delay`, исключения нет

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(5000)`
- **THEN** результат 0.0

#### Scenario: Номер попытки меньше 1
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Джиттер
При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)`, после чего результат SHALL снова ограничиваться `max_delay` (потолок жёсткий), а снизу нулём. На один расчёт задержки SHALL приходиться ровно один вызов `uniform`. При `jitter == 0` генератор SHALL NOT вызываться. Если `rng` не передан, SHALL использоваться генератор модуля `random`.

#### Scenario: Предсказуемый джиттер
- **WHEN** `jitter=0.5`, `base_delay=10`, `rng.uniform` возвращает 0.75
- **THEN** `delay_for(1)` равна 7.5, `uniform` вызван один раз с аргументами `(0.5, 1.5)`

#### Scenario: Джиттер не пробивает потолок
- **WHEN** `jitter=1`, задержка уже равна `max_delay`, а `uniform` возвращает 2.0
- **THEN** результат равен `max_delay`

#### Scenario: Без джиттера генератор не трогается
- **WHEN** `jitter=0` и передан `rng`
- **THEN** `rng` не вызывается

### Requirement: Классификация повторяемости
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как `except`), и всегда `False` для `PermanentJobError` и его наследников, независимо от `non_retryable`. Для остальных исключений SHALL возвращать `True`. `PermanentJobError` SHALL наследоваться от `JobqError`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и проверяется `UnicodeDecodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError
- **WHEN** `non_retryable=()` и проверяется `PermanentJobError("no")`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка
- **WHEN** проверяется `TimeoutError()` при `non_retryable=(ValueError,)`
- **THEN** `is_retryable` возвращает `True`
