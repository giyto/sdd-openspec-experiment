### design.md

## Context

Все изменения статуса идут через `JobQueue._transition` по таблице `_TRANSITIONS`; `InMemoryJobStore.due()` выбирает только `PENDING`; отчёт дежурных (`dashboard.py`, не трогаем) перебирает `JobStatus` и берёт `label`, поэтому новые статусы с подписями в модели попадут в него сами. Мотивация — в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:** политика повторов с защитой от переполнения; детерминированный `rng`; все переходы и счётчики через очередь.

**Non-Goals:** персистентность dead-letter, управление повторами из CLI/dashboard, слияние политик по полям, сброс `attempts` при requeue.

## Decisions

- **`RetryPolicy` валидируется в `__post_init__`**, `non_retryable` приводится к tuple через `object.__setattr__` (frozen). Проверки пишутся как «не (допустимо)», чтобы NaN отклонялся с `ConfigError`.
- **`delay_for` без OverflowError:** при `base_delay == 0` → `0.0`; при `factor == 1` → `min(base, max)`; иначе `factor ** (attempt-1)` в `try/except OverflowError` (и проверка на `inf`) → `max_delay`; результат `min(..., max_delay)`. Альтернатива — логарифмы: сложнее и менее точно. Jitter: `rng.uniform(1-j, 1+j)` ровно один раз и только при `jitter > 0`; `rng=None` → модульный `random`. Результат с jitter может превышать `max_delay` — так сказано в задаче.
- **Порядок проверок в воркере:** нет обработчика → `FAILED` до любой политики; затем политика через `queue.retry_policy_for` на момент ошибки; нет политики → `FAILED`; `not is_retryable` → `FAILED`; `attempts >= max_attempts` → dead-letter; иначе retry. `delay_for` вызывается только в последней ветке (требование к `rng`).
- **Новые методы очереди** `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` рядом с `mark_failed`; воркер считает `run_at` по `queue.clock.now()`. Счётчики инкрементируются внутри них, `jobs.requeued` — в `requeue_dead_letter`. Переходы: `RUNNING → RETRY_SCHEDULED/DEAD_LETTERED`, `RETRY_SCHEDULED → RUNNING/CANCELLED`, `DEAD_LETTERED → PENDING` (только requeue, тоже через `_transition`).
- **Dead-letter — список `DeadLetterEntry` в `JobQueue`** (в памяти, как и хранилище); `dead_letters()` отдаёт копию. `requeue` сначала получает задание (`JobNotFoundError`), проверяет статус через `_transition`, затем удаляет запись по `job_id`.
- **`store.due()`** учитывает `PENDING` и `RETRY_SCHEDULED`; порядок `(run_at, seq)` прежний.
- **`is_terminal`:** новые статусы не терминальны, чтобы `purge_finished` не оставлял висячих записей dead-letter. `finished_at` в этих статусах не выставляется.
- **Подписи** — в `_LABELS`; константы счётчиков — в `metrics.py`, докстринг модуля дополняется.

## Risks / Trade-offs

- `is_terminal=False` для `DEAD_LETTERED` меняет смысл «больше не будет выполняться воркером» → уточнить докстринг: ждёт ручного решения.
- `attempts` не сбрасывается при requeue, поэтому первая же ошибка вернёт задание в dead-letter → буквальное чтение задачи, зафиксировано в допущениях proposal.md.
- Существующие тесты могут зависеть от набора статусов в `stats()`/отчёте → прогнать весь набор тестов.
- Большие `attempt` во float → явная ветка переполнения и тесты на 5000/10000.


### proposal.md

## Why

