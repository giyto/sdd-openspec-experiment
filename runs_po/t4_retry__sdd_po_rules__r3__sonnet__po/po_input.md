### design.md

## Context

Все переходы статусов идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; воркер сейчас переводит упавшее задание в `FAILED` через `mark_failed`; готовые к запуску задания выбирает `InMemoryJobStore.due` (только `PENDING`). Отчёт `dashboard.py` перебирает `JobStatus` и берёт `status.label`, поэтому подписи достаточно добавить в `models.py`. Мотивацию и допущения см. в `proposal.md`, требования — в `specs/`.

## Goals / Non-Goals

**Goals:**
- Реализовать политику повторов и dead-letter, не меняя публичных сигнатур и существующих тестов.
- Сохранить поведение «как раньше», когда политики нет.

**Non-Goals:**
- Правки `dashboard.py`, `cli.py`, персистентность dead-letter, внешние зависимости.
- Сброс `attempts` при `requeue_dead_letter`.

## Decisions

1. **`jobq/retry.py` — самостоятельный модуль без зависимости от `queue`/`worker`.** `RetryPolicy` — `@dataclass(frozen=True)`; валидация и приведение `non_retryable` к `tuple` в `__post_init__` (через `object.__setattr__`). Ошибки — `ConfigError`. Проверка класса исключения: `isinstance(x, type) and issubclass(x, BaseException)`. Проверку чисел делаем в форме «not (условие корректности)», чтобы NaN отвергался. `bool` для `max_attempts` отвергаем.

2. **`delay_for` без переполнения.** Порядок: проверить `attempt >= 1`; если `base_delay == 0` → `0.0` (до возведения в степень, иначе `0 * inf`); если `factor == 1` → `min(base_delay, max_delay)`; иначе считать в `try: factor ** (attempt - 1)` с перехватом `OverflowError` → результат `max_delay`. Как вторая защита: если множитель `inf`, результат `max_delay`. Затем `min(raw, max_delay)`, и только после этого `rng.uniform(1 - jitter, 1 + jitter)` при `jitter > 0` (`rng or random` — модульный генератор по умолчанию). Альтернатива — логарифмическое сравнение; отвергнута как менее читаемая и менее точная на границе. `attempt` — целое; при больших значениях `factor ** n` с целыми операндами не используется (factor приводится к `float`), чтобы не строить огромные int.

3. **Классификация.** `is_retryable`: `False`, если `isinstance(exc, PermanentJobError)` или `isinstance(exc, self.non_retryable)` (пустой tuple даёт `False`), иначе `True`. `PermanentJobError` добавляется в `errors.py` рядом с остальными.

4. **Статусы и таблица переходов.** В `JobStatus` добавляются `RETRY_SCHEDULED`, `DEAD_LETTERED` (в конец, чтобы порядок существующих строк отчёта не менялся), подписи в `_LABELS`. `_TERMINAL` не расширяется. Новая таблица:
   - `PENDING → {RUNNING, CANCELLED}` (как было);
   - `RETRY_SCHEDULED → {RUNNING, CANCELLED}`;
   - `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`;
   - `DEAD_LETTERED → {PENDING}` — используется только `requeue_dead_letter`.
   Так недопустимые переходы по-прежнему ловит `_transition` и выбрасывается `InvalidTransitionError`. Не терминальность обоих статусов нужна, чтобы `purge_finished` (отбор по `is_terminal`) их не удалял.

5. **Выборка.** `InMemoryJobStore.due` принимает `PENDING` и `RETRY_SCHEDULED`; сортировка `(run_at, seq)` прежняя. Нет смысла плодить отдельный метод: `next_due` и воркер не меняются.

6. **Методы очереди для воркера.** Добавляются `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` по образцу `mark_failed`: переход, запись `error`, счётчик (`jobs.retried` / `jobs.dead_lettered`), для dead-letter — `finished_at` и запись `DeadLetterEntry` в приватный список. Счётчики увеличиваются внутри этих методов в момент перехода, как существующие. Решение о том, какой метод вызвать, принимает воркер (там известны исключение и `rng`); альтернатива — один метод `handle_failure` в очереди — отвергнута: воркер уже владеет разбором исключения, а очередь остаётся набором переходов.

7. **Хранение dead-letter.** `JobQueue._dead_letters: list[DeadLetterEntry]` в порядке попадания; `dead_letters()` возвращает копию. `requeue_dead_letter(job_id)`: `store.get` (даёт `JobNotFoundError`), `_transition(job, PENDING)` (даёт `InvalidTransitionError`, если статус не `DEAD_LETTERED`), затем `run_at = now`, `error = None`, `finished_at = None`, удаление записи по `job_id` из списка, `jobs.requeued`. Все проверки идут до побочных эффектов. Запись ищется по `job_id`; у задания в `DEAD_LETTERED` она ровно одна, потому что повторное попадание возможно только после возврата, который запись удаляет.

