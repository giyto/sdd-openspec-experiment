## Purpose

Описывает поведение очереди и воркера при падении обработчика: повторы по политике, перенос исчерпавших попытки заданий в dead-letter, осознанный возврат из dead-letter, счётчики и подписи в отчёте.

## ADDED Requirements

### Requirement: Выбор политики повторов
Очередь SHALL принимать политику по умолчанию (`default_retry_policy`, keyword-only, по умолчанию `None`) и политику для типа задания (`set_retry_policy(job_type, policy)`; `None` снимает политику типа). `retry_policy_for(job_type)` SHALL возвращать политику типа, а если её нет — политику по умолчанию, а если нет и её — `None`. Политика типа SHALL полностью заменять политику по умолчанию, поля не сливаются. Политика SHALL определяться в момент ошибки, а не в момент постановки. Значение, не являющееся `RetryPolicy` или `None`, и пустой `job_type` SHALL вызывать `ConfigError`.

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** по умолчанию задана политика с `non_retryable=(ValueError,)`, а для типа `email` — политика без `non_retryable`
- **THEN** `retry_policy_for("email")` возвращает политику типа, и `ValueError` в заданиях `email` повторяется

#### Scenario: Снятие политики типа
- **WHEN** вызван `set_retry_policy("email", None)`
- **THEN** `retry_policy_for("email")` возвращает политику по умолчанию (или `None`)

#### Scenario: Политика меняется после постановки
- **WHEN** задание поставлено, затем изменена политика типа, затем обработчик упал
- **THEN** применяется политика, действующая в момент падения

### Requirement: Без политики поведение прежнее
Если для типа задания нет действующей политики, любое исключение обработчика SHALL переводить задание в `FAILED`, как до изменения; новые статусы и счётчики не используются. Существующие сигнатуры публичных методов SHALL не меняться, старые вызовы работают как раньше.

#### Scenario: Падение без политики
- **WHEN** обработчик бросает `RuntimeError`, политик нет
- **THEN** задание в `FAILED`, `error` равен `"RuntimeError: ..."`, `jobs.failed` увеличен на 1

### Requirement: Статус задания после падения обработчика
Когда обработчик бросил исключение и действует политика, воркер SHALL выбирать статус в таком порядке: (1) если ошибка неповторяемая (`is_retryable` ложно) — `FAILED`, даже на последней попытке, запись в dead-letter не создаётся; (2) иначе, если `job.attempts >= max_attempts` — `DEAD_LETTERED` и запись в `dead_letters()`; (3) иначе — `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`. `max_attempts=1` означает «без повторов, но в dead-letter». Отсутствие обработчика для типа задания — ошибка конфигурации: `FAILED` сразу, без повтора, независимо от политики. В `job.error` SHALL всегда лежать последняя ошибка в формате `"ИмяКласса: сообщение"`, а при успешном выполнении `error` SHALL быть `None`. `attempts` не сбрасывается при повторах.

#### Scenario: Повтор запланирован
- **WHEN** политика `max_attempts=3, base_delay=1, factor=2`, время 12:00:00, обработчик упал на первой попытке с `TimeoutError`
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равен 12:00:01, `error` начинается с `"TimeoutError"`, `jobs.retried` равен 1

#### Scenario: Попытки исчерпаны
- **WHEN** обработчик упал с повторяемой ошибкой на третьей попытке при `max_attempts=3`
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` есть запись с `attempts=3` и последней ошибкой

#### Scenario: max_attempts равен 1
- **WHEN** `max_attempts=1` и обработчик упал с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, не `FAILED`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик бросил `PermanentJobError` (или класс из `non_retryable`) на последней попытке
- **THEN** статус `FAILED`, записи в dead-letter нет

#### Scenario: Нет обработчика для типа
- **WHEN** для типа задания не зарегистрирован обработчик, а политика есть
- **THEN** задание сразу `FAILED`, повтор не планируется

#### Scenario: Успех после повтора
- **WHEN** задание в `RETRY_SCHEDULED` при следующем запуске выполнилось успешно
- **THEN** статус `SUCCEEDED` и `error` равен `None`

### Requirement: Генератор случайных чисел воркера
`Worker` SHALL принимать keyword-only параметр `rng` (`random.Random | None`) и использовать его только при планировании повтора: задержка не рассчитывается и `rng` не трогается при уходе в `FAILED` или `DEAD_LETTERED`. При `jitter == 0` `rng` не вызывается и при планировании повтора.

#### Scenario: rng не трогается без повтора
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED` при `jitter > 0`
- **THEN** `rng.uniform` не вызывался

