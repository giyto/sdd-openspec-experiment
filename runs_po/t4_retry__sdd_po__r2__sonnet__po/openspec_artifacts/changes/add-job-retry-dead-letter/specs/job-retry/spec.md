## Purpose

Описывает, как воркер реагирует на падение обработчика: повтор с задержкой, окончательная ошибка или dead-letter, а также связанные статусы, счётчики и подписи в отчёте.

## ADDED Requirements

### Requirement: Новые статусы
Система SHALL иметь статусы `RETRY_SCHEDULED` (значение `retry_scheduled`, подпись «Ожидает повтора») и `DEAD_LETTERED` (значение `dead_lettered`, подпись «В dead-letter»). `stats()` MUST содержать оба ключа, текстовый отчёт дежурных MUST показывать обе подписи. `RETRY_SCHEDULED` MUST NOT быть терминальным; `DEAD_LETTERED` MUST считаться терминальным для воркера (сам он такое задание не берёт).

#### Scenario: Подписи в отчёте
- **WHEN** формируется отчёт дежурных
- **THEN** в нём есть строки «Ожидает повтора» и «В dead-letter» с количеством заданий

#### Scenario: Ключи в stats
- **WHEN** вызывается `stats()`
- **THEN** есть ключи `retry_scheduled` и `dead_lettered`

### Requirement: Решение воркера при падении обработчика
Когда обработчик выбросил исключение (`Exception`), воркер SHALL действовать по политике, действующей в этот момент (`retry_policy_for(тип)`), в таком порядке:
1. политики нет — `FAILED` (как раньше);
2. ошибка неповторяемая (`is_retryable` вернул `False`) — `FAILED`, даже на последней попытке, в dead-letter не попадает;
3. `job.attempts >= max_attempts` — `DEAD_LETTERED` и запись в журнале dead-letter;
4. иначе — `RETRY_SCHEDULED`, `run_at` = текущее время очереди + `delay_for(job.attempts, rng)`.

Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. `max_attempts=1` означает «без повторов, но в dead-letter»: первая повторяемая ошибка даёт `DEAD_LETTERED`. Генератор `rng` MUST использоваться только при реальном планировании повтора (шаг 4) и не более одного обращения на задержку; в `FAILED` и `DEAD_LETTERED` задержка не считается.

#### Scenario: Временная ошибка планирует повтор
- **WHEN** политика `max_attempts=3, base_delay=1, factor=2, jitter=0`, первая попытка упала с `TimeoutError`
- **THEN** статус `RETRY_SCHEDULED`, `run_at` = now + 1 с, `error` = `"TimeoutError: ..."`, `attempts=1`

#### Scenario: Вторая неудача удлиняет задержку
- **WHEN** повтор тоже упал (`attempts=2`)
- **THEN** `run_at` = now + 2 с

#### Scenario: Попытки исчерпаны
- **WHEN** упала попытка номер `max_attempts` с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` появилась запись, `error` — последняя ошибка

#### Scenario: max_attempts=1
- **WHEN** `max_attempts=1` и обработчик упал с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, повтор не планируется

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** `non_retryable=(ValueError,)`, обработчик на последней попытке бросил наследника `ValueError`
- **THEN** статус `FAILED`, записи в dead-letter нет

#### Scenario: PermanentJobError
- **WHEN** обработчик бросил `PermanentJobError` при действующей политике
- **THEN** статус `FAILED` без повторов

#### Scenario: Нет политики
- **WHEN** ни дефолта, ни политики типа нет и обработчик упал
- **THEN** статус `FAILED`, как до изменения

#### Scenario: Нет обработчика для типа
- **WHEN** для типа задания нет обработчика, даже при действующей политике
- **THEN** сразу `FAILED` с `UnknownJobTypeError`, без повторов и dead-letter

#### Scenario: rng трогаем только при повторе
- **WHEN** `jitter > 0`, задание уходит в `FAILED` или `DEAD_LETTERED`
- **THEN** `rng` не вызывается; при уходе в `RETRY_SCHEDULED` вызывается `uniform` ровно один раз

### Requirement: Повторный запуск запланированного задания
Воркер SHALL брать задание в `RETRY_SCHEDULED` тогда, когда наступил его `run_at`, наравне с `PENDING` и в общем порядке `(run_at, порядок постановки)`. До `run_at` такое задание MUST NOT выбираться. `attempts` увеличивается при каждом запуске, как и раньше. Успешный повтор SHALL давать `SUCCEEDED` с `error=None`. Отмена `RETRY_SCHEDULED`-задания SHALL быть допустима (оно ещё не выполняется) и MUST NOT создавать запись в dead-letter.

#### Scenario: Раньше срока не берётся
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at` в будущем
- **THEN** `run_once()` возвращает `None`, если других готовых нет

#### Scenario: Взято в срок
- **WHEN** часы дошли до `run_at`
- **THEN** воркер запускает обработчик, `attempts` растёт на 1

#### Scenario: Успех после повтора
- **WHEN** повторная попытка успешна
- **THEN** статус `SUCCEEDED`, `error` равен `None`

### Requirement: Счётчики
Новые счётчики SHALL увеличиваться ровно в момент соответствующего перехода: `jobs.retried` — при переходе в `RETRY_SCHEDULED`, `jobs.dead_lettered` — при переходе в `DEAD_LETTERED`, `jobs.requeued` — при возврате из dead-letter. Задание в `FAILED` увеличивает только `jobs.failed`. Неизвестный счётчик по-прежнему читается как 0.

#### Scenario: Счётчики одного пути
- **WHEN** задание дважды ушло на повтор и затем в dead-letter
- **THEN** `jobs.retried=2`, `jobs.dead_lettered=1`, `jobs.failed=0`, `jobs.started=3`

### Requirement: Обратная совместимость
Существующие публичные вызовы без новых параметров SHALL работать как раньше; новые параметры конструкторов и методов MUST быть keyword-only. `purge_finished` MUST NOT удалять задания в `DEAD_LETTERED`.

#### Scenario: Старый вызов
- **WHEN** создаются `JobQueue()` и `Worker(queue, registry)` без новых аргументов
- **THEN** любая ошибка обработчика даёт `FAILED`

#### Scenario: Очистка не трогает dead-letter
- **WHEN** вызывается `purge_finished()`, а в dead-letter есть задание
- **THEN** оно остаётся в хранилище и в `dead_letters()`
