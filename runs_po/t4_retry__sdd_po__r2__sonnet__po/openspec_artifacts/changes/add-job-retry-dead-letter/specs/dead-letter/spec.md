## Purpose

Описывает журнал dead-letter для заданий, исчерпавших попытки, и осознанный возврат таких заданий в работу.

## ADDED Requirements

### Requirement: Журнал dead-letter
`dead_letters()` SHALL возвращать список записей `DeadLetterEntry` (`job_id`, `job_type`, `attempts`, `error`, `dead_lettered_at`) в порядке попадания в dead-letter. Запись создаётся при переходе задания в `DEAD_LETTERED`; `attempts` и `error` берутся из задания на этот момент, `dead_lettered_at` — из часов очереди. Запись неизменяема. Возвращаемый список MUST быть копией: его изменение не влияет на очередь.

#### Scenario: Порядок записей
- **WHEN** сначала в dead-letter попало задание A, потом B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Содержимое записи
- **WHEN** задание типа `send_email` ушло в dead-letter после 3 попыток с `TimeoutError: gw`
- **THEN** запись имеет `job_type="send_email"`, `attempts=3`, `error="TimeoutError: gw"` и время падения

#### Scenario: Пустой журнал
- **WHEN** в dead-letter ничего не попадало
- **THEN** `dead_letters()` возвращает пустой список

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` = текущее время очереди, `attempts=0`, `error=None`, `finished_at=None`; запись удаляется из `dead_letters()`; `jobs.requeued` увеличивается на 1; метод возвращает это задание. `payload` SHALL сохраняться, а счётчик `attempts` SHALL сбрасываться в 0: вернувшееся задание получает полный набор попыток, как новое (решение продукта; прежнее число попыток видно в логах). Это единственный выход из `DEAD_LETTERED`: отмена и любые другие переходы MUST приводить к `InvalidTransitionError`. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`; в обоих случаях состояние и счётчики не меняются.

#### Scenario: Успешный возврат
- **WHEN** вызван `requeue_dead_letter` для задания из dead-letter
- **THEN** возвращён тот же объект с тем же `id`, статус `PENDING`, `run_at` = now, `attempts=0`, `error=None`, записи в журнале нет, `jobs.requeued=1`

#### Scenario: Воркер выполняет вернувшееся задание
- **WHEN** задание возвращено и воркер запущен
- **THEN** оно берётся как обычное готовое задание

#### Scenario: Полный набор попыток после возврата
- **WHEN** задание возвращено и его первый запуск упал с повторяемой ошибкой (`max_attempts>1`)
- **THEN** оно уходит в `RETRY_SCHEDULED`, а не в dead-letter

#### Scenario: Повторное попадание в dead-letter
- **WHEN** вернувшееся задание снова исчерпало все `max_attempts` попыток
- **THEN** в конец журнала добавляется новая запись

#### Scenario: Неизвестное задание
- **WHEN** `job_id` не существует
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Задание не в dead-letter
- **WHEN** вызывается для задания в `PENDING` или `FAILED`
- **THEN** выбрасывается `InvalidTransitionError`, `jobs.requeued` не меняется

#### Scenario: Отмена из dead-letter запрещена
- **WHEN** вызывается `cancel` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`, запись остаётся
