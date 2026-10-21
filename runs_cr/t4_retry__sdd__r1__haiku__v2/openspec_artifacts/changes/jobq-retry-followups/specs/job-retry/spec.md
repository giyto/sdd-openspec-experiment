## MODIFIED Requirements

### Requirement: Delay computation
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой после падения попытки с номером `attempt`
(нумерация с 1): `base_delay * factor ** (attempt - 1)`, ограниченную сверху значением `max_delay`.

`delay_for` MUST возвращать значение из диапазона `[0, max_delay]` для любого `attempt >= 1`, включая очень большие
значения, и MUST NOT выбрасывать `OverflowError`.

При `jitter > 0` ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1)`. Джиттер только уменьшает
задержку: результат MUST NOT превышать ограниченную задержку, и повтор MUST NOT приходить позже расчётного времени.

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
- **WHEN** политика с `base_delay=2.0`, `jitter=0.5`, а `rng.uniform(0.5, 1)` возвращает 0.75
- **THEN** `delay_for(1, rng)` возвращает 1.5, и `rng.uniform` вызван с аргументами `(0.5, 1)`

#### Scenario: Джиттер не увеличивает задержку
- **WHEN** политика с `base_delay=2.0`, `jitter=0.5`, а `rng.uniform(0.5, 1)` возвращает 1.0
- **THEN** `delay_for(1, rng)` возвращает 2.0, и результат не больше `delay_for(1)` без джиттера

#### Scenario: Джиттер не пробивает max_delay
- **WHEN** политика с `max_delay=60.0`, `jitter=1.0`, номер попытки велик
- **THEN** `delay_for(attempt, rng)` возвращает значение не больше 60.0

#### Scenario: Без джиттера генератор не используется
- **WHEN** политика с `jitter=0` и передан `rng`, который отмечает любой вызов
- **THEN** `delay_for(n, rng)` не обращается к `rng`

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Worker decision after handler failure
Когда обработчик выбрасывает исключение, воркер SHALL выбрать статус задания по следующим правилам, проверяя их по порядку:

1. Если действующей политики нет, задание переходит в `FAILED`, как и раньше.
2. Если `is_retryable(exc)` возвращает `False`, задание переходит в `DEAD_LETTERED` с причиной `NON_RETRYABLE`
   (см. `job-dead-letter`), даже на последней попытке. Повтор не планируется.
3. Если `job.attempts >= max_attempts`, задание переходит в `DEAD_LETTERED` с причиной `EXHAUSTED`.
4. Если исключение является `RetryLaterError`, задание переходит в `RETRY_SCHEDULED`, а `run_at` становится текущим
   временем плюс задержка из требования «Server-specified retry delay». Джиттер при этом не применяется.
5. Иначе задание переходит в `RETRY_SCHEDULED`, а `run_at` становится текущим временем плюс `delay_for(job.attempts, rng)`.

`job.error` MUST содержать текст последней ошибки в формате `ИмяКласса: сообщение` для всех исходов.
Задержка SHALL вычисляться только в ветках 4 и 5; `rng` в остальных ветках MUST NOT использоваться.

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
- **THEN** статус задания `DEAD_LETTERED` с причиной `EXHAUSTED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** политика с `max_attempts=3` и обработчик падает с исключением из `non_retryable` на первой попытке
- **THEN** статус задания `DEAD_LETTERED` с причиной `NON_RETRYABLE`, повтор не планируется

#### Scenario: PermanentJobError на первой попытке
- **WHEN** политика с `max_attempts=3`, задание на первой попытке падает с `PermanentJobError`
- **THEN** статус задания `DEAD_LETTERED` с причиной `NON_RETRYABLE`

#### Scenario: PermanentJobError на последней попытке
- **WHEN** политика с `max_attempts=3`, задание на третьей попытке падает с `PermanentJobError`
- **THEN** статус задания `DEAD_LETTERED` с причиной `NON_RETRYABLE`, а не `EXHAUSTED`

#### Scenario: Нет обработчика типа
- **WHEN** у задания нет зарегистрированного обработчика, а политика задана
- **THEN** статус задания `FAILED` и повтора не планируется

#### Scenario: Политика не задана
- **WHEN** ни политика типа, ни политика по умолчанию не заданы, и обработчик падает с `PermanentJobError`
- **THEN** статус задания `FAILED`, поведение совпадает с текущим

#### Scenario: Политика берётся на момент ошибки
- **WHEN** задание поставлено без политики, политика типа задана до его выполнения, и обработчик падает
- **THEN** решение принимается по политике типа, действующей в момент ошибки

#### Scenario: Успех после повтора очищает ошибку
- **WHEN** задание упало с повтором, при следующем запуске обработчик завершился успешно
- **THEN** статус `SUCCEEDED`, `job.error` равен `None`

## ADDED Requirements

### Requirement: Server-specified retry delay
`RetryLaterError(message: str = "", *, retry_after: float)` SHALL быть исключением пакета (наследником `JobqError`),
которое обработчик бросает, когда внешний сервис сам назвал время следующей попытки. `retry_after` — секунды.
Конструктор SHALL выбрасывать `ConfigError`, если `retry_after` меньше нуля, не является числом или не конечен.

Для `RetryLaterError` воркер SHALL планировать повтор через `min(retry_after, max_delay)` секунд. Это обычная временная
ошибка: она повторяема, если не входит в `non_retryable`, и учитывается в `max_attempts`. Джиттер к этой задержке
MUST NOT применяться, а `rng` MUST NOT вызываться. Значение `retry_after = 0` означает повтор сразу.

Без действующей политики `RetryLaterError` ведёт себя как любая ошибка: задание переходит в `FAILED`.

#### Scenario: Retry-After больше max_delay режется до max_delay
- **WHEN** политика с `max_delay=60.0`, обработчик бросает `RetryLaterError(retry_after=3600)` на первой попытке
- **THEN** статус `RETRY_SCHEDULED`, а `run_at` равно текущему времени плюс 60 секунд

#### Scenario: Retry-After заменяет расчётную задержку
- **WHEN** политика с `base_delay=1.0`, а обработчик бросает `RetryLaterError(retry_after=7)` на первой попытке
- **THEN** `run_at` равно текущему времени плюс 7 секунд, а не `delay_for(1)`

#### Scenario: Джиттер и генератор не используются
- **WHEN** политика с `jitter=0.5` и передан `rng`, который отмечает любой вызов, а обработчик бросает `RetryLaterError(retry_after=5)`
- **THEN** `run_at` равно текущему времени плюс 5 секунд, и `rng` не вызывается

#### Scenario: Нулевой Retry-After повторяет сразу
- **WHEN** обработчик бросает `RetryLaterError(retry_after=0)`
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равно текущему времени, и задание запускается при следующем `run_once()`

#### Scenario: Отрицательный Retry-After — ошибка конфигурации
- **WHEN** создаётся `RetryLaterError(retry_after=-1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: RetryLaterError на последней попытке
- **WHEN** политика с `max_attempts=3`, задание на третьей попытке падает с `RetryLaterError`
- **THEN** статус `DEAD_LETTERED` с причиной `EXHAUSTED`, а не `NON_RETRYABLE`
