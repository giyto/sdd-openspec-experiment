## Purpose

Описывает, как очередь и воркер повторяют упавшие задания по политике, переводят исчерпавшие попытки задания в dead-letter и позволяют вернуть их в работу.

## ADDED Requirements

### Requirement: Выбор действующей политики
`JobQueue` SHALL принимать keyword-only параметр `default_retry_policy: RetryPolicy | None = None`. `set_retry_policy(job_type, policy)` SHALL задавать политику типа, `None` — снимать её. `retry_policy_for(job_type)` SHALL возвращать политику типа, а если её нет — политику по умолчанию, а если нет и её — `None`. Политика типа SHALL заменять дефолт целиком, поля не сливаются. Политика SHALL определяться в момент ошибки, а не в момент постановки. Значение, не являющееся `RetryPolicy` или `None`, и пустой `job_type` SHALL давать `ConfigError`.

#### Scenario: Приоритет типа над дефолтом
- **WHEN** задан дефолт `RetryPolicy(non_retryable=(ValueError,))` и для типа `a` политика `RetryPolicy(max_attempts=5)`
- **THEN** `retry_policy_for("a")` возвращает политику типа с пустым `non_retryable`, а для других типов — дефолт

#### Scenario: Снятие политики типа
- **WHEN** вызывается `set_retry_policy("a", None)` после установки политики
- **THEN** `retry_policy_for("a")` возвращает дефолт, либо `None`, если дефолта нет

#### Scenario: Политика берётся в момент ошибки
- **WHEN** политика типа меняется после `enqueue`, но до падения обработчика
- **THEN** используется политика, действующая в момент падения

### Requirement: Исход падения обработчика
Когда обработчик бросает исключение, воркер SHALL перевести задание так: (1) если политики нет — в `FAILED` (прежнее поведение); (2) иначе, если ошибка неповторяемая (`is_retryable` вернул `False`) — в `FAILED`, в том числе на последней попытке, и в dead-letter такое задание не попадает; (3) иначе, если `job.attempts >= max_attempts` — в `DEAD_LETTERED` с записью в `dead_letters()`; (4) иначе — в `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`, где `now` берётся из часов очереди. Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. `max_attempts == 1` означает «без повторов, но в dead-letter», а не `FAILED`. Если для типа нет обработчика, задание SHALL сразу переходить в `FAILED` без повторов, независимо от политики.

#### Scenario: Без политики
- **WHEN** политики нет и обработчик бросил исключение
- **THEN** статус `FAILED`, `jobs.failed` увеличен на 1