8. **Политики в очереди.** `_default_retry_policy` и `_retry_policies: dict[str, RetryPolicy]`. `retry_policy_for` — `dict.get(job_type, default)` (политика типа заменяет дефолт целиком). Проверки типа аргумента и непустоты `job_type` — `ConfigError`. Политику читаем в момент ошибки (в воркере), а не сохраняем в задание.

9. **Логика воркера.** В `run_once`:
   - отсутствие обработчика — как раньше, `mark_failed` до любого обращения к политике;
   - при исключении: `policy = queue.retry_policy_for(job.job_type)`; `error = format_error(exc)`; `policy is None or not policy.is_retryable(exc)` → `mark_failed`; `job.attempts >= policy.max_attempts` → `mark_dead_lettered`; иначе `delay = policy.delay_for(job.attempts, self._rng)`, `run_at = queue.clock.now() + timedelta(seconds=delay)`, `mark_retry_scheduled`. `delay_for` вызывается только в последней ветке — этим гарантируется, что `rng` не трогается при `FAILED`/`DEAD_LETTERED`. `Worker.__init__` получает `rng` (keyword-only, после `name`), без `rng` передаётся `None`.
   - Ловится по-прежнему `except Exception`; `PermanentJobError` — наследник `Exception`.

10. **Метрики.** В `metrics.py` константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`; докстрока модуля дополняется.

11. **Экспорт и документация.** В `jobq/__init__.py` добавляются `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry`; в `README.md` — строка про `retry.py` и раздел про повторы.

12. **Тесты.** Новые файлы `tests/test_retry.py` (политика, `delay_for`, валидация), `tests/test_worker_retry.py` (исходы, rng, счётчики, dead-letter и requeue, purge, отчёт). Существующие тесты не меняются; используется `ManualClock` и подменный `rng` (`random.Random(seed)` или заглушка со счётчиком вызовов `uniform`).

## Risks / Trade-offs

- [Повторное падение вернувшегося задания сразу даёт dead-letter, т. к. `attempts` не сбрасывается] → следует тексту задачи, явно зафиксировано в допущениях и спеках; сброс легко добавить отдельной задачей.
- [Очень большой `max_delay` при `jitter` или сложении с `now` может выйти за пределы `timedelta`/`datetime`] → конфигурация с задержкой порядка сотен миллиардов секунд не ожидается; специальной защиты не вводим.
- [Не терминальные `DEAD_LETTERED`/`RETRY_SCHEDULED` не попадают в `failure_rate` и «Последние ошибки» отчёта] → `dashboard.py` вне зоны правок; видно в строках статусов и счётчиках.
- [Валидация NaN/бесконечностей строже текста задачи] → допущение 2 из proposal; на допустимые по задаче значения не влияет.


### proposal.md

## Why

Любое исключение обработчика сейчас сразу переводит задание в `FAILED`, и дежурные каждое утро вручную перезапускают десятки заданий, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Нужны настраиваемые повторы с экспоненциальной задержкой и отдельная dead-letter очередь для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

Публичный API (дословно из задачи):

- Новый модуль `jobq/retry.py`: `@dataclass(frozen=True) class RetryPolicy` с полями `max_attempts: int = 3`, `base_delay: float = 1.0`, `factor: float = 2.0`, `max_delay: float = 60.0`, `jitter: float = 0.0`, `non_retryable: tuple[type[BaseException], ...] = ()` (можно передать список, хранится tuple) и методами `delay_for(self, attempt: int, rng: random.Random | None = None) -> float`, `is_retryable(self, exc: BaseException) -> bool`.
- `jobq/errors.py`: `class PermanentJobError(JobqError)` — обработчик бросает её, когда точно знает, что повтор не поможет.
- `jobq/models.py`: `JobStatus.RETRY_SCHEDULED = "retry_scheduled"`, `JobStatus.DEAD_LETTERED = "dead_lettered"`; `@dataclass(frozen=True) class DeadLetterEntry` с полями `job_id: str`, `job_type: str`, `attempts: int`, `error: str`, `dead_lettered_at: datetime`.
- `jobq/queue.py`: `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy: RetryPolicy | None = None)`, `JobQueue.set_retry_policy(job_type: str, policy: RetryPolicy | None) -> None`, `JobQueue.retry_policy_for(job_type: str) -> RetryPolicy | None`, `JobQueue.dead_letters() -> list[DeadLetterEntry]`, `JobQueue.requeue_dead_letter(job_id: str) -> Job`.
- `jobq/worker.py`: `Worker(queue, registry, *, name="worker", rng: random.Random | None = None)`.
- Поведение: при падении обработчика воркер по действующей политике выбирает `FAILED` / `DEAD_LETTERED` / `RETRY_SCHEDULED`; задание в `RETRY_SCHEDULED` берётся воркером, когда наступил `run_at`.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Подписи статусов для отчёта дежурных: «Ожидает повтора» и «В dead-letter» (через `JobStatus.label`; `dashboard.py` не меняется).

Не ломается: без политики (ни дефолтной, ни по типу) поведение прежнее; сигнатуры существующих публичных методов не меняются, новые параметры только keyword-only; существующие тесты не меняются; новых зависимостей нет. `jobq/dashboard.py` и `jobq/cli.py` не трогаем.

## Capabilities

### New Capabilities
- `retry-policy`: параметры и валидация `RetryPolicy`, расчёт задержки (`delay_for`, без переполнения), классификация ошибок (`is_retryable`, `PermanentJobError`), назначение политики очереди и типу задания.
- `job-retries`: что воркер делает при падении обработчика (FAILED / DEAD_LETTERED / RETRY_SCHEDULED), планирование `run_at`, использование `rng`, выборка заданий в `RETRY_SCHEDULED`, счётчик `jobs.retried`, статусы и подписи.
- `dead-letter`: `dead_letters()`, `requeue_dead_letter`, счётчики `jobs.dead_lettered` и `jobs.requeued`, сохранность заданий в dead-letter.

### Modified Capabilities

Нет: основных спеков в `openspec/specs/` пока нет, изменений существующих требований нет.

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/metrics.py`, `jobq/store.py` (условие «готово к запуску»), `jobq/queue.py`, `jobq/worker.py`, `jobq/__init__.py` (экспорт новых имён), `README.md` (модули и соглашения).
- Тесты: только новые файлы; существующие не меняются.
- Зависимости: нет. `dashboard.py` получает новые строки статусов автоматически (цикл по `JobStatus`), сам не правится.