#### Scenario: Один вызов на один повтор
- **WHEN** планируется один повтор при `jitter > 0`
- **THEN** `rng.uniform` вызван ровно один раз

### Requirement: Выполнение запланированных повторов
Воркер SHALL брать задание в `RETRY_SCHEDULED`, когда `run_at <= now`, так же, как `PENDING`: упорядочение по `run_at`, затем по порядку постановки. Каждый запуск SHALL увеличивать `attempts` и счётчик `jobs.started`. Задание с `run_at` в будущем SHALL NOT выбираться.

#### Scenario: Повтор ещё рано
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at` через 4 секунды, время не продвинуто
- **THEN** `run_once()` возвращает `None`

#### Scenario: Повтор наступил
- **WHEN** часы продвинуты до `run_at`
- **THEN** `run_once()` запускает обработчик, `attempts` увеличен на 1

### Requirement: Dead-letter очередь
`dead_letters()` SHALL возвращать список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` в порядке попадания в dead-letter; изменение возвращённого списка не влияет на очередь. `dead_lettered_at` — время очереди в момент перехода. `purge_finished` SHALL NOT удалять задания `DEAD_LETTERED`: они остаются до `requeue_dead_letter`.

#### Scenario: Порядок записей
- **WHEN** сначала в dead-letter попало задание A, затем B
- **THEN** `dead_letters()` возвращает записи A, B

#### Scenario: purge_finished
- **WHEN** есть `DEAD_LETTERED` задание, вызван `purge_finished()`
- **THEN** задание остаётся в хранилище и в `dead_letters()`

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся) и возвращать его: статус `PENDING`, `run_at` равен текущему времени очереди, `error` равен `None`, `attempts` сброшен в 0 (иначе после первой же ошибки задание снова ушло бы в dead-letter), запись удалена из `dead_letters()`, `jobs.requeued` увеличен на 1. Для неизвестного идентификатора SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`, без побочных эффектов.

#### Scenario: Успешный requeue
- **WHEN** задание в dead-letter, вызван `requeue_dead_letter(job.id)`
- **THEN** тот же `Job` в статусе `PENDING`, `attempts == 0`, `error is None`, `dead_letters()` пуст, воркер подхватывает его сразу

#### Scenario: Задание не в dead-letter
- **WHEN** `requeue_dead_letter` вызван для `PENDING` или `FAILED` задания
- **THEN** `InvalidTransitionError`, счётчик `jobs.requeued` не меняется

#### Scenario: Неизвестное задание
- **WHEN** `requeue_dead_letter("job-999999")`
- **THEN** `JobNotFoundError`

### Requirement: Отмена и допустимые переходы
Задание в `RETRY_SCHEDULED` SHALL отменяться через `cancel` так же, как `PENDING` (статус `CANCELLED`, `finished_at` задан, `jobs.cancelled` +1). Для `DEAD_LETTERED` `cancel` SHALL вызывать `InvalidTransitionError`; единственный выход из dead-letter — `requeue_dead_letter`.

#### Scenario: Отмена ожидающего повтора
- **WHEN** `cancel` вызван для задания в `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`

#### Scenario: Отмена задания из dead-letter
- **WHEN** `cancel` вызван для `DEAD_LETTERED` задания
- **THEN** `InvalidTransitionError`, задание остаётся в dead-letter

### Requirement: Счётчики
Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` SHALL увеличиваться ровно в момент события: переход в `RETRY_SCHEDULED`, переход в `DEAD_LETTERED`, успешный возврат из dead-letter. `jobs.failed` SHALL увеличиваться только при переходе в `FAILED`. Отвергнутый вызов счётчики не меняет.

#### Scenario: Полный цикл
- **WHEN** задание дважды упало с повторяемой ошибкой при `max_attempts=2`, затем возвращено через requeue
- **THEN** `jobs.retried == 1`, `jobs.dead_lettered == 1`, `jobs.requeued == 1`, `jobs.failed == 0`

### Requirement: Отчёт для дежурных
Статус `RETRY_SCHEDULED` SHALL иметь подпись «Ожидает повтора», `DEAD_LETTERED` — «В dead-letter». `stats()` SHALL содержать ключи `retry_scheduled` и `dead_lettered`. Оба статуса SHALL NOT считаться завершёнными (`is_terminal` ложно). Отчёт `render_report` SHALL выводить эти статусы без изменения `dashboard.py`.

#### Scenario: Подписи в отчёте
- **WHEN** строится отчёт при наличии заданий в обоих статусах
- **THEN** в нём есть строки «Ожидает повтора» и «В dead-letter» с количеством заданий
