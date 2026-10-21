## Purpose

Повторное выполнение заданий, упавших из-за временных ошибок: настраиваемая политика с экспоненциальной задержкой, выбор политики и решение воркера о судьбе упавшего задания.

## ADDED Requirements

### Requirement: Валидация параметров политики
Система SHALL отклонять некорректную `RetryPolicy` ошибкой конфигурации (`ConfigError`) при создании: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент `non_retryable`, не являющийся классом исключения. Параметр `non_retryable` SHALL приниматься в виде любой последовательности (в том числе списка) и храниться как неизменяемый кортеж. Значения по умолчанию: `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`.

#### Scenario: Некорректное число попыток
- **WHEN** создаётся политика с `max_attempts=0`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Максимальная задержка меньше базовой
- **WHEN** создаётся политика с `base_delay=5` и `max_delay=4`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Jitter вне диапазона
- **WHEN** создаётся политика с `jitter=1.5` или `jitter=-0.1`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Неисключение в non_retryable
- **WHEN** в `non_retryable` передан объект, не являющийся классом-наследником `BaseException` (например, строка `"ValueError"` или экземпляр исключения)
- **THEN** выбрасывается `ConfigError`

#### Scenario: Список превращается в кортеж
- **WHEN** в `non_retryable` передан список `[ValueError]`
- **THEN** политика хранит `(ValueError,)`

### Requirement: Расчёт задержки
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1) как `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)` ровно одним обращением к `rng` на вызов, а результат SHALL быть не больше `max_delay` (`max_delay` — жёсткий потолок и для jitter); при `jitter == 0` `rng` SHALL NOT использоваться. `attempt < 1` SHALL приводить к `ConfigError`. Функция SHALL работать для любого `attempt` без `OverflowError`: слишком большая степень даёт `max_delay`, а при `base_delay == 0` результат равен `0`.

#### Scenario: Экспоненциальный рост с ограничением
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`
- **THEN** `delay_for(1)=1`, `delay_for(4)=8`, `delay_for(10)=60`

#### Scenario: Огромный номер попытки
- **WHEN** вызывается `delay_for(5001)` при `factor=2.0` и `max_delay=60`
- **THEN** возвращается `60` без исключения

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(10000)`
- **THEN** возвращается `0`

#### Scenario: Jitter не превышает max_delay
- **WHEN** `jitter=0.5`, задержка до jitter ограничена `max_delay=60`, а `rng.uniform(0.5, 1.5)` вернул `1.5`
- **THEN** результат равен `60`

#### Scenario: Jitter уменьшает задержку
- **WHEN** `jitter=0.5`, `base_delay=10`, `attempt=1`, а `rng.uniform(0.5, 1.5)` вернул `0.5`
- **THEN** результат равен `5`

#### Scenario: Без jitter rng не трогается
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Номер попытки меньше 1
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда для `PermanentJobError` и её наследников, независимо от `non_retryable`. Для остальных исключений SHALL возвращать `True`. `PermanentJobError` SHALL наследоваться от `JobqError`.

#### Scenario: Наследник неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и обработчик бросил `UnicodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError
- **WHEN** обработчик бросил `PermanentJobError`, а `non_retryable` пуст
- **THEN** `is_retryable` возвращает `False`

### Requirement: Выбор политики
Очередь SHALL принимать `default_retry_policy` (keyword-only, по умолчанию `None`), позволять задавать политику типа задания через `set_retry_policy(job_type, policy)` и снимать её передачей `None`. `retry_policy_for(job_type)` SHALL возвращать действующую политику: политику типа, а если её нет — дефолт очереди, а если нет и его — `None`. Политика типа SHALL заменять дефолт целиком, поля не сливаются. При ошибке SHALL применяться политика, действующая в момент ошибки, а не в момент постановки.

#### Scenario: Политика типа заменяет дефолт
- **WHEN** дефолт задаёт `non_retryable=(ValueError,)`, а политика типа создана без `non_retryable`
- **THEN** для этого типа `ValueError` считается повторяемой

#### Scenario: Снятие политики типа
- **WHEN** политика типа снята через `set_retry_policy(job_type, None)`
- **THEN** `retry_policy_for(job_type)` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Политика меняется между постановкой и ошибкой
- **WHEN** задание поставлено без политики, затем задана политика типа, затем обработчик упал
- **THEN** применяется заданная политика

### Requirement: Решение воркера при падении обработчика
Когда обработчик бросает исключение (`Exception`), воркер SHALL выбрать результат в таком порядке: (1) если политики нет или ошибка неповторяемая (`is_retryable` ложно) — статус `FAILED`, даже на последней попытке; (2) иначе если `job.attempts >= max_attempts` — статус `DEAD_LETTERED`; (3) иначе статус `RETRY_SCHEDULED` и `run_at = now + delay_for(job.attempts, rng)` по часам очереди. `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. Задержка и `rng` SHALL использоваться только в случае (3). Отсутствие обработчика для типа задания — ошибка конфигурации: статус `FAILED` сразу, без повторов, независимо от политики. Без действующей политики поведение SHALL совпадать с прежним. `max_attempts=1` означает «без повторов, но в dead-letter».

#### Scenario: Планирование повтора
- **WHEN** обработчик упал на попытке 1 при `max_attempts=3`, `base_delay=10`
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равен текущему времени плюс 10 секунд, `error` содержит последнюю ошибку, счётчик `jobs.retried` вырос на 1

#### Scenario: Попытки кончились
- **WHEN** обработчик упал на попытке 3 при `max_attempts=3` и ошибка повторяемая
- **THEN** статус `DEAD_LETTERED`, запись появилась в `dead_letters()`

#### Scenario: Одна попытка
- **WHEN** `max_attempts=1` и обработчик упал с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** на последней попытке обработчик бросил исключение из `non_retryable`
- **THEN** статус `FAILED`, в dead-letter запись не добавляется

#### Scenario: Нет обработчика
- **WHEN** для типа задания не зарегистрирован обработчик, политика задана
- **THEN** статус `FAILED` сразу, `rng` не использовался

#### Scenario: Предсказуемый rng
- **WHEN** `jitter > 0`, воркер создан с `rng` и задание идёт в `FAILED` или `DEAD_LETTERED`
- **THEN** `rng` не вызывается; при планировании повтора вызывается ровно один раз

#### Scenario: Повтор берётся по времени
- **WHEN** задание в `RETRY_SCHEDULED` и часы дошли до его `run_at`
- **THEN** воркер берёт его в работу наравне с `PENDING`; до `run_at` не берёт

### Requirement: Статусы в отчёте и статистике
`JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`) SHALL иметь подпись «Ожидает повтора», `JobStatus.DEAD_LETTERED` (`"dead_lettered"`) — «В dead-letter». `queue.stats()` SHALL содержать оба статуса. Ни один из них не является терминальным (`is_terminal` ложно). Задание в `RETRY_SCHEDULED` SHALL быть отменяемым через `cancel`.

#### Scenario: Подписи
- **WHEN** запрашиваются `label` новых статусов
- **THEN** возвращаются «Ожидает повтора» и «В dead-letter»

#### Scenario: Отмена ожидающего повтора
- **WHEN** вызывается `cancel` для задания в `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`