## Допущения (приняты автономно, пользователь недоступен)

1. Все ошибки конфигурации политики и `attempt < 1` в `delay_for` — `ConfigError` (проект выбрасывает только наследников `JobqError`). Неверный тип политики в `set_retry_policy` / `default_retry_policy` (не `RetryPolicy` и не `None`) или пустой `job_type` — тоже `ConfigError`.
2. NaN и бесконечные значения в `base_delay`, `factor`, `max_delay`, `jitter` считаются некорректными (`ConfigError`); `max_attempts` должен быть `int` (не `bool`).
3. `DEAD_LETTERED` и `RETRY_SCHEDULED` не считаются терминальными (`is_terminal` = `False`): из dead-letter есть выход, а `purge_finished` не должен удалять такие задания (иначе записи dead-letter указывали бы на несуществующее задание).
4. `cancel` разрешён для `RETRY_SCHEDULED` (задание ещё не выполняется) и запрещён для `DEAD_LETTERED` (единственный выход — `requeue_dead_letter`).
5. `requeue_dead_letter` не сбрасывает `attempts`; `finished_at` очищается. Поэтому при политике с конечным `max_attempts` повторное падение вернувшегося задания снова даст `DEAD_LETTERED`. Это следует тексту задачи (перечислены только статус, `run_at`, `error`, запись dead-letter) и фиксируется как известное следствие.
6. `requeue_dead_letter` для неизвестного id — `JobNotFoundError`; для задания не в `DEAD_LETTERED` — `InvalidTransitionError`.
7. `failure_rate` в `dashboard.py` не меняется и `DEAD_LETTERED` не учитывает.


### specs/dead-letter/spec.md

## Purpose

Описывает dead-letter очередь: учёт заданий, исчерпавших попытки, просмотр записей и осознанный возврат заданий в работу.

## ADDED Requirements

### Requirement: Запись DeadLetterEntry и просмотр dead_letters
`DeadLetterEntry` в `jobq/models.py` SHALL быть неизменяемым dataclass с полями `job_id: str`, `job_type: str`, `attempts: int`, `error: str`, `dead_lettered_at: datetime`. `JobQueue.dead_letters() -> list[DeadLetterEntry]` SHALL возвращать записи в порядке попадания в dead-letter; изменение возвращённого списка SHALL NOT влиять на очередь. Запись создаётся при переходе задания в `DEAD_LETTERED` со значениями `attempts` и `error` задания и временем очереди в `dead_lettered_at`. Единственный способ убрать запись — `requeue_dead_letter`.

