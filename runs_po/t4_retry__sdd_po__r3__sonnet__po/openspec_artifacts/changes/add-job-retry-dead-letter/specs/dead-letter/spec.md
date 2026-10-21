## Purpose

Хранение заданий, исчерпавших попытки, в отдельном списке и осознанный возврат их в работу оператором.

## ADDED Requirements

### Requirement: Запись в dead-letter
При переходе задания в `DEAD_LETTERED` очередь SHALL добавить `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`, где `attempts` — число попыток задания на момент попадания, `error` — последняя ошибка, `dead_lettered_at` — время по часам очереди. `dead_letters()` SHALL возвращать копию списка записей в порядке попадания. Счётчик `jobs.dead_lettered` SHALL увеличиваться ровно в момент перехода, `jobs.failed` при этом не меняется.

#### Scenario: Порядок записей
- **WHEN** в dead-letter попали задания A, затем B
- **THEN** `dead_letters()` возвращает записи A, B

#### Scenario: Содержимое записи
- **WHEN** задание исчерпало 3 попытки с ошибкой `RuntimeError: boom`
- **THEN** запись содержит его id, тип, `attempts=3`, `error="RuntimeError: boom"` и текущее время

#### Scenario: Изменение возвращённого списка
- **WHEN** вызывающий код меняет список, полученный из `dead_letters()`
- **THEN** внутренний список очереди не меняется

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL вернуть в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` равен текущему времени, `error` очищен (`None`), `attempts` обнулён (у задания снова полный набор попыток, как у нового), запись удалена из `dead_letters()`; `payload` и `id` сохраняются. Метод SHALL возвращать задание и увеличивать `jobs.requeued` на 1. Для неизвестного id SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`, при этом состояние не меняется. Других выходов из `DEAD_LETTERED` (отмена, запуск, повторный перевод) не существует.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter` для задания в dead-letter
- **THEN** то же задание в `PENDING`, `run_at` равен now, `error` пуст, `attempts=0`, `dead_letters()` не содержит записи, `jobs.requeued` вырос на 1

#### Scenario: Полный набор попыток после возврата
- **WHEN** возвращённое задание снова падает повторяемой ошибкой при `max_attempts=3`
- **THEN** оно получает повторы (`RETRY_SCHEDULED`) и попадает в dead-letter только после 3 новых попыток

#### Scenario: Задание не в dead-letter
- **WHEN** вызывается `requeue_dead_letter` для задания в `FAILED`
- **THEN** выбрасывается `InvalidTransitionError`, счётчик `jobs.requeued` не меняется

#### Scenario: Неизвестный id
- **WHEN** вызывается `requeue_dead_letter("nope")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Отмена задания в dead-letter
- **WHEN** вызывается `cancel` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`

### Requirement: Сохранность заданий dead-letter
`purge_finished` SHALL NOT удалять задания в `DEAD_LETTERED`, чтобы запись всегда указывала на существующее задание.

#### Scenario: Очистка завершённых
- **WHEN** вызывается `purge_finished()` при наличии задания в dead-letter
- **THEN** задание и его запись остаются

### Requirement: Счётчики
Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` SHALL работать по правилам существующих: увеличиваются ровно в момент соответствующего перехода (в `RETRY_SCHEDULED`, в `DEAD_LETTERED`, возврат из dead-letter), неизвестный читается как 0, ненулевые попадают в `snapshot()`.

#### Scenario: Счётчики после цикла
- **WHEN** задание дважды ушло на повтор, затем в dead-letter, затем возвращено
- **THEN** `jobs.retried=2`, `jobs.dead_lettered=1`, `jobs.requeued=1`
