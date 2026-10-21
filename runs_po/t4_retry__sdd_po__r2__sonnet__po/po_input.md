### design.md

## Context

Все смены статуса идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; воркер сейчас на любую ошибку вызывает `mark_failed`. `InMemoryJobStore.due()` выбирает только `PENDING`. `dashboard.render_report` и `stats()` обходят все значения `JobStatus`, поэтому новые статусы и подписи попадут в отчёт без правок `dashboard.py`/`cli.py` (они не наши). Время только из `queue.clock`; ошибки конфигурации — `ConfigError`; только stdlib. Требования — в specs; мотивация — в proposal.md.

## Goals / Non-Goals

**Goals:**
- Политика, решение воркера и dead-letter без изменений существующих сигнатур и тестов.
- Детерминизм для тестов: ровно один `rng.uniform` на запланированный повтор.

**Non-Goals:**
- Персистентность журнала dead-letter, потокобезопасность, автоповтор из dead-letter, правки dashboard/cli.

## Decisions

1. **`jobq/retry.py` с замороженным dataclass.** Проверка в `__post_init__`, `non_retryable` нормализуется через `object.__setattr__(self, ..., tuple(...))`. Ошибки — `ConfigError` (не `ValueError`, по соглашению пакета).
2. **Безопасный расчёт задержки.** `base_delay == 0` → `0.0`; `factor == 1` → `base_delay`; иначе привести `factor` к `float` и считать `base * factor ** (attempt - 1)` в `try`, при `OverflowError` брать `inf`, затем `min(raw, max_delay)`. Приведение к `float` нужно, чтобы целый factor не породил гигантский int. Jitter применяется после ограничения. Альтернатива «цикл до достижения max_delay» — O(attempt), хуже.
3. **Решение о судьбе задания — в воркере, переходы — в очереди.** В очереди новые `mark_retry_scheduled(job_id, error, delay)` и `mark_dead_lettered(job_id, error)` рядом с `mark_failed`; воркер вызывает `retry_policy_for`, `is_retryable`, `delay_for`. Так порядок проверок и обращение к `rng` в одном месте. `Worker(rng=None)` создаёт собственный `random.Random()`.
4. **Порядок проверок**: нет обработчика → FAILED до всякой политики; нет политики → FAILED; неповторяемая → FAILED; `attempts >= max_attempts` → DEAD_LETTERED; иначе RETRY_SCHEDULED. `delay_for` вызывается только в последней ветке.
5. **Таблица переходов**: `PENDING→{RUNNING,CANCELLED}`, `RETRY_SCHEDULED→{RUNNING,CANCELLED}`, `RUNNING→{SUCCEEDED,FAILED,RETRY_SCHEDULED,DEAD_LETTERED}`, `DEAD_LETTERED→{PENDING}` (достижим только из `requeue_dead_letter`; `cancel` бросит `InvalidTransitionError`, поэтому `cancel` должен проверять переход отдельно от requeue).
6. **Выборка готовых**: `store.due()` включает `PENDING` и `RETRY_SCHEDULED`, сортировка `(run_at, seq)` прежняя.
7. **Журнал** — список `DeadLetterEntry` в `JobQueue`, `dead_letters()` отдаёт копию; запись удаляется по `job_id` при возврате. Хранилище не расширяем.
8. **Терминальность**: `DEAD_LETTERED` терминален для воркера, но `purge_finished` его пропускает, иначе журнал ссылался бы на удалённое задание. `finished_at` ставится при входе в `DEAD_LETTERED` и сбрасывается при возврате. `RETRY_SCHEDULED` не терминален, `finished_at` не ставится.
9. **Метрики**: константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`, инкремент в самих `mark_*`/`requeue_dead_letter`; обновить docstring модуля.
10. **Политика определяется в момент ошибки** (`retry_policy_for` вызывается в воркере), в задание не копируется.

## Допущения (неоднозначности тикета)

- `requeue_dead_letter` **не сбрасывает `attempts`** (в тикете перечислены только status/run_at/error, а `attempts` документирован как число запусков). Следствие: при неизменной политике первое же падение вернувшегося задания снова уводит его в dead-letter. Если нужен сброс, это отдельное решение продукта.
- Отмена `RETRY_SCHEDULED` разрешена (задание ещё не выполняется).
- `rng=None` у `delay_for` при `jitter>0` — генератор модуля `random`.
- NaN, `bool` и нецелый `max_attempts` — ошибка конфигурации.
- Не-`Exception` (`KeyboardInterrupt`) воркер не перехватывает, как и раньше.
- Существующий тест `test_stats_lists_every_status` сверяет ключи с `JobStatus`, поэтому остаётся зелёным; тест отчёта сверяет строки по `status.label`.

## Risks / Trade-offs

- [Две новые строки в отчёте и `stats()` могут удивить потребителей] → указано в proposal; `dashboard.py` не правим.
- [Повторное попадание в dead-letter после requeue без сброса attempts] → зафиксировано как допущение.
- [Переполнение при больших `attempt`] → отдельные тесты на 5000/10000 и `base_delay=0`.
- [Журнал в памяти теряется при рестарте] → вне объёма, как и само хранилище.


### proposal.md

## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий. Нужны настраиваемые повторы с экспоненциальной задержкой и отдельное место (dead-letter) для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль с неизменяемой `RetryPolicy` (max_attempts, base_delay, factor, max_delay, jitter, non_retryable), расчётом задержки `delay_for` и проверкой `is_retryable`; некорректные параметры — `ConfigError`.
- Новая ошибка `PermanentJobError`: обработчик бросает её, когда повтор заведомо не поможет.
- Новые статусы `RETRY_SCHEDULED` («Ожидает повтора») и `DEAD_LETTERED` («В dead-letter»), модель `DeadLetterEntry`.
- `JobQueue`: политика по умолчанию (`default_retry_policy`) и по типу задания (`set_retry_policy`, `retry_policy_for`), `dead_letters()`, `requeue_dead_letter()`.
- `Worker`: при падении обработчика выбирает между `FAILED`, `RETRY_SCHEDULED` и `DEAD_LETTERED`; необязательный `rng` для jitter.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Не меняются `jobq/dashboard.py` и `jobq/cli.py` (чужие). Подписи новых статусов попадают в отчёт через `JobStatus.label`. Сигнатуры существующих методов не меняются, без политики поведение прежнее. Не **BREAKING**, но в `stats()` и отчёте появляются два новых статуса.

## Capabilities

### New Capabilities
- `retry-policy`: параметры и валидация `RetryPolicy`, расчёт задержки, классификация ошибок, назначение политики очереди и типу задания.
- `job-retry`: что делает воркер при падении обработчика, новые статусы и переходы, срок запуска повтора, счётчики и подписи в отчёте.
- `dead-letter`: журнал заданий, исчерпавших попытки, и их осознанный возврат в работу.

### Modified Capabilities

(нет: в `openspec/specs/` спецификаций ещё нет, существующее поведение без политики не меняется)

## Impact

- Код: новый `jobq/retry.py`; правки `errors.py`, `models.py`, `metrics.py`, `store.py` (выборка готовых), `queue.py`, `worker.py`, `__init__.py`, README.
- Публичный API: только добавления, новые параметры keyword-only. Зависимости не добавляются.
- Побочный эффект: `stats()` содержит ключи `retry_scheduled` и `dead_lettered`; отчёт дежурных получает две новые строки без правок `dashboard.py`.


### specs/dead-letter/spec.md

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
`requeue_dead_letter(job_id)` SHALL возвращать в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` = текущее время очереди, `error=None`, `finished_at=None`; запись удаляется из `dead_letters()`; `jobs.requeued` увеличивается на 1; метод возвращает это задание. `attempts` и `payload` SHALL сохраняться (допущение, см. design.md). Это единственный выход из `DEAD_LETTERED`: отмена и любые другие переходы MUST приводить к `InvalidTransitionError`. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`; в обоих случаях состояние и счётчики не меняются.

#### Scenario: Успешный возврат
- **WHEN** вызван `requeue_dead_letter` для задания из dead-letter
- **THEN** возвращён тот же объект с тем же `id`, статус `PENDING`, `run_at` = now, `error=None`, записи в журнале нет, `jobs.requeued=1`

#### Scenario: Воркер выполняет вернувшееся задание
- **WHEN** задание возвращено и воркер запущен
- **THEN** оно берётся как обычное готовое задание

#### Scenario: Повторное попадание в dead-letter
- **WHEN** вернувшееся задание снова исчерпало попытки
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


### specs/job-retry/spec.md

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


### specs/retry-policy/spec.md

## Purpose

Описывает политику повторов: параметры, их проверку, расчёт задержки между попытками, определение повторяемых ошибок и назначение политики очереди и типам заданий.

## ADDED Requirements

### Requirement: Параметры политики и их проверка
Политика повторов SHALL быть неизменяемой и иметь параметры `max_attempts=3` (всего попыток, включая первую), `base_delay=1.0`, `factor=2.0`, `max_delay=60.0` (секунды), `jitter=0.0` и `non_retryable=()`. Параметр `non_retryable` SHALL принимать любую последовательность классов (например, список) и храниться как tuple. Создание политики с `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]` или элементом `non_retryable`, который не является классом-наследником `BaseException`, MUST завершаться `ConfigError`. Значения NaN MUST считаться некорректными.

#### Scenario: Значения по умолчанию
- **WHEN** создана политика без аргументов
- **THEN** `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`

#### Scenario: Список превращается в tuple
- **WHEN** в `non_retryable` передан список `[ValueError]`
- **THEN** у политики `non_retryable == (ValueError,)`

#### Scenario: Некорректный параметр
- **WHEN** создаётся политика с `max_attempts=0`, или `base_delay=-1`, или `factor=0.5`, или `max_delay` меньше `base_delay`, или `jitter=1.5`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Элемент non_retryable не класс исключения
- **WHEN** в `non_retryable` передана строка, экземпляр исключения или класс, не являющийся исключением
- **THEN** выбрасывается `ConfigError`

#### Scenario: max_attempts=1 допустим
- **WHEN** создаётся политика с `max_attempts=1`
- **THEN** ошибки нет; повторов не будет

### Requirement: Расчёт задержки перед повтором
`delay_for(attempt)` SHALL возвращать задержку в секундах перед следующей попыткой, если упала попытка номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на ровно одно значение `rng.uniform(1 - jitter, 1 + jitter)`; при `jitter == 0` генератор MUST NOT вызываться. Расчёт MUST работать для любого `attempt >= 1` (включая очень большие, например 5000 и 10000) и любых допустимых параметров, включая `base_delay=0`, без `OverflowError`. Для `attempt < 1` SHALL выбрасываться `ConfigError`. Если `rng` не передан, а `jitter > 0`, SHALL использоваться генератор по умолчанию.

#### Scenario: Экспоненциальный рост
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`, `jitter=0`
- **THEN** `delay_for(1)=1`, `delay_for(2)=2`, `delay_for(3)=4`