#### Scenario: Содержимое записи
- **WHEN** задание типа `"mail"` исчерпало 3 попытки с последней ошибкой `TimeoutError: gw` в момент `T`
- **THEN** `dead_letters()` содержит `DeadLetterEntry(job_id=<id>, job_type="mail", attempts=3, error="TimeoutError: gw", dead_lettered_at=T)`

#### Scenario: Порядок попадания
- **WHEN** сначала в dead-letter попало задание A, затем B
- **THEN** `dead_letters()` возвращает записи `[A, B]`

#### Scenario: Пустой dead-letter
- **WHEN** ни одно задание не исчерпало попытки
- **THEN** `dead_letters()` возвращает пустой список

#### Scenario: Копия списка
- **WHEN** вызывающий очищает возвращённый список
- **THEN** следующий `dead_letters()` по-прежнему возвращает все записи

### Requirement: Возврат из dead-letter
`JobQueue.requeue_dead_letter(job_id: str) -> Job` SHALL возвращать в работу то же задание (новое не создаётся, `id` и `seq` те же): статус `PENDING`, `run_at` = текущее время очереди, `error = None`, `finished_at = None`, запись о задании удаляется из `dead_letters()`; `attempts` не сбрасывается. Для неизвестного `job_id` SHALL выбрасываться `JobNotFoundError`; для задания, не находящегося в `DEAD_LETTERED`, — `InvalidTransitionError`. Других выходов из `DEAD_LETTERED` (в том числе `cancel`) нет.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter(job_id)` для задания в `DEAD_LETTERED` в момент `T`
- **THEN** возвращается то же задание (тот же объект в хранилище) со статусом `PENDING`, `run_at == T`, `error is None`; `dead_letters()` больше не содержит его; число заданий в хранилище не изменилось

#### Scenario: Возвращённое задание выполняется
- **WHEN** после возврата вызывается `worker.run_once()` и обработчик теперь успешен
- **THEN** задание получает `SUCCEEDED`

#### Scenario: Задание не в dead-letter
- **WHEN** вызывается `requeue_dead_letter` для задания в статусе `FAILED`, `PENDING` или повторно для уже возвращённого
- **THEN** выбрасывается `InvalidTransitionError`, состояние не меняется

#### Scenario: Неизвестный id
- **WHEN** вызывается `requeue_dead_letter("job-999999")`
- **THEN** выбрасывается `JobNotFoundError`

#### Scenario: Отмена недоступна
- **WHEN** вызывается `cancel` для задания в `DEAD_LETTERED`
- **THEN** выбрасывается `InvalidTransitionError`

#### Scenario: Повторное попадание
- **WHEN** возвращённое задание снова исчерпало попытки
- **THEN** в конец `dead_letters()` добавляется новая запись

### Requirement: Счётчики jobs.dead_lettered и jobs.requeued
Счётчик `jobs.dead_lettered` SHALL увеличиваться на 1 ровно в момент перехода задания в `DEAD_LETTERED`, а `jobs.requeued` — на 1 ровно при успешном `requeue_dead_letter`. При ошибке `requeue_dead_letter` счётчики не меняются. Неизвестные счётчики по-прежнему читаются как 0, а `metrics.snapshot()` показывает только ненулевые.

#### Scenario: Подсчёт
- **WHEN** задание ушло в dead-letter, затем возвращено
- **THEN** `jobs.dead_lettered == 1`, `jobs.requeued == 1`

#### Scenario: Неудачный возврат
- **WHEN** `requeue_dead_letter` завершился ошибкой
- **THEN** `jobs.requeued` не изменился


### specs/job-retries/spec.md

## Purpose

Описывает, как воркер реагирует на падение обработчика при наличии политики повторов: выбор итогового статуса, планирование следующей попытки, использование генератора случайных чисел, новые статусы и счётчик повторов.

## ADDED Requirements

### Requirement: Новые статусы заданий
`JobStatus` SHALL содержать значения `RETRY_SCHEDULED = "retry_scheduled"` и `DEAD_LETTERED = "dead_lettered"` с подписями для отчёта дежурных `«Ожидает повтора»` и `«В dead-letter»` соответственно. `queue.stats()` SHALL включать новые статусы по их значениям. Оба статуса SHALL NOT считаться терминальными (`is_terminal == False`), и `purge_finished` SHALL NOT удалять задания в этих статусах. `dashboard.py` и `cli.py` не изменяются.

#### Scenario: Значения и подписи
- **WHEN** читаются `JobStatus.RETRY_SCHEDULED.value`, `JobStatus.DEAD_LETTERED.value` и их `label`
- **THEN** получаем `"retry_scheduled"`, `"dead_lettered"`, `"Ожидает повтора"`, `"В dead-letter"`

#### Scenario: Статусы в отчёте и stats
- **WHEN** строится `stats()` и `render_report(queue)`
- **THEN** в `stats()` есть ключи `"retry_scheduled"` и `"dead_lettered"`, а в отчёте — строки с подписями «Ожидает повтора» и «В dead-letter»

#### Scenario: Очистка не трогает ожидающие и dead-letter
- **WHEN** есть задания в `RETRY_SCHEDULED` и `DEAD_LETTERED`, вызывается `purge_finished()`
- **THEN** они остаются в хранилище

### Requirement: Исход упавшего задания
Когда обработчик бросил исключение `exc`, воркер SHALL определить политику через `queue.retry_policy_for(job.job_type)` на момент ошибки (а не на момент постановки) и перевести задание так:
1. политики нет — `FAILED`, как до изменения;
2. `policy.is_retryable(exc)` ложно — `FAILED`, даже если это последняя попытка; в dead-letter такое задание не попадает;
3. иначе, если `job.attempts >= policy.max_attempts` — `DEAD_LETTERED` и появляется запись в `dead_letters()`;
4. иначе — `RETRY_SCHEDULED` с `run_at` = текущее время очереди + `policy.delay_for(job.attempts, rng)`.

Во всех случаях `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. Отсутствие обработчика для типа задания SHALL приводить к `FAILED` сразу, без повторов и независимо от политики.

#### Scenario: Повтор после временной ошибки
- **WHEN** политика `RetryPolicy(max_attempts=3, base_delay=2, factor=2, jitter=0)`, обработчик бросил `TimeoutError("gw")` на первой попытке в момент `T`
- **THEN** статус `RETRY_SCHEDULED`, `run_at == T + 2 с`, `error == "TimeoutError: gw"`, `attempts == 1`

#### Scenario: Задержка растёт с номером попытки
- **WHEN** вторая попытка упала в момент `T2` при той же политике
- **THEN** `run_at == T2 + 4 с`

#### Scenario: Попытки кончились
- **WHEN** `max_attempts=3` и упала третья попытка
- **THEN** статус `DEAD_LETTERED`, в `dead_letters()` одна запись для этого задания, `error` — последняя ошибка

#### Scenario: max_attempts=1 означает без повторов, но в dead-letter
- **WHEN** `max_attempts=1` и первая попытка упала повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка всегда FAILED
- **WHEN** `non_retryable=(ValueError,)` и обработчик бросил наследника `ValueError` — на первой или на последней попытке
- **THEN** статус `FAILED`, записи в dead-letter нет

#### Scenario: PermanentJobError
- **WHEN** обработчик бросил `PermanentJobError("no")` при любой политике
- **THEN** статус `FAILED`

#### Scenario: Нет политики
- **WHEN** нет ни дефолтной политики, ни политики типа и обработчик упал
- **THEN** статус `FAILED`, `error` заполнен, повторов нет

#### Scenario: Нет обработчика
- **WHEN** для типа задания не зарегистрирован обработчик, политика задана
- **THEN** статус `FAILED` сразу, `RETRY_SCHEDULED` и dead-letter не используются

#### Scenario: Политика берётся на момент ошибки
- **WHEN** после постановки задания, но до его падения, политика типа изменена или снята
- **THEN** исход определяется новой действующей политикой

### Requirement: Использование rng воркером
`Worker.__init__` SHALL принимать keyword-only параметр `rng: random.Random | None = None` (после `name`), существующие вызовы остаются валидными. Воркер SHALL передавать `rng` в `delay_for` только когда реально планирует повтор: при `FAILED` и `DEAD_LETTERED` задержка не считается и `rng` не используется; при `jitter == 0` `rng` не используется; при `jitter > 0` на один запланированный повтор приходится ровно один вызов `rng.uniform`.

#### Scenario: Предсказуемый rng
- **WHEN** `jitter=0.5`, воркер создан с `rng`, запланирован один повтор
- **THEN** `rng.uniform` вызван ровно один раз, а `run_at` равен сейчас плюс ограниченная задержка, умноженная на его результат

#### Scenario: rng не трогается без повтора
- **WHEN** задание ушло в `FAILED` или `DEAD_LETTERED`, либо `jitter == 0`
- **THEN** `rng` не использован

