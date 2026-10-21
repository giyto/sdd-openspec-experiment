## Purpose

Определяет, как очередь и воркер выбирают действующую политику повторов и во что переводят задание при падении обработчика: `FAILED`, `RETRY_SCHEDULED` или `DEAD_LETTERED`.

## ADDED Requirements

### Requirement: Настройка политик повторов
`JobQueue` SHALL принимать `default_retry_policy: RetryPolicy | None = None` как keyword-only параметр конструктора, предоставлять `set_retry_policy(job_type, policy)` (`None` снимает политику типа) и `retry_policy_for(job_type) -> RetryPolicy | None`. Действующая политика типа — политика типа, если она задана, иначе дефолтная, иначе `None`. Политика типа MUST заменять дефолт целиком, без слияния по полям. `set_retry_policy` с пустым `job_type` или значением, не являющимся `RetryPolicy`/`None`, SHALL выбрасывать `ConfigError`; такой же ошибкой отклоняется некорректное значение `default_retry_policy`.

#### Scenario: Дефолт очереди
- **WHEN** очередь создана с `default_retry_policy=P` и для типа `"mail"` политика не задана
- **THEN** `retry_policy_for("mail") is P`

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** дефолт `RetryPolicy(non_retryable=(ValueError,))`, а для `"mail"` задана `RetryPolicy(max_attempts=5)`
- **THEN** `retry_policy_for("mail")` возвращает политику типа с `non_retryable == ()`

#### Scenario: Снятие политики типа
- **WHEN** вызывается `set_retry_policy("mail", None)` после установки политики
- **THEN** `retry_policy_for("mail")` возвращает дефолт очереди или `None`, если дефолта нет

#### Scenario: Нет политик
- **WHEN** ни дефолт, ни политика типа не заданы
- **THEN** `retry_policy_for("mail")` возвращает `None`

### Requirement: Результат падения обработчика
Когда обработчик бросил исключение, воркер SHALL использовать политику, действующую в момент ошибки (а не в момент постановки задания), и перевести задание в статус: `FAILED`, если политики нет или ошибка неповторяема (`is_retryable` — `False`), в том числе на последней попытке; `DEAD_LETTERED`, если ошибка повторяема и `job.attempts >= max_attempts`; иначе `RETRY_SCHEDULED`. Во всех случаях `job.error` MUST содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. Задания, перешедшие в `FAILED`, в dead-letter не попадают. `max_attempts=1` означает «без повторов, но в dead-letter», а не в `FAILED`. Если для типа задания не зарегистрирован обработчик, это ошибка конфигурации: задание сразу получает `FAILED`, независимо от политик.

#### Scenario: Без политики
- **WHEN** обработчик бросает `RuntimeError("boom")`, политик нет
- **THEN** статус `FAILED`, `error == "RuntimeError: boom"`, записей в dead-letter нет, `jobs.failed` увеличен

#### Scenario: Первая неудача, попытки остались
- **WHEN** политика `max_attempts=3`, обработчик падает на первой попытке
- **THEN** статус `RETRY_SCHEDULED`, `attempts == 1`, `error` содержит последнюю ошибку

#### Scenario: Попытки исчерпаны
- **WHEN** политика `max_attempts=3`, обработчик падает при `attempts == 3`
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` появилась запись

#### Scenario: max_attempts=1
- **WHEN** политика `max_attempts=1`, обработчик падает на первой попытке повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED` и не `RETRY_SCHEDULED`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** политика `max_attempts=3, non_retryable=(ValueError,)`, обработчик на третьей попытке бросает `ValueError`
- **THEN** статус `FAILED`, в dead-letter записи нет

#### Scenario: Наследник неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)`, обработчик бросает подкласс `ValueError`
- **THEN** статус `FAILED`

#### Scenario: PermanentJobError
- **WHEN** обработчик бросает `PermanentJobError("no")` при политике с оставшимися попытками
- **THEN** статус `FAILED`

#### Scenario: Нет обработчика для типа
- **WHEN** для типа задания нет зарегистрированного обработчика, политика задана
- **THEN** статус сразу `FAILED`, повтор не планируется, `rng` не используется