#### Scenario: Ограничение max_delay
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`
- **THEN** `delay_for(10)=60`

#### Scenario: Огромный номер попытки
- **WHEN** вызывается `delay_for(5000)` или `delay_for(10000)` при `factor=2`
- **THEN** результат равен `max_delay`, исключения нет

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(10000)`
- **THEN** результат `0.0`, исключения нет

#### Scenario: factor=1
- **WHEN** `factor=1`
- **THEN** при любом `attempt` задержка равна `base_delay`

#### Scenario: Jitter применяется после ограничения
- **WHEN** `jitter=0.5`, задержка до jitter ограничена `max_delay=60`, а `rng.uniform` вернул 1.25
- **THEN** результат 75.0, и `uniform` вызван ровно один раз с аргументами `(0.5, 1.5)`

#### Scenario: Без jitter генератор не трогаем
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Номер попытки меньше 1
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация повторяемых ошибок
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError` и его наследников, независимо от `non_retryable`. Для остальных исключений SHALL возвращаться `True`. `PermanentJobError` SHALL наследоваться от `JobqError`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и проверяется `UnicodeDecodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError
- **WHEN** `non_retryable=()` и проверяется `PermanentJobError("x")`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка
- **WHEN** проверяется `TimeoutError` при `non_retryable=(ValueError,)`
- **THEN** `is_retryable` возвращает `True`