### Requirement: Выбор заданий в RETRY_SCHEDULED
Воркер SHALL брать задание в `RETRY_SCHEDULED`, когда `run_at <= now`, наравне с `PENDING` по общему порядку `(run_at, seq)`; раньше `run_at` задание не берётся. Взятое задание проходит обычный запуск (`attempts` увеличивается, статус `RUNNING`). При успехе статус становится `SUCCEEDED`, а `error` — `None`. Задание в `RETRY_SCHEDULED` можно отменить (`cancel`).

#### Scenario: Ожидание run_at
- **WHEN** задание в `RETRY_SCHEDULED` с `run_at = T + 2 с`, текущее время `T + 1 с`
- **THEN** `worker.run_once()` возвращает `None`; после `clock.advance` до `T + 2 с` задание выполняется

#### Scenario: Успех после повтора
- **WHEN** первая попытка упала, вторая прошла успешно
- **THEN** статус `SUCCEEDED`, `attempts == 2`, `error is None`

#### Scenario: Общий порядок
- **WHEN** готовы задания `PENDING` и `RETRY_SCHEDULED`
- **THEN** первым берётся то, у которого меньше `(run_at, seq)`

#### Scenario: Отмена ожидающего повтора
- **WHEN** вызывается `cancel` для задания в `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`

### Requirement: Счётчик jobs.retried
Счётчик `jobs.retried` SHALL увеличиваться ровно на 1 в момент перехода задания в `RETRY_SCHEDULED` (как существующие счётчики статусов) и больше нигде. Остальные счётчики (`jobs.started`, `jobs.failed`, `jobs.succeeded` и т. д.) работают как прежде; `jobs.failed` не растёт при переходе в `RETRY_SCHEDULED` и `DEAD_LETTERED`.

#### Scenario: Подсчёт
- **WHEN** задание падает дважды с повтором и затем успешно выполняется
- **THEN** `jobs.retried == 2`, `jobs.started == 3`, `jobs.succeeded == 1`, `jobs.failed == 0`


### specs/retry-policy/spec.md

## Purpose

Описывает настраиваемую политику повторов (`RetryPolicy`): параметры, их проверку, расчёт задержки между попытками, классификацию ошибок на повторяемые и неповторяемые, а также назначение политики очереди и типу задания.

## ADDED Requirements

### Requirement: Параметры RetryPolicy и их проверка
`RetryPolicy` в `jobq/retry.py` SHALL быть неизменяемым dataclass с полями `max_attempts: int = 3` (всего попыток, включая первую), `base_delay: float = 1.0`, `factor: float = 2.0`, `max_delay: float = 60.0` (секунды), `jitter: float = 0.0` и `non_retryable: tuple[type[BaseException], ...] = ()`. Значение `non_retryable` можно передать списком; оно SHALL храниться как `tuple`. Некорректные параметры SHALL приводить к `ConfigError` при создании политики: `max_attempts < 1` (или не `int`), `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, NaN или бесконечные значения вещественных полей, элемент `non_retryable`, не являющийся классом-наследником `BaseException`.

#### Scenario: Значения по умолчанию
- **WHEN** создаётся `RetryPolicy()`
- **THEN** `max_attempts == 3`, `base_delay == 1.0`, `factor == 2.0`, `max_delay == 60.0`, `jitter == 0.0`, `non_retryable == ()`

#### Scenario: Список non_retryable хранится как tuple
- **WHEN** создаётся `RetryPolicy(non_retryable=[ValueError, KeyError])`
- **THEN** `policy.non_retryable == (ValueError, KeyError)` и это `tuple`

#### Scenario: Некорректные параметры отвергаются
- **WHEN** создаётся `RetryPolicy` с `max_attempts=0`, либо `base_delay=-1`, либо `factor=0.5`, либо `base_delay=5, max_delay=1`, либо `jitter=1.5` (или `-0.1`), либо `non_retryable=(int,)`, либо `non_retryable=("ValueError",)`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Граничные значения допустимы
- **WHEN** создаётся `RetryPolicy(max_attempts=1, base_delay=0, factor=1, max_delay=0, jitter=1)`
- **THEN** политика создаётся без ошибки

### Requirement: Расчёт задержки delay_for
`RetryPolicy.delay_for(attempt: int, rng: random.Random | None = None) -> float` SHALL возвращать задержку перед следующей попыткой, если упала попытка номер `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)` — ровно один вызов `uniform` на одну задержку; при `jitter == 0` генератор SHALL NOT использоваться. Если `rng` не передан, SHALL использоваться генератор по умолчанию. Метод SHALL работать для любого `attempt >= 1` (включая очень большие, например `5000` и больше, и `base_delay == 0`) без `OverflowError`; при `attempt < 1` SHALL выбрасываться `ConfigError`.

#### Scenario: Экспоненциальный рост с ограничением
- **WHEN** политика `RetryPolicy(base_delay=1, factor=2, max_delay=10)`
- **THEN** `delay_for(1) == 1`, `delay_for(2) == 2`, `delay_for(3) == 4`, `delay_for(5) == 10`

#### Scenario: Огромный номер попытки
- **WHEN** вызывается `RetryPolicy(max_attempts=10000, max_delay=60).delay_for(5000)`
- **THEN** результат равен `60.0` и `OverflowError` не возникает

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(5000)` (и `delay_for(1)`)
- **THEN** результат равен `0.0`