#### Scenario: Планирование повтора
- **WHEN** действует `RetryPolicy(max_attempts=3, base_delay=1, factor=2)`, обработчик упал на первой попытке в момент `T`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 1s`, `error` содержит ошибку, `jobs.retried == 1`

#### Scenario: Исчерпание попыток
- **WHEN** `max_attempts=3` и обработчик упал на третьей попытке
- **THEN** статус `DEAD_LETTERED`, `dead_letters()` содержит запись с `attempts == 3` и последней ошибкой, `jobs.dead_lettered == 1`, `jobs.failed` не изменён

#### Scenario: max_attempts равно 1
- **WHEN** `max_attempts=1` и обработчик упал
- **THEN** статус `DEAD_LETTERED`, а не `FAILED` и не `RETRY_SCHEDULED`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** обработчик бросил `PermanentJobError`, либо ошибку из `non_retryable` (в том числе наследника), на последней попытке
- **THEN** статус `FAILED`, записи в dead-letter нет

#### Scenario: Нет обработчика
- **WHEN** для типа задания не зарегистрирован обработчик, а политика есть
- **THEN** статус `FAILED`, повтор не планируется

#### Scenario: Повтор исполняется
- **WHEN** задание в `RETRY_SCHEDULED`, время `run_at` ещё не наступило
- **THEN** воркер его не берёт; после наступления `run_at` берёт как любое готовое задание, с сортировкой по `(run_at, seq)`

### Requirement: Использование rng воркером
`Worker` SHALL принимать keyword-only параметр `rng: random.Random | None = None` и передавать его в `delay_for`. Воркер SHALL обращаться к `rng` только когда реально планируется повтор (и только при `jitter > 0`): при исходах `FAILED` и `DEAD_LETTERED` задержка не вычисляется. Один повтор с джиттером — ровно один вызов `rng.uniform`.

#### Scenario: Исходы без повтора не трогают rng
- **WHEN** задание уходит в `FAILED` или `DEAD_LETTERED`
- **THEN** вызовов `rng.uniform` не было

#### Scenario: Один вызов на повтор
- **WHEN** планируется повтор при `jitter > 0`
- **THEN** выполнен ровно один вызов `rng.uniform`

### Requirement: Dead-letter очередь
`dead_letters()` SHALL возвращать новый список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` в порядке попадания; `dead_lettered_at` берётся из часов очереди. `requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` равен текущему времени, `error = None`, `attempts = 0`, запись из dead-letter удаляется, `jobs.requeued` увеличивается на 1. Для неизвестного id SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`. `purge_finished` SHALL NOT удалять задания в `DEAD_LETTERED`.

#### Scenario: Порядок записей
- **WHEN** сначала в dead-letter попало задание A, затем B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Возврат в работу
- **WHEN** вызывается `requeue_dead_letter(id)` для задания с `attempts == 3`
- **THEN** возвращается тот же объект `Job` со статусом `PENDING`, `attempts == 0`, `error is None`, `run_at == now`; `dead_letters()` его не содержит; после первой же новой ошибки (при `max_attempts > 1`) задание не уходит снова в dead-letter

#### Scenario: Requeue не из dead-letter
- **WHEN** `requeue_dead_letter` вызывается для `FAILED` или `PENDING` задания
- **THEN** выбрасывается `InvalidTransitionError`, состояние не меняется

#### Scenario: Purge не трогает dead-letter
- **WHEN** выполняется `purge_finished(0)` при наличии заданий `DEAD_LETTERED`
- **THEN** они остаются в хранилище и в `dead_letters()`, а `FAILED`, `SUCCEEDED`, `CANCELLED` удаляются как раньше

### Requirement: Отмена и допустимые переходы
Задание в `RETRY_SCHEDULED` SHALL отменяться через `cancel` так же, как `PENDING` (статус `CANCELLED`, `jobs.cancelled`). Задание в `DEAD_LETTERED` SHALL NOT отменяться (`InvalidTransitionError`); единственный выход — `requeue_dead_letter`. `DEAD_LETTERED` и `RETRY_SCHEDULED` SHALL NOT считаться завершёнными (`is_terminal` ложно).

#### Scenario: Отмена ожидающего повтора
- **WHEN** `cancel` вызывается для `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`

#### Scenario: Отмена dead-letter
- **WHEN** `cancel` вызывается для `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`

### Requirement: Счётчики
Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` SHALL увеличиваться ровно в момент перехода в `RETRY_SCHEDULED`, перехода в `DEAD_LETTERED` и успешного `requeue_dead_letter` соответственно, как существующие счётчики. Неизвестный счётчик читается как 0. `jobs.started` SHALL расти на каждый запуск, включая повторы.

#### Scenario: Полный цикл
- **WHEN** задание дважды падает с `max_attempts=2`, затем возвращается через requeue
- **THEN** `jobs.started == 2`, `jobs.retried == 1`, `jobs.dead_lettered == 1`, `jobs.requeued == 1`

### Requirement: Статусы в отчётах и stats
`JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`) SHALL иметь подпись «Ожидает повтора», `JobStatus.DEAD_LETTERED` (`"dead_lettered"`) — «В dead-letter». `stats()` SHALL включать оба новых статуса. Существующие значения и подписи статусов не меняются.

#### Scenario: Отчёт дежурных
- **WHEN** строится отчёт `render_report` при наличии заданий в новых статусах
- **THEN** он содержит строки «Ожидает повтора» и «В dead-letter» с количеством, без изменений в `dashboard.py`

### Requirement: Обратная совместимость
Существующие публичные сигнатуры SHALL остаться совместимыми: новые параметры только keyword-only со значениями по умолчанию, существующие тесты проходят без изменений.

#### Scenario: Старые вызовы
- **WHEN** `JobQueue()` и `Worker(queue, registry)` вызываются без новых параметров
- **THEN** поведение прежнее: любое исключение обработчика даёт `FAILED`