### Requirement: Назначение политики очереди и типам заданий
Очередь SHALL принимать политику по умолчанию (`default_retry_policy`, keyword-only) и политики по типу задания через `set_retry_policy(job_type, policy)`; `set_retry_policy(job_type, None)` SHALL снимать политику типа. `retry_policy_for(job_type)` SHALL возвращать политику типа, а если её нет — политику по умолчанию, а если нет и её — `None`. Политика типа MUST заменять политику по умолчанию целиком, без слияния по полям. Политика MUST определяться на момент ошибки, а не на момент постановки задания. Значение, не являющееся `RetryPolicy` или `None`, и пустой `job_type` MUST приводить к `ConfigError`.

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** у очереди дефолт с `non_retryable=(ValueError,)`, а для типа задана политика без `non_retryable`
- **THEN** `retry_policy_for(тип)` возвращает политику типа, и `ValueError` для этого типа повторяется

#### Scenario: Откат к дефолту
- **WHEN** для типа вызвано `set_retry_policy(тип, None)`
- **THEN** `retry_policy_for(тип)` возвращает дефолт очереди

#### Scenario: Политики нет совсем
- **WHEN** нет ни дефолта, ни политики типа
- **THEN** `retry_policy_for(тип)` возвращает `None`

#### Scenario: Политика меняется после постановки
- **WHEN** задание поставлено, затем политика типа изменена, затем обработчик упал
- **THEN** применяется политика, действующая в момент падения

