# job-retry Specification

## Purpose
Настраиваемая политика повторов упавших заданий: сколько всего попыток сделать, сколько ждать перед
каждой и какие ошибки повторять нельзя. Определяет, в какой статус переходит задание после падения обработчика.

## Requirements

### Requirement: Retry policy parameters
The system SHALL предоставлять `RetryPolicy` с полями `max_attempts` (по умолчанию 3, всего попыток включая первую),
`base_delay` (по умолчанию 1.0 секунды), `factor` (по умолчанию 2.0), `max_delay` (по умолчанию 60.0 секунд),
`jitter` (по умолчанию 0.0) и `non_retryable` (по умолчанию пустой). Список `non_retryable`, переданный как
список, SHALL храниться как кортеж.

The system MUST отклонять некорректные параметры ошибкой `ConfigError`: `max_attempts < 1`, `base_delay < 0`,
`factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, нечисловые значения и `NaN`/бесконечность, а также
элемент `non_retryable`, который не является классом исключения.

#### Scenario: Список неповторяемых исключений хранится кортежем
- **WHEN** политика создана с `non_retryable=[ValueError]`
- **THEN** поле `non_retryable` равно `(ValueError,)`

#### Scenario: Некорректный параметр отклоняется
- **WHEN** создаётся политика с `max_attempts=0`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не является классом исключения
- **WHEN** создаётся политика с `non_retryable=("timeout",)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Delay computation
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой после падения попытки с номером `attempt`
(нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху значением `max_delay`.

`delay_for` MUST возвращать значение из диапазона `[0, max_delay]` для любого `attempt >= 1`, включая очень большие
значения, и MUST NOT выбрасывать `OverflowError`.

При `jitter > 0` ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)`. Результат SHALL
снова ограничиваться `max_delay`: джиттер не пробивает верхний предел.

При `jitter = 0` генератор `rng` MUST NOT вызываться.

`delay_for` MUST выбрасывать `ConfigError` при `attempt < 1`.

#### Scenario: Экспоненциальный рост задержки
- **WHEN** политика с `base_delay=1.0`, `factor=2.0`, `max_delay=60.0` и `jitter=0`
- **THEN** `delay_for(1)` равно 1.0, `delay_for(2)` равно 2.0, `delay_for(3)` равно 4.0

#### Scenario: Задержка ограничена max_delay
- **WHEN** политика с `base_delay=1.0`, `factor=2.0`, `max_delay=60.0` и `jitter=0`
- **THEN** `delay_for(10)` равно 60.0

#### Scenario: Очень большой номер попытки не переполняет вычисление
- **WHEN** политика с `factor=2.0` и `max_delay=60.0`
- **THEN** `delay_for(5000)` возвращает 60.0 и не выбрасывает исключения

#### Scenario: Нулевая базовая задержка
- **WHEN** политика с `base_delay=0.0`
- **THEN** `delay_for(100)` возвращает 0.0

#### Scenario: Джиттер умножает ограниченную задержку
- **WHEN** политика с `base_delay=2.0`, `jitter=0.5`, а `rng.uniform(0.5, 1.5)` возвращает 1.5
- **THEN** `delay_for(1, rng)` возвращает 3.0

#### Scenario: Джиттер не пробивает max_delay
- **WHEN** политика с `max_delay=60.0`, `jitter=1.0`, а `rng.uniform(0.0, 2.0)` возвращает 2.0 и номер попытки велик
- **THEN** `delay_for(attempt, rng)` возвращает 60.0

#### Scenario: Без джиттера генератор не используется
- **WHEN** политика с `jitter=0` и передан `rng`, который отмечает любой вызов
- **THEN** `delay_for(n, rng)` не обращается к `rng`

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Retryability of errors
`is_retryable(exc)` SHALL возвращать `False`, если `exc` является экземпляром любого класса из `non_retryable`
(наследники учитываются, как в обычном `except`). `is_retryable` MUST возвращать `False` для любого
`PermanentJobError`, даже если `non_retryable` пуст. Во всех остальных случаях SHALL возвращать `True`.

#### Scenario: Наследник неповторяемого исключения
- **WHEN** политика с `non_retryable=(ValueError,)` и ошибка является подклассом `ValueError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError не повторяется
- **WHEN** политика с пустым `non_retryable` и ошибка `PermanentJobError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Прочие ошибки повторяются
- **WHEN** политика с `non_retryable=(ValueError,)` и ошибка `TimeoutError`
- **THEN** `is_retryable` возвращает `True`

### Requirement: Retry policy resolution
Политика типа задания SHALL полностью заменять политику по умолчанию очереди; поля политик не сливаются.
`JobQueue.set_retry_policy(job_type, None)` SHALL снимать политику типа, после чего действует политика по умолчанию.
`JobQueue.retry_policy_for(job_type)` SHALL возвращать действующую политику: политику типа, иначе политику по
умолчанию, иначе `None`.

Политика, действующая в момент ошибки, SHALL определять решение воркера; политика на момент постановки в очередь
не учитывается.

#### Scenario: Политика типа не сливается с политикой по умолчанию
- **WHEN** политика по умолчанию имеет `non_retryable=(ValueError,)`, а для типа задан `RetryPolicy()` с пустым `non_retryable`
- **THEN** `retry_policy_for(тип)` возвращает политику типа, и `ValueError` для этого типа повторяется

#### Scenario: Снятие политики типа
- **WHEN** для типа задана политика, затем вызвано `set_retry_policy(тип, None)`
- **THEN** `retry_policy_for(тип)` возвращает политику по умолчанию очереди

#### Scenario: Политики нет
- **WHEN** ни политика типа, ни политика по умолчанию не заданы
- **THEN** `retry_policy_for(тип)` возвращает `None`

#### Scenario: Некорректное значение политики
- **WHEN** вызывается `set_retry_policy(тип, "3")`
- **THEN** выбрасывается `ConfigError`

### Requirement: Worker decision after handler failure
Когда обработчик выбрасывает исключение, воркер SHALL выбрать статус задания по следующим правилам, проверяя их по порядку:

1. Если действующей политики нет, задание переходит в `FAILED`, как и раньше.
2. Если `is_retryable(exc)` возвращает `False`, задание переходит в `FAILED`, даже на последней попытке. Такие задания в dead-letter не попадают.
3. Если `job.attempts >= max_attempts`, задание переходит в `DEAD_LETTERED` (см. `job-dead-letter`).
4. Иначе задание переходит в `RETRY_SCHEDULED`, а `run_at` становится текущим временем плюс `delay_for(job.attempts, rng)`.

`job.error` MUST содержать текст последней ошибки в формате `ИмяКласса: сообщение` для всех трёх исходов.
Задержка SHALL вычисляться только в ветке 4; `rng` в остальных ветках MUST NOT использоваться.

Задание с неизвестным типом (нет обработчика) SHALL переходить в `FAILED` без повторов, даже если политика задана.

Успешное выполнение SHALL очищать `job.error`, так как у задания в `SUCCEEDED` ошибки быть не должно.

#### Scenario: Первое падение планирует повтор
- **WHEN** политика с `max_attempts=3`, задание падает на первой попытке с `TimeoutError`
- **THEN** статус задания `RETRY_SCHEDULED`, `job.error` равен `"TimeoutError: ..."`, а `run_at` равно текущему времени плюс `delay_for(1)`

#### Scenario: Повтор не запускается до run_at
- **WHEN** задание в `RETRY_SCHEDULED` и часы ещё не дошли до `run_at`
- **THEN** `run_once()` возвращает `None`, а после продвижения часов задание запускается снова с `attempts` = 2

#### Scenario: Единственная попытка без повторов уходит в dead-letter
- **WHEN** политика с `max_attempts=1` и обработчик падает с повторяемой ошибкой
- **THEN** статус задания `DEAD_LETTERED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** политика с `max_attempts=3` и обработчик падает с исключением из `non_retryable`
- **THEN** статус задания `FAILED`

