## Purpose

Описывает, как воркер реагирует на падение обработчика: выбор между `FAILED`, повтором и dead-letter, новые статусы, учёт времени, счётчики и подписи в отчёте.

## ADDED Requirements

### Requirement: Новые статусы
Система SHALL иметь статусы `RETRY_SCHEDULED` (`"retry_scheduled"`, подпись «Ожидает повтора») и `DEAD_LETTERED` (`"dead_lettered"`, подпись «В dead-letter»). `stats()` и текстовый отчёт дежурных SHALL содержать обе строки. `RETRY_SCHEDULED` не является терминальным; `DEAD_LETTERED` не принимается воркером и покидает состояние только через `requeue_dead_letter`.

#### Scenario: Статистика и отчёт
- **WHEN** запрашивается `stats()` и формируется отчёт
- **THEN** есть ключи `retry_scheduled` и `dead_lettered`, а в отчёте строки «Ожидает повтора» и «В dead-letter»

### Requirement: Решение при падении обработчика
Когда обработчик бросил исключение, воркер SHALL использовать политику, действующую в момент ошибки (не при постановке), и выбрать результат так:
1. политики нет → `FAILED` (поведение как до изменения);
2. ошибка неповторяема (`is_retryable` is `False`) → `FAILED`, даже на последней попытке, в dead-letter не попадает;
3. `job.attempts >= max_attempts` → `DEAD_LETTERED` и запись в `dead_letters()`;
4. иначе → `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`, где `now` — время очереди в момент ошибки.

`job.error` SHALL всегда содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. `max_attempts=1` означает «без повторов, но в dead-letter», а не `FAILED`. Отсутствие обработчика для типа задания — ошибка конфигурации: сразу `FAILED` независимо от политики.

#### Scenario: Временная ошибка
- **WHEN** действует политика `max_attempts=3`, обработчик падает на первой попытке с `TimeoutError`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == now + base_delay`, `error` начинается с `TimeoutError`

#### Scenario: Попытки исчерпаны
- **WHEN** обработчик падает на попытке номер `max_attempts`
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` появляется запись

#### Scenario: max_attempts=1
- **WHEN** политика с `max_attempts=1` и обработчик падает повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, повтор не планируется

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик на последней попытке бросает `PermanentJobError` или ошибку из `non_retryable`
- **THEN** статус `FAILED`, в dead-letter записи нет

#### Scenario: Нет обработчика
- **WHEN** для типа задания нет обработчика и политика задана
- **THEN** статус `FAILED`, повтор не планируется

#### Scenario: Политика изменилась после постановки
- **WHEN** политика типа меняется между постановкой и падением
- **THEN** применяется политика, действующая в момент падения

#### Scenario: Без политик
- **WHEN** политик нет и обработчик падает
- **THEN** статус `FAILED`, как раньше

### Requirement: Использование rng
Воркер SHALL принимать keyword-only `rng` и передавать его в `delay_for` только когда реально планируется повтор. Для заданий, уходящих в `FAILED` или `DEAD_LETTERED`, задержка SHALL NOT вычисляться и `rng` SHALL NOT использоваться. При `jitter == 0` `rng` не трогается.

#### Scenario: rng не используется без повтора
- **WHEN** задание уходит в `DEAD_LETTERED` или `FAILED` при `jitter > 0`
- **THEN** `rng` не вызывался

#### Scenario: Один вызов на повтор
- **WHEN** планируется повтор при `jitter > 0`
- **THEN** сделан ровно один вызов `rng.uniform`

### Requirement: Запуск повторов
Воркер SHALL брать задание в `RETRY_SCHEDULED`, когда `run_at <= now`, наравне с `PENDING` и в общем порядке `(run_at, порядок постановки)`; до наступления `run_at` задание не берётся. Каждый запуск увеличивает `attempts`. `RETRY_SCHEDULED`-задание можно отменить (`cancel`). Успешное выполнение после повторов SHALL приводить к `SUCCEEDED` с `error is None`. Задания `DEAD_LETTERED` SHALL NOT удаляться `purge_finished` и SHALL NOT отменяться.

#### Scenario: Повтор по расписанию
- **WHEN** задание в `RETRY_SCHEDULED` и часы не дошли до `run_at`, затем дошли
- **THEN** `run_once` сначала возвращает `None`, потом выполняет задание

#### Scenario: Успех после повтора
- **WHEN** вторая попытка успешна
- **THEN** статус `SUCCEEDED`, `error is None`, `attempts == 2`

#### Scenario: Отмена и purge
- **WHEN** отменяется `RETRY_SCHEDULED`-задание, и вызывается `purge_finished` при наличии `DEAD_LETTERED`-заданий
- **THEN** первое становится `CANCELLED`, dead-letter задания остаются в хранилище, `cancel` для них выбрасывает `InvalidTransitionError`

### Requirement: Счётчики
Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` SHALL увеличиваться ровно в момент соответствующего перехода: планирование повтора, попадание в dead-letter, возврат из dead-letter. `jobs.failed` SHALL увеличиваться только при переходе в `FAILED`, `jobs.started` — при каждом запуске.

#### Scenario: Счётчики прогона
- **WHEN** задание дважды повторено и затем попало в dead-letter (`max_attempts=3`)
- **THEN** `jobs.started == 3`, `jobs.retried == 2`, `jobs.dead_lettered == 1`, `jobs.failed == 0`