#### Scenario: Некорректный аргумент
- **WHEN** в `set_retry_policy` передан не `RetryPolicy` и не `None`
- **THEN** выбрасывается `ConfigError`


### tasks.md

## 1. Основа: ошибки, модели, метрики

- [ ] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py` и экспорт в `jobq/__init__.py`; проверить `issubclass(PermanentJobError, JobqError)` тестом
- [ ] 1.2 Добавить `RETRY_SCHEDULED`/`DEAD_LETTERED`, подписи «Ожидает повтора»/«В dead-letter», терминальность (`DEAD_LETTERED` терминален, `RETRY_SCHEDULED` нет) и `DeadLetterEntry` в `jobq/models.py`; тест на `value`, `label`, `is_terminal`
- [ ] 1.3 Добавить константы `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` и обновить docstring в `jobq/metrics.py`; тест, что счётчики читаются как 0

## 2. RetryPolicy

- [ ] 2.1 Создать `jobq/retry.py`: замороженный dataclass, значения по умолчанию, нормализация `non_retryable` в tuple, валидация с `ConfigError` (включая NaN, не-классы, bool/нецелый `max_attempts`); параметризованный тест на каждое некорректное значение
- [ ] 2.2 Реализовать `delay_for` без `OverflowError` (`base_delay=0`, `factor=1`, attempt 5000/10000, целый factor), jitter после ограничения, ровно один `uniform`, без вызова при `jitter=0`, `attempt<1` → `ConfigError`; тесты с подменным rng
- [ ] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError` всегда False); тесты по сценариям спецификации
- [ ] 2.4 Экспортировать `RetryPolicy`, `DeadLetterEntry` из `jobq/__init__.py`; проверить импортом `from jobq import RetryPolicy, DeadLetterEntry`

## 3. Очередь

- [ ] 3.1 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` с валидацией; тесты: замена целиком, снятие политики, `None`, смена политики после enqueue
- [ ] 3.2 Расширить `_TRANSITIONS` и `InMemoryJobStore.due()` (включить `RETRY_SCHEDULED`), разрешить `cancel` из `RETRY_SCHEDULED`; тест: до `run_at` не выбирается, после — выбирается в порядке `(run_at, seq)`
- [ ] 3.3 Добавить `mark_retry_scheduled` и `mark_dead_lettered` (ошибка, `run_at`, `finished_at`, запись журнала, счётчики); тесты на счётчики и поля
- [ ] 3.4 Добавить `dead_letters()` (копия, порядок попадания) и `requeue_dead_letter()` (то же задание, PENDING, run_at=now, error/finished_at очищены, запись удалена, `jobs.requeued`; `JobNotFoundError`/`InvalidTransitionError` без побочных эффектов); тесты по сценариям спецификации, включая запрет `cancel` из dead-letter
- [ ] 3.5 Сделать `purge_finished` пропускающим `DEAD_LETTERED`; тест, что задание и запись остаются

## 4. Воркер

- [ ] 4.1 Добавить `Worker(..., rng=None)` keyword-only и ветвление при ошибке обработчика в порядке: нет обработчика → FAILED, нет политики → FAILED, неповторяемая → FAILED, `attempts >= max_attempts` → DEAD_LETTERED, иначе RETRY_SCHEDULED с `delay_for(job.attempts, rng)`; `rng` не трогается вне последней ветки; тесты со всеми сценариями `job-retry`, включая `max_attempts=1` и `PermanentJobError`
- [ ] 4.2 Сквозные тесты на ManualClock: упало дважды, успех на третьем запуске (`error=None`); путь retry, retry, dead-letter, requeue, success со сверкой счётчиков
- [ ] 4.3 Тест обратной совместимости: без политики любая ошибка даёт FAILED; тест, что `render_report` содержит новые подписи

## 5. Документация и проверка

- [ ] 5.1 Обновить README (таблица модулей, `retry.py`, раздел про повторы и dead-letter, допущение про `attempts`); проверить, что файл содержит новый раздел
- [ ] 5.2 Запустить `python -m pytest -q`: все существующие и новые тесты зелёные; `git diff --stat` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты
