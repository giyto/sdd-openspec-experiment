### design.md

## Context

Сейчас `Worker.run_once` на любое `Exception` вызывает `queue.mark_failed`. Все смены статуса идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; `InMemoryJobStore.due` выбирает только `PENDING`; `Metrics` увеличивает счётчик в момент перехода. Отчёт (`dashboard.render_report`) обходит все `JobStatus` и берёт подписи из `JobStatus.label`, поэтому новые статусы появятся в нём без правок `dashboard.py` (он и `cli.py` вне зоны изменений). Мотивацию см. в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:**
- Политика повторов как чистый объект без состояния; решение «FAILED / повтор / dead-letter» в одном месте (воркер), состояние и переходы — в очереди.
- Полная обратная совместимость при отсутствии политик.

**Non-Goals:**
- Персистентность dead-letter (хранилище только в памяти), автоматический requeue, отдельные метрики по типам, изменения `dashboard.py`/`cli.py`.
- Отдельный раздел отчёта со списком dead-letter.

## Decisions

1. **`RetryPolicy` — frozen dataclass с `__post_init__`-валидацией.** `non_retryable` нормализуется в tuple через `object.__setattr__`. Все ошибки — `ConfigError` (в проекте встроенные исключения наружу не выпускаются). Дополнительно (допущение) отклоняем NaN/inf и не-числа/`bool`, иначе сравнения молча проходят.
2. **`delay_for` без переполнения.** `factor == 1` или `base_delay == 0` → без возведения в степень (`base_delay` / `0`). Иначе `base_delay * factor ** (attempt - 1)` в `try/except OverflowError` → `max_delay` (при `factor >= 1`, `base_delay > 0` переполнение означает значение заведомо выше любого конечного `max_delay`). Затем `min(..., max_delay)`, затем джиттер (`rng.uniform` ровно один раз, только при `jitter > 0`). Без `rng` — модульный `random`. Альтернатива (логарифмы) сложнее и менее точна.
3. **Решение принимает воркер, очередь даёт примитивы.** В `JobQueue` добавляются `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` (по образцу `mark_failed`), `mark_failed` не меняется. Воркер: нет политики → `mark_failed`; `not is_retryable` → `mark_failed`; `attempts >= max_attempts` → `mark_dead_lettered`; иначе `delay_for(job.attempts, rng)` и `mark_retry_scheduled(run_at=clock.now()+delay)`. Это гарантирует порядок «rng трогаем только при реальном повторе» и использование политики на момент ошибки (`retry_policy_for` вызывается в обработчике ошибки). Ветка «нет обработчика» остаётся `mark_failed` до любой логики политик.
4. **Переходы:** `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`; `RETRY_SCHEDULED → {RUNNING, CANCELLED}`; `DEAD_LETTERED → {PENDING}` (только через `requeue_dead_letter`, поэтому `cancel` туда запрещён). `cancel` для `RETRY_SCHEDULED` разрешён (допущение: задание ещё не выполняется, как `PENDING`).
5. **Выборка:** `InMemoryJobStore.due` включает `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`.
6. **Dead-letter хранится в очереди** как список `DeadLetterEntry` (frozen) в порядке добавления; `dead_letters()` отдаёт копию; `requeue_dead_letter` ищет запись по `job_id` (отсутствие job → `JobNotFoundError` из хранилища, не в dead-letter → `InvalidTransitionError` через `_transition`), удаляет запись, меняет статус на `PENDING`, `run_at = now`, `error = None`, `finished_at = None`, счётчик `jobs.requeued`. `attempts` не сбрасывается (в тикете не упомянут; сохраняем историю запусков).
7. **`error` и `finished_at`.** `mark_succeeded` обнуляет `error` (инвариант модели: у `SUCCEEDED` `error is None`, а после повторов там лежит прошлая ошибка). `RETRY_SCHEDULED` не ставит `finished_at`; `DEAD_LETTERED` ставит.
8. **`DEAD_LETTERED` терминален для воркера (`is_terminal=True`), но `purge_finished` пропускает его**, чтобы запись dead-letter не осталась «висячей». `RETRY_SCHEDULED` нетерминален.
9. **Метрики:** константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`; инкремент внутри соответствующих `mark_*`/`requeue_*` сразу после перехода. Обновить docstring `metrics.py`.
10. **Экспорт и документация:** `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`; раздел в README.

## Risks / Trade-offs

- [Возврат из dead-letter не сбрасывает `attempts`, и при `attempts >= max_attempts` следующее же падение снова уведёт задание в dead-letter без повторов] → зафиксировано как допущение, соответствует тексту тикета; при необходимости сброс добавляется отдельным изменением.
- [Джиттер применяется после `max_delay`, поэтому задержка может превысить `max_delay` до `1+jitter` раз] → прямо требуется тикетом.
- [`stats()` и отчёт получают две новые строки; внешние потребители с жёстким набором ключей могут удивиться] → ожидаемо для новых статусов; существующие тесты проверяют набор ключей через `JobStatus`.
- [`failure_rate` не учитывает `DEAD_LETTERED`] → `dashboard.py` не трогаем; отметить владельцам отчёта.
- [Блок «Последние ошибки» в отчёте показывает только `FAILED`] → то же ограничение, вне зоны.

## Допущения

- `cancel` для `RETRY_SCHEDULED` разрешён, для `DEAD_LETTERED` — нет.
- Без `rng` используется модульный `random`; при `Worker(rng=None)` поведение то же.
- `set_retry_policy`/конструктор проверяют тип политики и непустой `job_type` (`ConfigError`).
- Задание, у которого политика пропала между попытками, при следующем падении идёт в `FAILED`.


### proposal.md

## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, и дежурные каждое утро вручную перезапускают десятки заданий, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились.

## What Changes

- Новый модуль `jobq/retry.py`: `RetryPolicy` (frozen dataclass) с `delay_for` и `is_retryable`; валидация параметров через `ConfigError`.
- Новая ошибка `PermanentJobError(JobqError)` — обработчик бросает её, когда повтор точно не поможет.
- Новые статусы `RETRY_SCHEDULED` («Ожидает повтора») и `DEAD_LETTERED` («В dead-letter»), модель `DeadLetterEntry`.
- `JobQueue`: параметр `default_retry_policy` (keyword-only), `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`, новые переходы статусов.
- `Worker`: keyword-only параметр `rng`; при падении обработчика выбирает `FAILED`, `RETRY_SCHEDULED` или `DEAD_LETTERED` по политике, действующей в момент ошибки.
- `InMemoryJobStore.due` отдаёт также `RETRY_SCHEDULED`-задания с наступившим `run_at`.
- Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Без политики (ни для типа, ни по умолчанию) поведение не меняется. Сигнатуры существующих методов не меняются, новые зависимости не добавляются, `jobq/dashboard.py` и `jobq/cli.py` не трогаем (отчёт подхватит подписи новых статусов через `JobStatus.label`).

## Capabilities

### New Capabilities
- `retry-policy`: `RetryPolicy`, расчёт задержки, классификация ошибок, `PermanentJobError`, назначение политик очереди/типа.
- `job-retry-flow`: что делает воркер при падении обработчика, новые статусы и переходы, выборка заданий к повтору, счётчики, подписи в отчёте.
- `dead-letter-queue`: `DeadLetterEntry`, `dead_letters()`, `requeue_dead_letter()`.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций, существующее поведение сохраняется)

## Impact

- Код: `jobq/retry.py` (новый), `errors.py`, `models.py`, `queue.py`, `store.py`, `worker.py`, `metrics.py`, `__init__.py` (экспорт), `README.md`.
- Публичный API расширяется только добавлениями; `JobStatus` получает два члена, поэтому `stats()` и отчёт содержат две новые строки.
- Новые тесты добавляются, существующие не меняются.


### specs/dead-letter-queue/spec.md

## Purpose

Описывает dead-letter очередь: учёт заданий, исчерпавших попытки, и осознанный возврат их в работу.

## ADDED Requirements

### Requirement: Список dead-letter
`JobQueue.dead_letters()` SHALL возвращать список `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` в порядке попадания в dead-letter. Запись фиксирует число попыток, последнюю ошибку и время (по часам очереди) на момент попадания. Возвращается копия: изменение списка не влияет на очередь. `DeadLetterEntry` SHALL быть неизменяемой.

#### Scenario: Порядок и содержимое
- **WHEN** в dead-letter последовательно попадают два задания
- **THEN** `dead_letters()` содержит две записи в порядке попадания с корректными `attempts`, `error`, `dead_lettered_at`

#### Scenario: Пустой список
- **WHEN** в dead-letter ничего не попадало
- **THEN** `dead_letters() == []`

### Requirement: Возврат из dead-letter
`requeue_dead_letter(job_id)` SHALL вернуть в работу то же самое задание (новое не создаётся, `id` сохраняется): статус `PENDING`, `run_at = now`, `error = None`, запись удаляется из `dead_letters()`, счётчик `jobs.requeued` увеличивается. `attempts` и `created_at` не изменяются. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`; для существующего задания не в dead-letter — `InvalidTransitionError`. Других способов выйти из dead-letter нет. Если задание снова попадёт в dead-letter, добавляется новая запись в конец списка.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter` для задания в dead-letter
- **THEN** возвращается тот же `Job` со статусом `PENDING`, `run_at == now`, `error is None`, `dead_letters()` не содержит его

#### Scenario: Задание не в dead-letter
- **WHEN** вызывается `requeue_dead_letter` для `PENDING`- или `FAILED`-задания
- **THEN** выбрасывается `InvalidTransitionError`, состояние не меняется

#### Scenario: Неизвестное задание
- **WHEN** вызывается `requeue_dead_letter("nope")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Повторное попадание
- **WHEN** возвращённое задание снова падает и исчерпывает попытки
- **THEN** в конце `dead_letters()` появляется новая запись