Любое исключение в обработчике сразу переводит задание в `FAILED`, и дежурные каждое утро вручную перезапускают десятки заданий, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py` с `RetryPolicy` (frozen dataclass): `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`; методы `delay_for(attempt, rng=None) -> float` и `is_retryable(exc) -> bool`. Некорректные параметры — `ConfigError`.
- `jobq/errors.py`: `PermanentJobError(JobqError)` — обработчик бросает её, когда повтор точно не поможет.
- `jobq/models.py`: `JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`), `JobStatus.DEAD_LETTERED` (`"dead_lettered"`) с подписями «Ожидает повтора» и «В dead-letter»; `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`.
- `jobq/queue.py`: `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy: RetryPolicy | None = None)`, `set_retry_policy(job_type, policy | None)`, `retry_policy_for(job_type)`, `dead_letters()`, `requeue_dead_letter(job_id) -> Job`.
- `jobq/worker.py`: `Worker(queue, registry, *, name="worker", rng: random.Random | None = None)`; при падении обработчика воркер выбирает между `FAILED`, `RETRY_SCHEDULED` и `DEAD_LETTERED`.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Без политики (ни дефолтной, ни для типа) поведение не меняется: любое падение — `FAILED`.
- Сигнатуры существующих публичных методов не меняются; новые параметры только keyword-only. Ничего **BREAKING**.

## Capabilities

### New Capabilities
- `retry-policy`: параметры, валидация, расчёт задержки (`delay_for`) и классификация ошибок (`is_retryable`) политики повторов, а также `PermanentJobError`.
- `job-retries`: выбор политики (по умолчанию для очереди / для типа), переходы статусов при падении обработчика, планирование повтора, выборка заданий `RETRY_SCHEDULED`, счётчик `jobs.retried`, подписи статусов в отчёте.
- `dead-letter`: dead-letter очередь (`dead_letters()`, `DeadLetterEntry`), возврат в работу через `requeue_dead_letter`, счётчики `jobs.dead_lettered`, `jobs.requeued`.

### Modified Capabilities
<!-- В openspec/specs пока нет спецификаций; существующее поведение без политики не меняется. -->

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/queue.py`, `jobq/worker.py`, `jobq/metrics.py`, `jobq/store.py` (выборка готовых заданий включает `RETRY_SCHEDULED`), `jobq/__init__.py` (экспорт).
- Не трогаем `jobq/dashboard.py` и `jobq/cli.py` (владелец — другая команда): отчёт перебирает `JobStatus` и берёт подписи из модели, поэтому новые статусы появятся в нём без правок.
- Зависимости не добавляются; существующие тесты не меняются.

## Assumptions

- `DEAD_LETTERED` и `RETRY_SCHEDULED` не считаются терминальными (`is_terminal` = False): из dead-letter есть выход через `requeue_dead_letter`, поэтому `purge_finished` их не удаляет.
- `cancel` разрешён для `RETRY_SCHEDULED` (задание не выполняется) и запрещён для `DEAD_LETTERED`.
- `requeue_dead_letter` меняет только перечисленные в задаче поля; `attempts` не сбрасывается.
- Переход в `DEAD_LETTERED` не увеличивает `jobs.failed` (счётчик растёт только при переходе в свой статус).


### specs/dead-letter/spec.md

## Purpose

Описывает dead-letter очередь: учёт заданий, исчерпавших попытки, и осознанный возврат их в работу.

## ADDED Requirements

### Requirement: Запись в dead-letter
При переходе задания в `DEAD_LETTERED` очередь SHALL добавить в конец списка `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` (frozen dataclass в `jobq/models.py`), где `attempts` и `error` взяты у задания, а `dead_lettered_at` — время часов очереди. `dead_letters()` MUST возвращать новый список записей в порядке попадания; изменение этого списка не влияет на очередь. Счётчик `jobs.dead_lettered` увеличивается на 1 при каждом таком переходе.

#### Scenario: Содержимое записи
- **WHEN** задание `job-000001` типа `"mail"` исчерпало 3 попытки с последней ошибкой `TimeoutError: gw`
- **THEN** `dead_letters()` содержит запись с `job_id == "job-000001"`, `job_type == "mail"`, `attempts == 3`, `error == "TimeoutError: gw"` и `dead_lettered_at`, равным текущему времени очереди

#### Scenario: Порядок
- **WHEN** в dead-letter попадают сначала задание A, затем B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Список — копия
- **WHEN** вызывающий код очищает возвращённый `dead_letters()` список
- **THEN** следующий вызов `dead_letters()` по-прежнему возвращает все записи

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL вернуть в работу то же задание (новое не создаётся) и вернуть его: статус `PENDING`, `run_at` = текущее время часов очереди, `error = None`; запись удаляется из dead-letter, `jobs.requeued` увеличивается на 1. Прочие поля (`id`, `payload`, `attempts`, `created_at`) не меняются. Это единственный выход из `DEAD_LETTERED`: `cancel` и `purge_finished` не должны затрагивать такие задания. Если задание не найдено — `JobNotFoundError`; если оно не в `DEAD_LETTERED` — `InvalidTransitionError`; в обоих случаях состояние не меняется.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter(id)` для задания в dead-letter
- **THEN** возвращён тот же объект `Job` со статусом `PENDING`, `run_at == now`, `error is None`; `dead_letters()` не содержит его; `jobs.requeued == 1`; `next_due()` возвращает его

#### Scenario: Повторный возврат
- **WHEN** `requeue_dead_letter(id)` вызывается второй раз подряд
- **THEN** выбрасывается `InvalidTransitionError`, `jobs.requeued` остаётся 1

#### Scenario: Неизвестное задание
- **WHEN** вызывается `requeue_dead_letter("nope")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Задание не в dead-letter
- **WHEN** `requeue_dead_letter(id)` для задания в `FAILED` или `PENDING`
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: Отмена и очистка не затрагивают dead-letter
- **WHEN** вызываются `cancel(id)` и `purge_finished()` для задания в `DEAD_LETTERED`
- **THEN** `cancel` выбрасывает `InvalidTransitionError`, `purge_finished` задание не удаляет, запись остаётся