#### Scenario: PermanentJobError на последней попытке
- **WHEN** политика с `max_attempts=3`, задание на третьей попытке падает с `PermanentJobError`
- **THEN** статус задания `FAILED`, а не `DEAD_LETTERED`

#### Scenario: Нет обработчика типа
- **WHEN** у задания нет зарегистрированного обработчика, а политика задана
- **THEN** статус задания `FAILED` и повтора не планируется

#### Scenario: Политика не задана
- **WHEN** ни политика типа, ни политика по умолчанию не заданы, и обработчик падает
- **THEN** статус задания `FAILED`, поведение совпадает с текущим

#### Scenario: Политика берётся на момент ошибки
- **WHEN** задание поставлено без политики, политика типа задана до его выполнения, и обработчик падает
- **THEN** решение принимается по политике типа, действующей в момент ошибки

#### Scenario: Успех после повтора очищает ошибку
- **WHEN** задание упало с повтором, при следующем запуске обработчик завершился успешно
- **THEN** статус `SUCCEEDED`, `job.error` равен `None`

### Requirement: Retry statuses and cancellation
`JobStatus.RETRY_SCHEDULED` SHALL иметь значение `"retry_scheduled"` и подпись «Ожидает повтора». Статус
MUST NOT считаться терминальным. Воркер SHALL брать задание в этом статусе, когда наступил его `run_at`, так же,
как обычное готовое задание. `JobQueue.cancel()` SHALL отменять задание в `RETRY_SCHEDULED` так же, как ожидающее задание.

#### Scenario: Подпись статуса в отчёте
- **WHEN** запрашивается `JobStatus.RETRY_SCHEDULED.label`
- **THEN** возвращается «Ожидает повтора»

#### Scenario: Отмена задания, ожидающего повтора
- **WHEN** задание в `RETRY_SCHEDULED` отменяется через `cancel()`
- **THEN** статус `CANCELLED`, `finished_at` заполнен, счётчик `jobs.cancelled` увеличен на 1

### Requirement: Retry metrics
Счётчик `jobs.retried` SHALL увеличиваться ровно в момент перехода задания в `RETRY_SCHEDULED`. При таком переходе
счётчик `jobs.failed` MUST NOT увеличиваться. Счётчик `jobs.failed` увеличивается только при переходе в `FAILED`.
Счётчик `jobs.started` увеличивается при каждом запуске обработчика.

#### Scenario: Успех на третьей попытке
- **WHEN** политика с `max_attempts=3`, первые две попытки падают с повторяемой ошибкой, третья успешна
- **THEN** `jobs.started` = 3, `jobs.retried` = 2, `jobs.succeeded` = 1, `jobs.failed` = 0

### Requirement: Backward compatibility of the public API
Сигнатуры существующих публичных методов SHALL NOT меняться. Новые параметры `default_retry_policy` у `JobQueue` и
`rng` у `Worker` SHALL быть keyword-only. Вызовы без новых параметров MUST вести себя как до изменения.

#### Scenario: Старый вызов без политики
- **WHEN** очередь и воркер создаются без новых параметров, обработчик падает
- **THEN** задание переходит в `FAILED`, счётчики `jobs.retried` и `jobs.dead_lettered` равны 0
