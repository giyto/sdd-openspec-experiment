## MODIFIED Requirements

### Requirement: Решение при ошибке обработчика
Когда обработчик бросил исключение, воркер SHALL выбрать результат по политике, действующей в момент ошибки (не в момент постановки):
1. политики нет → `FAILED`;
2. ошибка неповторяемая (класс из `non_retryable` или `PermanentJobError`) → `DEAD_LETTERED` сразу, без повторов и даже на первой попытке, с записью в dead-letter с причиной `non_retryable`;
3. иначе, если `attempts >= max_attempts` → `DEAD_LETTERED` и запись в dead-letter с причиной `exhausted`;
4. иначе → `RETRY_SCHEDULED`, `run_at` = текущее время очереди + задержка для номера только что упавшей попытки (`job.attempts`).

Причина важнее счётчика попыток: неповторяемая ошибка на последней попытке даёт `non_retryable`. Поле `error` SHALL всегда содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. При `max_attempts=1` повторяемая ошибка SHALL сразу давать `DEAD_LETTERED` с причиной `exhausted`. Для типа без зарегистрированного обработчика SHALL сразу устанавливаться `FAILED` независимо от политики. Для неповторяемой ошибки задержка не вычисляется.

#### Scenario: Без политики
- **WHEN** политики нет и обработчик упал (в том числе `PermanentJobError`)
- **THEN** статус `FAILED`, в dead-letter записи нет

#### Scenario: Первая ошибка при max_attempts=3
- **WHEN** обработчик упал на первой попытке повторяемой ошибкой
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равен текущему времени плюс задержка для попытки 1, `error` содержит ошибку

#### Scenario: Попытки исчерпаны
- **WHEN** обработчик упал на попытке номер `max_attempts` повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, в dead-letter появилась запись с причиной `exhausted`

#### Scenario: max_attempts=1
- **WHEN** политика с `max_attempts=1` и обработчик упал повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED` с причиной `exhausted`, задержка не считается

#### Scenario: Неповторяемая ошибка на первой попытке
- **WHEN** при действующей политике и `max_attempts=3` на первой попытке брошена ошибка из `non_retryable` или `PermanentJobError`
- **THEN** статус `DEAD_LETTERED`, причина `non_retryable`, `attempts=1`, `jobs.dead_lettered` увеличен, `jobs.failed` и `jobs.retried` не изменились

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** на последней попытке брошена ошибка из `non_retryable` или `PermanentJobError`
- **THEN** статус `DEAD_LETTERED`, причина `non_retryable`

#### Scenario: Нет обработчика
- **WHEN** для типа задания нет обработчика, а политика задана
- **THEN** статус `FAILED` сразу, повтор не планируется, в dead-letter записи нет

#### Scenario: Политика изменена после постановки
- **WHEN** политика типа изменена между постановкой и ошибкой
- **THEN** используется политика, действующая в момент ошибки

### Requirement: Использование генератора случайных чисел
Воркер SHALL принимать необязательный генератор (только именованным параметром) и передавать его в расчёт задержки. Генератор SHALL использоваться только при планировании повтора по задержке из политики и только при `jitter > 0`: не более одного вызова на задержку, ни одного — при `FAILED`, `DEAD_LETTERED` (по любой причине), при `jitter == 0` и при повторе, запланированном по `RetryLaterError`.

#### Scenario: Генератор не трогается
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED` (в том числе по неповторяемой ошибке)
- **THEN** состояние генератора не меняется

#### Scenario: Предсказуемый джиттер
- **WHEN** повтор планируется при `jitter > 0` с генератором с фиксированным зерном
- **THEN** `run_at` соответствует ровно одному значению этого генератора, а задержка не больше расчётной

#### Scenario: Генератор и RetryLaterError
- **WHEN** повтор планируется по `RetryLaterError` при `jitter > 0`
- **THEN** состояние генератора не меняется

## ADDED Requirements

### Requirement: Повтор по указанию внешнего сервиса
Пакет SHALL предоставлять исключение `RetryLaterError(message="", *, retry_after)`, наследующее базовую ошибку пакета; `retry_after` (секунды) передаётся только именованным параметром, обязателен и доступен как атрибут. Значение `retry_after < 0`, нечисловое (включая `bool`) или NaN SHALL вызывать ошибку конфигурации при создании исключения; `0` допустим. Если обработчик бросил `RetryLaterError`, это обычная временная ошибка: при действующей политике и `attempts < max_attempts` SHALL планироваться `RETRY_SCHEDULED` с `run_at` = текущее время очереди + `min(retry_after, max_delay)` секунд вместо задержки из политики. Джиттер к этой задержке SHALL не применяться, генератор не вызываться. `max_delay` остаётся потолком любой задержки. На последней попытке (`attempts >= max_attempts`) результат — `DEAD_LETTERED` с причиной `exhausted`; без политики — `FAILED`. Классификация повторяемости остаётся общей: если политика явно относит `RetryLaterError` к `non_retryable`, он обрабатывается как неповторяемая ошибка. Поле `error` имеет обычный формат `"RetryLaterError: сообщение"`.

#### Scenario: Задержка из retry_after
- **WHEN** политика `max_attempts=3, base_delay=1, max_delay=60`, обработчик бросил `RetryLaterError(retry_after=30)` на первой попытке
- **THEN** статус `RETRY_SCHEDULED`, `run_at` = сейчас + 30 секунд

#### Scenario: Потолок max_delay
- **WHEN** `max_delay=60`, брошено `RetryLaterError(retry_after=3600)`
- **THEN** `run_at` = сейчас + 60 секунд

#### Scenario: Без джиттера
- **WHEN** `jitter=0.5` с генератором и брошено `RetryLaterError(retry_after=30)`
- **THEN** `run_at` = сейчас + 30 секунд ровно, генератор не вызывался

#### Scenario: Нулевой retry_after
- **WHEN** брошено `RetryLaterError(retry_after=0)`
- **THEN** `run_at` = сейчас, статус `RETRY_SCHEDULED`

#### Scenario: Последняя попытка
- **WHEN** `RetryLaterError` брошен на попытке номер `max_attempts`
- **THEN** статус `DEAD_LETTERED`, причина `exhausted`

#### Scenario: Без политики
- **WHEN** политики нет и брошен `RetryLaterError`
- **THEN** статус `FAILED`

#### Scenario: Отрицательный retry_after
- **WHEN** создаётся `RetryLaterError(retry_after=-1)`
- **THEN** выбрасывается ошибка конфигурации

#### Scenario: Сообщение по умолчанию
- **WHEN** создаётся `RetryLaterError(retry_after=5)` без сообщения
- **THEN** сообщение пустое, `retry_after` равно 5