#### Scenario: Повторное попадание в dead-letter
- **WHEN** возвращённое задание снова исчерпывает попытки
- **THEN** в конце `dead_letters()` появляется новая запись для того же `job_id`, дубликатов нет


### specs/job-retries/spec.md

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


### specs/retry-policy/spec.md

## Purpose

Описывает политику повторов `RetryPolicy`: допустимые параметры, расчёт задержки перед следующей попыткой и определение, можно ли повторять задание после данной ошибки.

## ADDED Requirements

### Requirement: Параметры политики повторов
`jobq/retry.py` SHALL предоставлять `RetryPolicy` — неизменяемый dataclass с полями `max_attempts: int = 3` (всего попыток, включая первую), `base_delay: float = 1.0` (секунды), `factor: float = 2.0`, `max_delay: float = 60.0` (секунды), `jitter: float = 0.0` и `non_retryable: tuple[type[BaseException], ...] = ()`. В `non_retryable` MUST приниматься любой список/кортеж классов, а храниться — `tuple`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список приводится к tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `policy.non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Политика неизменяема
- **WHEN** выполняется присваивание `policy.max_attempts = 5`
- **THEN** возникает ошибка изменения frozen dataclass

### Requirement: Валидация параметров
Создание `RetryPolicy` с некорректными параметрами SHALL завершаться `ConfigError`. Некорректны: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]` и элемент `non_retryable`, не являющийся классом исключения (подкласс `BaseException`). Граничные значения (`max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay == base_delay`, `jitter` 0 и 1) MUST быть допустимы.

#### Scenario: Недопустимое число попыток
- **WHEN** создаётся `RetryPolicy(max_attempts=0)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Недопустимые задержки и множитель
- **WHEN** создаётся `RetryPolicy(base_delay=-1)`, `RetryPolicy(factor=0.5)` или `RetryPolicy(base_delay=10, max_delay=5)`
- **THEN** в каждом случае выбрасывается `ConfigError`

#### Scenario: Jitter вне диапазона
- **WHEN** создаётся `RetryPolicy(jitter=1.5)` или `RetryPolicy(jitter=-0.1)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError("x")])`, `RetryPolicy(non_retryable=[int])` или `RetryPolicy(non_retryable=["ValueError"])`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся `RetryPolicy(max_attempts=1, base_delay=0, factor=1, max_delay=0, jitter=1)`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки
`delay_for(attempt, rng=None)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1) как `base_delay * factor ** (attempt - 1)`, ограниченную сверху `max_delay`. При `jitter > 0` уже ограниченная задержка MUST умножаться на `rng.uniform(1 - jitter, 1 + jitter)` — ровно один вызов `uniform` на одну задержку; при `jitter == 0` `rng` MUST NOT использоваться. Если `rng` не передан, а `jitter > 0`, используется источник случайности по умолчанию. `attempt < 1` — `ConfigError`. Метод MUST работать для любого `attempt` (включая очень большие, например 5000 и более) без `OverflowError`, в том числе при `base_delay == 0` (результат `0.0`) и `factor == 1`.