#### Scenario: factor равен 1
- **WHEN** `factor=1`, `base_delay=3`
- **THEN** `delay_for(n) == 3` для любого `n`

#### Scenario: Джиттер применяется после ограничения
- **WHEN** `jitter=0.5`, `base_delay=1`, `max_delay=10`, `attempt=10` и `rng.uniform(0.5, 1.5)` возвращает `1.2`
- **THEN** результат равен `12.0` (то есть `10 * 1.2`), а `uniform` вызван один раз с аргументами `(0.5, 1.5)`

#### Scenario: Без джиттера генератор не трогается
- **WHEN** `jitter=0` и передан `rng`
- **THEN** ни один метод `rng` не вызывается

#### Scenario: Некорректный номер попытки
- **WHEN** вызывается `delay_for(0)` или `delay_for(-1)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок is_retryable
`RetryPolicy.is_retryable(exc: BaseException) -> bool` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда `False` для `PermanentJobError`. Для остальных исключений SHALL возвращаться `True`. В `jobq/errors.py` SHALL быть класс `PermanentJobError(JobqError)`.

#### Scenario: Наследники неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и ошибка — `UnicodeError` (наследник `ValueError`) или `ValueError`
- **THEN** `is_retryable` возвращает `False`

#### Scenario: Прочие ошибки повторяемы
- **WHEN** `non_retryable=(ValueError,)` и ошибка — `TimeoutError`
- **THEN** `is_retryable` возвращает `True`

#### Scenario: PermanentJobError никогда не повторяется
- **WHEN** `non_retryable=()` и ошибка — `PermanentJobError("no")`
- **THEN** `is_retryable` возвращает `False`

### Requirement: Назначение политик очереди и типам заданий
`JobQueue.__init__` SHALL принимать keyword-only параметр `default_retry_policy: RetryPolicy | None = None`. `JobQueue.set_retry_policy(job_type: str, policy: RetryPolicy | None) -> None` SHALL задавать политику типа; `None` SHALL снимать политику типа. `JobQueue.retry_policy_for(job_type: str) -> RetryPolicy | None` SHALL возвращать действующую политику: политику типа, если она задана, иначе дефолт очереди, иначе `None`. Политика типа заменяет дефолт целиком, поля не сливаются. Значение, не являющееся `RetryPolicy` или `None`, а также пустой `job_type` SHALL приводить к `ConfigError`. Вызовы `JobQueue(...)` без нового параметра SHALL работать как раньше.

#### Scenario: Приоритет политик
- **WHEN** у очереди дефолт `A`, для типа `"mail"` задана `B`
- **THEN** `retry_policy_for("mail") is B`, а `retry_policy_for("billing") is A`

#### Scenario: Политика типа заменяет дефолт целиком
- **WHEN** дефолт `RetryPolicy(non_retryable=(ValueError,))`, а для типа задана `RetryPolicy()`
- **THEN** `retry_policy_for(тип).non_retryable == ()`

#### Scenario: Снятие политики типа
- **WHEN** вызывается `set_retry_policy("mail", None)` после назначения политики
- **THEN** `retry_policy_for("mail")` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Политик нет
- **WHEN** нет ни дефолта, ни политики типа
- **THEN** `retry_policy_for(тип)` возвращает `None`

#### Scenario: Неверный аргумент
- **WHEN** вызывается `set_retry_policy("mail", "x")` или `JobQueue(default_retry_policy=5)`
- **THEN** выбрасывается `ConfigError`


### tasks.md

## 1. Базовые типы

- [ ] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` в новом тесте
- [ ] 1.2 Добавить в `jobq/models.py` статусы `RETRY_SCHEDULED`/`DEAD_LETTERED` (в конец enum), подписи «Ожидает повтора» и «В dead-letter», нетерминальность, и frozen dataclass `DeadLetterEntry`; проверить тестом значений, подписей, `is_terminal` и неизменяемости записи
- [ ] 1.3 Добавить счётчики `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `jobq/metrics.py` и дополнить докстроку; проверить, что `Metrics().get("jobs.retried") == 0`

## 2. RetryPolicy

- [ ] 2.1 Создать `jobq/retry.py` с `RetryPolicy` (поля и значения по умолчанию из proposal), валидацией в `__post_init__` и приведением `non_retryable` к tuple; проверить тестами по сценариям «Параметры RetryPolicy» (умолчания, список → tuple, каждый вид некорректных параметров → `ConfigError`, граничные значения)
- [ ] 2.2 Реализовать `delay_for` (ограничение `max_delay`, джиттер после ограничения, один `uniform` только при `jitter > 0`, `base_delay == 0`, `factor == 1`, защита от `OverflowError`, `attempt < 1` → `ConfigError`); проверить тестами, включая `attempt=5000` и `attempt=10**6`, `base_delay=0`, заглушку `rng` со счётчиком вызовов
- [ ] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError`); проверить тестами по сценариям классификации