#### Scenario: Политика берётся на момент ошибки
- **WHEN** задание поставлено без политики, затем до выполнения для типа задана политика с `max_attempts=3`, и обработчик падает
- **THEN** статус `RETRY_SCHEDULED`

### Requirement: Планирование повтора
При переходе в `RETRY_SCHEDULED` воркер SHALL установить `run_at = now + delay_for(job.attempts, rng)`, где `now` — время часов очереди в момент ошибки, и передать в `delay_for` собственный `rng` (параметр `Worker(..., rng: random.Random | None = None)`, keyword-only). Задержка считается только при реальном планировании повтора: при `FAILED` и `DEAD_LETTERED` `rng` MUST NOT вызываться. При `jitter == 0` `rng` также не вызывается; при `jitter > 0` делается ровно один вызов `uniform` на повтор. Счётчик `jobs.retried` MUST увеличиваться на 1 при каждом переходе в `RETRY_SCHEDULED`.

#### Scenario: Время повтора
- **WHEN** в момент `T` задание падает с `attempts == 2`, политика `base_delay=1, factor=2`
- **THEN** `run_at == T + 2 секунды`

#### Scenario: Детерминированный rng
- **WHEN** `Worker` создан с `random.Random(42)` и `jitter > 0`
- **THEN** задержка повторяет `policy.delay_for(attempts, random.Random(42))`, а состояние `rng` продвинулось ровно на один `uniform`

#### Scenario: rng не трогается при финальных исходах
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED` при `jitter > 0`
- **THEN** `rng` не вызывался

#### Scenario: Счётчик повторов
- **WHEN** задание дважды уходит в `RETRY_SCHEDULED`
- **THEN** `jobs.retried == 2`

### Requirement: Выбор заданий в RETRY_SCHEDULED
Воркер SHALL брать задание в `RETRY_SCHEDULED` тогда, когда наступил его `run_at`, как и `PENDING`: сортировка по `run_at`, затем по порядку постановки. До `run_at` задание MUST NOT выбираться. Запуск из `RETRY_SCHEDULED` увеличивает `attempts` и `jobs.started` как обычно. `cancel` MUST быть допустим для `RETRY_SCHEDULED`.

#### Scenario: Повтор ещё не наступил
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at` в будущем
- **THEN** `run_once()` возвращает `None`, `next_due()` не возвращает это задание

#### Scenario: Повтор наступил
- **WHEN** часы продвинуты до `run_at` задания в `RETRY_SCHEDULED`
- **THEN** `run_once()` выполняет задание с `attempts` на единицу больше; при успехе статус `SUCCEEDED`, а `error` равен `None`

#### Scenario: Полный цикл до dead-letter
- **WHEN** обработчик всегда падает при `max_attempts=3`, часы продвигаются до каждого `run_at`
- **THEN** задание выполнено 3 раза, статус `DEAD_LETTERED`, `jobs.retried == 2`, `jobs.dead_lettered == 1`

### Requirement: Обратная совместимость
Существующие публичные сигнатуры SHALL остаться совместимыми: новые параметры только keyword-only, старые вызовы работают как раньше. Без какой-либо политики любое исключение обработчика ведёт к `FAILED`, как сейчас. `stats()` MUST включать новые статусы (по ключам `retry_scheduled`, `dead_lettered`).

#### Scenario: Старые вызовы
- **WHEN** создаются `JobQueue()` и `Worker(queue, registry)` без новых параметров
- **THEN** они работают как до изменения

### Requirement: Подписи статусов в отчёте дежурных
Новые статусы SHALL иметь подписи `RETRY_SCHEDULED` — «Ожидает повтора», `DEAD_LETTERED` — «В dead-letter». Отчёт дежурных MUST выводить эти строки без изменения `jobq/dashboard.py` и `jobq/cli.py`.

#### Scenario: Отчёт
- **WHEN** строится отчёт для очереди с заданиями в новых статусах
- **THEN** он содержит строки «Ожидает повтора» и «В dead-letter» с количествами