#### Scenario: Экспоненциальный рост
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=60)` вычисляет `delay_for` для попыток 1, 2, 3
- **THEN** результаты равны `1.0`, `2.0`, `4.0`

#### Scenario: Ограничение max_delay
- **WHEN** `RetryPolicy(base_delay=1, factor=2, max_delay=60).delay_for(10)`
- **THEN** результат равен `60.0`

#### Scenario: Огромный номер попытки
- **WHEN** `RetryPolicy(max_attempts=10000).delay_for(5000)` и `delay_for(10000)`
- **THEN** возвращается `60.0` без `OverflowError`

#### Scenario: Нулевая базовая задержка
- **WHEN** `RetryPolicy(base_delay=0).delay_for(5000)`
- **THEN** результат равен `0.0` без `OverflowError` и без `nan`

#### Scenario: Jitter применяется после ограничения
- **WHEN** `RetryPolicy(base_delay=1, max_delay=60, jitter=0.5).delay_for(10, rng)` и `rng.uniform(0.5, 1.5)` вернул `1.25`
- **THEN** результат равен `75.0`, а `uniform` вызван ровно один раз с аргументами `(0.5, 1.5)`

#### Scenario: Без jitter rng не трогается
- **WHEN** `delay_for(1, rng)` вызывается для политики с `jitter == 0`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Недопустимый номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Определение повторяемости ошибки
`is_retryable(exc)` SHALL возвращать `False` для экземпляров любого класса из `non_retryable` (с учётом наследования, как обычный `except`) и всегда для `PermanentJobError` (и её наследников), независимо от `non_retryable`; для остальных исключений — `True`.

#### Scenario: Ошибка из non_retryable
- **WHEN** `RetryPolicy(non_retryable=(ValueError,)).is_retryable(ValueError())`
- **THEN** результат `False`

#### Scenario: Наследник класса из non_retryable
- **WHEN** `is_retryable(UnicodeDecodeError(...))` при `non_retryable=(ValueError,)`
- **THEN** результат `False`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** `RetryPolicy().is_retryable(PermanentJobError("no"))`
- **THEN** результат `False`

#### Scenario: Обычная ошибка повторяема
- **WHEN** `RetryPolicy(non_retryable=(ValueError,)).is_retryable(TimeoutError())`
- **THEN** результат `True`

### Requirement: PermanentJobError
`jobq/errors.py` SHALL определять `PermanentJobError`, наследующую `JobqError`. Обработчик бросает её, когда точно знает, что повтор не поможет.

#### Scenario: Иерархия
- **WHEN** проверяется `issubclass(PermanentJobError, JobqError)`
- **THEN** результат `True`


### tasks.md

## 1. Модели, ошибки, метрики

- [ ] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить новым тестом `issubclass`
- [ ] 1.2 Добавить `RETRY_SCHEDULED`/`DEAD_LETTERED` в `JobStatus` с подписями «Ожидает повтора»/«В dead-letter» (нетерминальные) и `DeadLetterEntry`; проверить тестом значений, подписей и `is_terminal`
- [ ] 1.3 Добавить счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` в `jobq/metrics.py`; проверить, что они читаются как 0 по умолчанию

## 2. RetryPolicy

- [ ] 2.1 Создать `jobq/retry.py` с `RetryPolicy`, валидацией в `ConfigError` и приведением `non_retryable` к tuple; проверить тестами из сценариев валидации
- [ ] 2.2 Реализовать `delay_for` без `OverflowError` (attempt 5000/10000, `base_delay=0`, `factor=1`) и jitter с одним вызовом `uniform`; проверить тестами с фейковым `rng`
- [ ] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError`); проверить тестами

## 3. Очередь и хранилище

- [ ] 3.1 Расширить `InMemoryJobStore.due()` статусом `RETRY_SCHEDULED`; проверить тестом выборки до и после `run_at`
- [ ] 3.2 Добавить `default_retry_policy`, `set_retry_policy`, `retry_policy_for` (замена целиком, `None` снимает); проверить тестами
- [ ] 3.3 Расширить `_TRANSITIONS`, добавить `mark_retry_scheduled`, `mark_dead_lettered`, `dead_letters`, `requeue_dead_letter` со счётчиками; проверить тестами порядка, копии списка, ошибок requeue, `cancel` и `purge_finished`

## 4. Воркер

- [ ] 4.1 Добавить keyword-only `rng` в `Worker` и выбор `FAILED`/`RETRY_SCHEDULED`/`DEAD_LETTERED` (политика на момент ошибки, нет обработчика → `FAILED`, `rng` только при реальном повторе); проверить тестами всех сценариев `job-retries`, включая полный цикл с `ManualClock`

## 5. Экспорт, отчёт и регрессия

- [ ] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`; проверить импортом
- [ ] 5.2 Проверить, что `render_report` показывает новые подписи, `git diff --stat` не содержит `dashboard.py`/`cli.py`, и полный `pytest` проходит без изменения существующих тестов
- [ ] 5.3 Сверить публичный API реализации с proposal и specs (имена, сигнатуры, keyword-only параметры, значения enum, имена счётчиков) и устранить расхождения