## 3. Очередь

- [ ] 3.1 Обновить `_TRANSITIONS` в `jobq/queue.py` (RETRY_SCHEDULED → RUNNING/CANCELLED, RUNNING → +RETRY_SCHEDULED/DEAD_LETTERED, DEAD_LETTERED → PENDING) и `InMemoryJobStore.due` (PENDING и RETRY_SCHEDULED); проверить тестами: ждёт до `run_at`, общий порядок `(run_at, seq)`, `cancel` из RETRY_SCHEDULED проходит, из DEAD_LETTERED — `InvalidTransitionError`, `purge_finished` их не удаляет
- [ ] 3.2 Добавить `default_retry_policy` (keyword-only), `set_retry_policy`, `retry_policy_for` с проверками типов (`ConfigError`); проверить тестами: приоритет, замена целиком без слияния, снятие `None`, старый вызов `JobQueue(...)` без параметра
- [ ] 3.3 Добавить `mark_retry_scheduled`, `mark_dead_lettered`, `dead_letters` (копия, порядок попадания), `requeue_dead_letter` (то же задание, PENDING, `run_at=now`, `error=None`, `finished_at=None`, запись удалена, ошибки `JobNotFoundError`/`InvalidTransitionError` без побочных эффектов) со счётчиками; проверить тестами по сценариям спека `dead-letter`

## 4. Воркер

- [ ] 4.1 Добавить `rng` (keyword-only после `name`) в `Worker` и ветвление исхода в `run_once`: нет политики / неповторяемая → FAILED, `attempts >= max_attempts` → DEAD_LETTERED, иначе RETRY_SCHEDULED с `run_at = now + delay_for(attempts, rng)`; отсутствие обработчика → FAILED до обращения к политике; проверить тестами по сценариям «Исход упавшего задания» (`max_attempts=1`, последняя попытка с неповторяемой ошибкой, политика меняется после enqueue, подклассы `non_retryable`)
- [ ] 4.2 Проверить тестами с заглушкой `rng`: ровно один `uniform` на запланированный повтор при `jitter > 0` и ни одного при `FAILED`, `DEAD_LETTERED` и `jitter == 0`
- [ ] 4.3 Сквозные тесты: упало дважды и прошло с третьей попытки (`error is None`, `attempts == 3`), счётчики `jobs.retried/dead_lettered/requeued/failed/started`, возврат из dead-letter и успешное выполнение, строки статусов в `render_report` (без правки `dashboard.py`)

## 5. Экспорт и документация

- [ ] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py` и обновить `README.md` (таблица модулей, раздел о повторах и dead-letter); проверить `from jobq import RetryPolicy, PermanentJobError, DeadLetterEntry`

## 6. Проверка

- [ ] 6.1 Запустить `python -m pytest -q`: все существующие тесты проходят без изменений, `git diff --stat` не показывает `jobq/dashboard.py`, `jobq/cli.py` и существующих файлов в `tests/`
- [ ] 6.2 Сверить публичный API реализации с proposal и specs: `RetryPolicy` (поля, значения по умолчанию, `delay_for`, `is_retryable`), `PermanentJobError`, `JobStatus.RETRY_SCHEDULED`/`DEAD_LETTERED` и их значения/подписи, `DeadLetterEntry` (поля), `JobQueue(...)` с `default_retry_policy`, `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`, `Worker(..., name, rng)`, имена счётчиков; проверить через `inspect.signature` и ручной просмотр, расхождения исправить
