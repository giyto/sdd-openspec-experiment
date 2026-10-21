# dead-letter-queue Specification

## Purpose
Описывает статусы ожидания повтора и dead-letter, хранение и возврат в работу заданий, не выполнившихся за все попытки, а также связанные счётчики и подписи отчёта.

## Requirements

### Requirement: Новые статусы и их свойства
`JobStatus` SHALL содержать `RETRY_SCHEDULED` со значением `"retry_scheduled"` и подписью «Ожидает повтора», а также `DEAD_LETTERED` со значением `"dead_lettered"` и подписью «В dead-letter». `JobQueue.stats()` SHALL включать оба статуса (с нулями при отсутствии заданий). Допустимые переходы: `RUNNING → RETRY_SCHEDULED | DEAD_LETTERED | FAILED`, `RETRY_SCHEDULED → RUNNING | CANCELLED`, `DEAD_LETTERED → PENDING` (только через `requeue_dead_letter`). Остальные переходы SHALL давать `InvalidTransitionError`. `RETRY_SCHEDULED` и `DEAD_LETTERED` SHALL NOT считаться завершёнными (`is_terminal` равно `False`).

#### Scenario: Подписи отчёта
- **WHEN** запрашиваются `JobStatus.RETRY_SCHEDULED.label` и `JobStatus.DEAD_LETTERED.label`
- **THEN** возвращаются «Ожидает повтора» и «В dead-letter», и они выводятся в отчёте дежурных

#### Scenario: Статистика
- **WHEN** вызывается `queue.stats()` на пустой очереди
- **THEN** ключи `"retry_scheduled"` и `"dead_lettered"` присутствуют со значением 0

### Requirement: Просмотр dead-letter
`JobQueue.dead_letters()` SHALL возвращать список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` в порядке попадания в dead-letter. `attempts` и `error` SHALL фиксировать значения на момент попадания, `dead_lettered_at` — время часов очереди. Возвращается копия: изменение списка не влияет на очередь.

#### Scenario: Порядок записей
- **WHEN** задание B попадает в dead-letter раньше задания A (A поставлено раньше)
- **THEN** `dead_letters()` возвращает сначала запись B, затем A

#### Scenario: Содержимое записи
- **WHEN** задание типа `send_email` исчерпало 3 попытки, последняя ошибка `TimeoutError: gateway`
- **THEN** запись содержит `job_type="send_email"`, `attempts=3`, `error="TimeoutError: gateway"`, `dead_lettered_at` = текущее время часов

### Requirement: Возврат из dead-letter
`JobQueue.requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` = текущее время часов, `error = None`, `attempts = 0`; запись SHALL удаляться из `dead_letters()`. Метод SHALL возвращать это `Job`. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`. Единственный выход из dead-letter — `requeue_dead_letter`, в частности `cancel` для такого задания недопустим. Число прежних попыток остаётся только в логах.

#### Scenario: Успешный возврат
- **WHEN** задание в dead-letter и вызывается `requeue_dead_letter(id)`
- **THEN** возвращается тот же объект задания со статусом `PENDING`, `run_at == now`, `error is None`, `attempts == 0`, записи в `dead_letters()` нет, общее число заданий в хранилище не изменилось

#### Scenario: Перезапущенное задание получает полный набор попыток
- **WHEN** задание возвращено и снова падает на первой попытке при `max_attempts=3`
- **THEN** оно получает `RETRY_SCHEDULED`, а не `DEAD_LETTERED`

#### Scenario: Возврат задания не из dead-letter
- **WHEN** вызывается `requeue_dead_letter` для задания в `PENDING`
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: Неизвестное задание
- **WHEN** вызывается `requeue_dead_letter("job-999999")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Отмена из dead-letter
- **WHEN** вызывается `cancel` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`, запись остаётся

### Requirement: Отмена ожидающего повтора и purge
Задание в `RETRY_SCHEDULED` SHALL отменяться через `cancel` так же, как ожидающее (`CANCELLED`, `finished_at` выставлен, `jobs.cancelled` +1). `purge_finished` SHALL NOT удалять задания в `RETRY_SCHEDULED` и `DEAD_LETTERED`; они остаются до выполнения, отмены или `requeue_dead_letter`.

#### Scenario: Отмена задания, ждущего повтора
- **WHEN** задание в `RETRY_SCHEDULED` и вызывается `cancel(id)`
- **THEN** статус `CANCELLED` и воркер его больше не берёт

#### Scenario: purge не трогает dead-letter
- **WHEN** есть задание в `DEAD_LETTERED` и вызывается `purge_finished()` (в том числе с `older_than=0`)
- **THEN** оно остаётся в хранилище и в `dead_letters()`

### Requirement: Счётчики
`Metrics` SHALL получить счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`. Каждый SHALL увеличиваться ровно в момент соответствующего события: переход в `RETRY_SCHEDULED`, переход в `DEAD_LETTERED`, успешный `requeue_dead_letter`. Эти события SHALL NOT увеличивать `jobs.failed` и `jobs.enqueued`. Отклонённая операция счётчики не меняет. Запуск повтора увеличивает существующий `jobs.started`.

#### Scenario: Цепочка с dead-letter
- **WHEN** при `max_attempts=2` обработчик падает дважды, затем задание возвращается
- **THEN** `jobs.started == 2`, `jobs.retried == 1`, `jobs.dead_lettered == 1`, `jobs.requeued == 1`, `jobs.failed == 0`

#### Scenario: Отклонённый возврат
- **WHEN** `requeue_dead_letter` завершается `InvalidTransitionError`
- **THEN** `jobs.requeued` не изменился

### Requirement: Готовность заданий и обратная совместимость
Задание в `RETRY_SCHEDULED` SHALL считаться готовым к запуску при `run_at <= now` и упорядочиваться вместе с `PENDING` по `(run_at, порядок постановки)`. Существующие вызовы `JobQueue(...)`, `Worker(...)`, `enqueue`, `cancel`, `purge_finished` и поведение без заданной политики SHALL оставаться прежними.

#### Scenario: Общий порядок готовых заданий
- **WHEN** готовы `PENDING` с более поздним `run_at` и `RETRY_SCHEDULED` с более ранним
- **THEN** `next_due()` возвращает `RETRY_SCHEDULED`

#### Scenario: Старые вызовы
- **WHEN** очередь и воркер создаются без новых параметров
- **THEN** любое исключение обработчика приводит к `FAILED`, как до изменения