### specs/job-retry-flow/spec.md

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


### specs/retry-policy/spec.md

## Purpose

Описывает политику повторов `RetryPolicy`: расчёт задержки, классификацию ошибок на повторяемые и неповторяемые, валидацию параметров и назначение политик очереди и типам заданий.

## ADDED Requirements

### Requirement: Параметры и валидация политики
`RetryPolicy` SHALL быть неизменяемой и иметь параметры `max_attempts=3` (всего попыток, включая первую), `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`. Некорректные параметры SHALL приводить к `ConfigError` при создании политики: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, нечисловые или нефинитные (NaN, бесконечность) числовые значения, элемент `non_retryable`, не являющийся классом исключения. `non_retryable` SHALL принимать любую последовательность классов и храниться как `tuple`. Встроенные `ValueError`/`TypeError` наружу не выпускаются.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список превращается в tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `non_retryable == (ValueError, KeyError)`

#### Scenario: Некорректный параметр
- **WHEN** создаётся политика с `max_attempts=0`, `base_delay=-1`, `factor=0.5`, `max_delay` меньше `base_delay`, `jitter=1.5` или `non_retryable=[int]`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные допустимые значения
- **WHEN** создаётся политика с `max_attempts=1`, `base_delay=0`, `factor=1`, `max_delay == base_delay`, `jitter=0` или `jitter=1`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой, если упала попытка номер `attempt` (с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. Функция SHALL работать для любого `attempt >= 1` (включая очень большие значения и `base_delay=0`) без `OverflowError`; при переполнении результат равен `max_delay` (при `base_delay=0` — `0`). `attempt < 1` SHALL приводить к `ConfigError`.

#### Scenario: Экспоненциальный рост с ограничением
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`
- **THEN** `delay_for(1) == 1`, `delay_for(4) == 8`, `delay_for(7) == 60`

#### Scenario: Огромный номер попытки
- **WHEN** `max_attempts=10000`, `base_delay=1`, `factor=2`, `max_delay=60` и вызывается `delay_for(5000)`
- **THEN** результат `60`, исключения нет

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(5000)`
- **THEN** результат `0`

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Джиттер
При `jitter > 0` `delay_for` SHALL умножать уже ограниченную `max_delay` задержку на `rng.uniform(1 - jitter, 1 + jitter)`, делая ровно один вызов `uniform` на одну задержку. При `jitter == 0` генератор SHALL NOT использоваться. Если `rng` не передан, SHALL использоваться собственный источник случайности.

#### Scenario: Один uniform на задержку
- **WHEN** `jitter=0.5` и `delay_for(2, rng)` вызывается с предсказуемым `rng`
- **THEN** результат равен ограниченной задержке, умноженной на единственное значение `rng.uniform(0.5, 1.5)`

#### Scenario: Нулевой джиттер не трогает rng
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Джиттер применяется после ограничения
- **WHEN** задержка уже упёрлась в `max_delay` и `jitter=0.2`
- **THEN** результат лежит в `[0.8 * max_delay, 1.2 * max_delay]`

### Requirement: Классификация ошибок
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами (с учётом наследования, как обычный `except`) любого класса из `non_retryable`, и всегда `False` для `PermanentJobError` и его наследников; иначе `True`. `PermanentJobError` SHALL наследоваться от `JobqError`.

#### Scenario: Наследники неповторяемых классов
- **WHEN** `non_retryable=(ValueError,)` и ошибка — `UnicodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError всегда неповторяем
- **WHEN** политика с пустым `non_retryable` и ошибка `PermanentJobError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Обычная ошибка
- **WHEN** ошибка `TimeoutError`, не входящая в `non_retryable`
- **THEN** `is_retryable` возвращает `True`

### Requirement: Назначение политик
`JobQueue` SHALL принимать keyword-only `default_retry_policy`; `set_retry_policy(job_type, policy)` SHALL задавать политику типа, `None` снимает её; `retry_policy_for(job_type)` SHALL возвращать политику типа, иначе политику по умолчанию, иначе `None`. Политика типа SHALL заменять политику по умолчанию целиком, без слияния полей. Значение, не являющееся `RetryPolicy` или `None`, и пустой `job_type` SHALL приводить к `ConfigError`. Старые вызовы `JobQueue(...)` без нового параметра SHALL работать как раньше.

#### Scenario: Приоритет политики типа
- **WHEN** задан дефолт с `non_retryable=(ValueError,)` и политика типа `email` без `non_retryable`
- **THEN** `retry_policy_for("email")` возвращает политику типа, а `retry_policy_for("other")` — дефолт

#### Scenario: Снятие политики типа
- **WHEN** вызывается `set_retry_policy("email", None)`
- **THEN** `retry_policy_for("email")` возвращает дефолт очереди или `None`, если дефолта нет

#### Scenario: Нет политик
- **WHEN** ни дефолта, ни политики типа нет
- **THEN** `retry_policy_for(...)` возвращает `None`


### tasks.md

## 1. Базовые типы

- [ ] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить, что `issubclass(PermanentJobError, JobqError)` (тест)
- [ ] 1.2 В `jobq/models.py` добавить статусы `RETRY_SCHEDULED`, `DEAD_LETTERED`, подписи «Ожидает повтора» / «В dead-letter», `DEAD_LETTERED` в терминальные, и `DeadLetterEntry` (frozen); тест на значения, подписи, `is_terminal`
- [ ] 1.3 Создать `jobq/retry.py` с `RetryPolicy` (валидация через `ConfigError`, `non_retryable` в tuple, `delay_for` без `OverflowError`, `is_retryable`); тесты на все сценарии retry-policy, включая `delay_for(5000)` при `max_attempts=10000`, `base_delay=0`, джиттер с подменным `rng` (один `uniform`, при `jitter=0` не вызывается)

## 2. Очередь, хранилище, метрики

- [ ] 2.1 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` и обновить docstring; тест имён счётчиков
- [ ] 2.2 В `jobq/store.py` расширить `due` на `RETRY_SCHEDULED`; тест: повтор не берётся до `run_at`, порядок `(run_at, seq)` сохранён
- [ ] 2.3 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` (замена, а не слияние; `None` снимает; `ConfigError` на неверный тип/пустой тип); тесты приоритета политик
- [ ] 2.4 В `JobQueue` расширить `_TRANSITIONS`, добавить `mark_retry_scheduled`, `mark_dead_lettered`, `dead_letters`, `requeue_dead_letter`; `mark_succeeded` обнуляет `error`; `purge_finished` пропускает `DEAD_LETTERED`; тесты: счётчики, порядок записей, поля после requeue, `JobNotFoundError`/`InvalidTransitionError`, `cancel` для `RETRY_SCHEDULED` и запрет для `DEAD_LETTERED`

## 3. Воркер

- [ ] 3.1 В `Worker.__init__` добавить keyword-only `rng`; в обработчике ошибки реализовать выбор FAILED / RETRY_SCHEDULED / DEAD_LETTERED по политике на момент ошибки; ветка «нет обработчика» остаётся `FAILED`; тесты: временная ошибка, исчерпание попыток, `max_attempts=1`, `PermanentJobError` и наследник `non_retryable` на последней попытке → `FAILED`, `rng` не трогается при FAILED/dead-letter, ровно один `uniform` на повтор, смена политики после enqueue, успех после повтора (`error is None`)
- [ ] 3.2 Сквозной тест с `ManualClock`: цепочка падений → dead-letter → `requeue_dead_letter` → успех; проверить счётчики `jobs.retried/dead_lettered/requeued` и строки «Ожидает повтора» / «В dead-letter» в `render_report`

## 4. Завершение

- [ ] 4.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`, описать функциональность в `README.md`; проверить импорт `from jobq import ...`
- [ ] 4.2 Запустить полный `pytest`: все существующие тесты проходят без изменений, `git diff --stat` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты
