### design.md

## Context

Сейчас воркер (`jobq/worker.py`) при любом `Exception` вызывает `queue.mark_failed`. Статусы меняются только через `JobQueue._transition` по таблице `_TRANSITIONS`; `InMemoryJobStore.due()` отдаёт только `PENDING`; `dashboard.render_report` перебирает все `JobStatus` и берёт подписи из `JobStatus.label`, поэтому новые статусы появятся в отчёте без правок `dashboard.py` (он закрыт для нас). Требования — в `specs/job-retry` и `specs/dead-letter`, мотивация — в `proposal.md`.

## Goals / Non-Goals

**Goals:**
- Вся логика решения «FAILED / повтор / dead-letter» в одном месте (воркер), вся смена статусов — в очереди.
- `delay_for` без `OverflowError` для любого `attempt`.

**Non-Goals:**
- Персистентность dead-letter (хранилище только в памяти), правки `dashboard.py`/`cli.py`, учёт новых статусов в `failure_rate`.
- Автоматическое возобновление из dead-letter, сброс счётчика попыток при возврате.

## Decisions

1. **`RetryPolicy` — frozen dataclass с валидацией в `__post_init__`**; `non_retryable` нормализуется через `object.__setattr__(self, "non_retryable", tuple(...))`. Проверки записаны в форме «не (допустимо)», чтобы NaN отвергался. Элемент валиден, если `isinstance(x, type) and issubclass(x, BaseException)`. Ошибки — `ConfigError`. Тип `max_attempts` должен быть `int` (не `bool`).
2. **Устойчивый `delay_for`.** Порядок: проверить `attempt >= 1`; если `base_delay == 0` — база `0.0`; иначе считать `base_delay * factor ** (attempt - 1)` в `try`, при `OverflowError` брать `max_delay`; затем `min(.., max_delay)`. При `factor == 1` степень не считается. Для `int`-фактора степень приводить к `float` внутри `try`, чтобы огромный `int` не падал при умножении. Только после ограничения применяется jitter: `delay * rng.uniform(1 - jitter, 1 + jitter)`; при `jitter == 0` `rng` не трогается; при `rng is None` берётся модульный `random`. Альтернатива (ограничивать `attempt` заранее) отвергнута: зависит от `factor`.
3. **Решение принимает воркер, смену статуса — очередь.** В очереди появляются `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)`; каждая делает `_transition`, пишет `error`, увеличивает свой счётчик (`jobs.retried` / `jobs.dead_lettered`) и, для dead-letter, добавляет `DeadLetterEntry`. Воркер вызывает `queue.retry_policy_for(job.job_type)` в момент ошибки (даёт «действует политика на момент ошибки»). `rng` у воркера по умолчанию `random.Random()`; `delay_for` вызывается только в ветке повтора.
4. **Порядок проверок в воркере**: нет обработчика → `FAILED` (до всякой политики); нет политики или `not is_retryable` → `FAILED`; `job.attempts >= max_attempts` → `DEAD_LETTERED`; иначе `RETRY_SCHEDULED` с `run_at = clock.now() + timedelta(seconds=delay_for(job.attempts, rng))`.
5. **Таблица переходов**: `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`, `RETRY_SCHEDULED → {RUNNING, CANCELLED}`, `DEAD_LETTERED → {PENDING}` (только из `requeue_dead_letter`). `mark_running` из `RETRY_SCHEDULED` работает как из `PENDING`.
6. **Готовность к запуску.** `InMemoryJobStore.due()` включает `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`.
7. **Dead-letter хранится в очереди** как список `DeadLetterEntry` (порядок попадания), `dead_letters()` возвращает копию. Альтернатива — вычислять из `list_jobs(DEAD_LETTERED)` — отвергнута: порядок попадания не равен порядку `seq`, и нужны `dead_lettered_at`.
8. **`requeue_dead_letter`**: берёт задание (`JobNotFoundError`), проверяет наличие записи/статус до любых изменений (иначе `InvalidTransitionError` через `_transition`), затем переход в `PENDING`, `run_at = now`, `error = None`, удаление записи, `jobs.requeued`. `finished_at`/`started_at` не меняются. Атомарность: проверка до мутаций.
9. **Терминальность.** `RETRY_SCHEDULED` и `DEAD_LETTERED` не входят в `_TERMINAL`, значит `purge_finished` их не удаляет; запись dead-letter не может «повиснуть». `finished_at` для них не выставляется.
10. **Подписи и метрики.** Новые подписи в `_LABELS`, константы в `metrics.py`, дополнить его docstring. Экспорт `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`.
11. **Совместимость.** `JobQueue.__init__` и `Worker.__init__` получают только keyword-only параметры с `None` по умолчанию; без политики ветка воркера идентична прежней.

## Допущения (в тикете не определено)

- `attempts` при `requeue_dead_letter` не сбрасывается (в тикете перечислены изменяемые поля). Следствие: если политика прежняя, повторно возвращённое задание при первом же падении снова попадёт в dead-letter. Сброс можно добавить отдельным тикетом.
- Отмена (`cancel`) разрешена для `RETRY_SCHEDULED` (задание не выполняется) и запрещена для `DEAD_LETTERED` («выход один»).
- `requeue_dead_letter` для задания не в dead-letter → `InvalidTransitionError`; для неизвестного id → `JobNotFoundError`.
- `is_terminal` у новых статусов ложно; `failure_rate` не учитывает dead-letter (файл не наш).
- Сообщение об ошибке для обоих исходов берётся через `format_error`.

## Risks / Trade-offs

- [Очень большой `max_delay` (например `1e20`) делает `timedelta` непредставимым → `OverflowError` в воркере] → в воркере ограничить секунды величиной, допустимой для `timedelta`, либо ловить `OverflowError` и брать `timedelta.max`-безопасное значение; покрыть тестом.
- [Jitter может поднять задержку выше `max_delay` (до `max_delay * (1 + jitter)`)] → это прямо указано в тикете, фиксируется тестом.
- [`failure_rate` и отчёт «Последние ошибки» не показывают dead-letter] → ограничение владельца dashboard; передать другой команде.
- [Dead-letter теряется при перезапуске процесса] → как и всё хранилище; вне объёма.


### proposal.md

## Why

Любое исключение обработчика сразу переводит задание в `FAILED`, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Дежурные каждое утро вручную перезапускают десятки заданий. Нужны настраиваемые повторы с экспоненциальной задержкой и отдельное место (dead-letter) для заданий, которые так и не выполнились. Тикет: JOBQ-212.

## What Changes

- Новый модуль с политикой повторов `RetryPolicy` (число попыток, экспоненциальная задержка с ограничением и jitter, список неповторяемых исключений) и расчётом задержки без переполнения для любого номера попытки.
- Новая ошибка `PermanentJobError`: обработчик бросает её, когда повтор точно не поможет.
- Новые статусы `RETRY_SCHEDULED` («Ожидает повтора») и `DEAD_LETTERED` («В dead-letter»), запись `DeadLetterEntry`.
- Политика задаётся по умолчанию для очереди и отдельно для типа задания; политика типа заменяет дефолт целиком; действует политика на момент ошибки.
- Воркер при падении обработчика выбирает: `FAILED` (ошибка неповторяемая или политики нет), `DEAD_LETTERED` (попытки кончились) или `RETRY_SCHEDULED` с `run_at = now + delay`. Задания в `RETRY_SCHEDULED` берутся в работу по наступлении `run_at`.
- `JobQueue.dead_letters()` и `JobQueue.requeue_dead_letter()` — единственный выход из dead-letter.
- Счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Без политики поведение не меняется. Все новые параметры keyword-only; `dashboard.py` и `cli.py` не меняются (новые статусы попадают в отчёт через подписи `JobStatus.label`).

## Capabilities

### New Capabilities
- `job-retry`: политика повторов, расчёт задержки, классификация ошибок, выбор политики, решение воркера при падении задания, счётчик `jobs.retried`.
- `dead-letter`: статус `DEAD_LETTERED`, список dead-letter, возврат в работу, счётчики `jobs.dead_lettered` и `jobs.requeued`.

### Modified Capabilities

(В `openspec/specs` пока нет спецификаций, поэтому всё описано как новые требования.)

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/metrics.py`, `jobq/queue.py`, `jobq/store.py` (выборка готовых заданий включает `RETRY_SCHEDULED`), `jobq/worker.py`, `jobq/__init__.py` (экспорты), `README.md`.
- Не затрагиваются: `jobq/dashboard.py`, `jobq/cli.py`, существующие тесты. Новых зависимостей нет.
- Видимое изменение: `queue.stats()` и отчёт дежурных получают две новые строки статусов (существующие тесты проверяют только набор ключей `JobStatus`, они остаются верными).


### specs/dead-letter/spec.md

## Purpose

Хранение заданий, исчерпавших попытки, в отдельном списке и осознанный возврат их в работу оператором.

## ADDED Requirements

### Requirement: Запись в dead-letter
При переходе задания в `DEAD_LETTERED` очередь SHALL добавить `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)`, где `attempts` — число попыток задания, `error` — последняя ошибка, `dead_lettered_at` — время по часам очереди. `dead_letters()` SHALL возвращать копию списка записей в порядке попадания. Счётчик `jobs.dead_lettered` SHALL увеличиваться ровно в момент перехода, `jobs.failed` при этом не меняется.

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
`requeue_dead_letter(job_id)` SHALL вернуть в работу то же задание (новое не создаётся): статус `PENDING`, `run_at` равен текущему времени, `error` очищен (`None`), запись удалена из `dead_letters()`; `attempts`, `payload` и `id` сохраняются. Метод SHALL возвращать задание и увеличивать `jobs.requeued` на 1. Для неизвестного id SHALL выбрасываться `JobNotFoundError`, для задания не в `DEAD_LETTERED` — `InvalidTransitionError`, при этом состояние не меняется. Других выходов из `DEAD_LETTERED` (отмена, запуск, повторный перевод) не существует.

#### Scenario: Успешный возврат
- **WHEN** вызывается `requeue_dead_letter` для задания в dead-letter
- **THEN** то же задание в `PENDING`, `run_at` равен now, `error` пуст, `dead_letters()` не содержит записи, `jobs.requeued` вырос на 1

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


### specs/job-retry/spec.md

## Purpose

Повторное выполнение заданий, упавших из-за временных ошибок: настраиваемая политика с экспоненциальной задержкой, выбор политики и решение воркера о судьбе упавшего задания.

## ADDED Requirements

### Requirement: Валидация параметров политики
Система SHALL отклонять некорректную `RetryPolicy` ошибкой конфигурации (`ConfigError`) при создании: `max_attempts < 1`, `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент `non_retryable`, не являющийся классом исключения. Параметр `non_retryable` SHALL приниматься в виде любой последовательности (в том числе списка) и храниться как неизменяемый кортеж. Значения по умолчанию: `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()`.

#### Scenario: Некорректное число попыток
- **WHEN** создаётся политика с `max_attempts=0`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Максимальная задержка меньше базовой
- **WHEN** создаётся политика с `base_delay=5` и `max_delay=4`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Jitter вне диапазона
- **WHEN** создаётся политика с `jitter=1.5` или `jitter=-0.1`
- **THEN** выбрасывается `ConfigError`

#### Scenario: Неисключение в non_retryable
- **WHEN** в `non_retryable` передан объект, не являющийся классом-наследником `BaseException` (например, строка `"ValueError"` или экземпляр исключения)
- **THEN** выбрасывается `ConfigError`

#### Scenario: Список превращается в кортеж
- **WHEN** в `non_retryable` передан список `[ValueError]`
- **THEN** политика хранит `(ValueError,)`

### Requirement: Расчёт задержки
`delay_for(attempt)` SHALL возвращать задержку перед следующей попыткой после падения попытки номер `attempt` (нумерация с 1) как `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`. При `jitter > 0` уже ограниченная задержка SHALL умножаться на `rng.uniform(1 - jitter, 1 + jitter)` ровно одним обращением к `rng` на вызов; при `jitter == 0` `rng` SHALL NOT использоваться. `attempt < 1` SHALL приводить к `ConfigError`. Функция SHALL работать для любого `attempt` без `OverflowError`: слишком большая степень даёт `max_delay`, а при `base_delay == 0` результат равен `0`.

#### Scenario: Экспоненциальный рост с ограничением
- **WHEN** `base_delay=1`, `factor=2`, `max_delay=60`
- **THEN** `delay_for(1)=1`, `delay_for(4)=8`, `delay_for(10)=60`

#### Scenario: Огромный номер попытки
- **WHEN** вызывается `delay_for(5001)` при `factor=2.0` и `max_delay=60`
- **THEN** возвращается `60` без исключения

#### Scenario: Нулевая базовая задержка
- **WHEN** `base_delay=0` и вызывается `delay_for(10000)`
- **THEN** возвращается `0`

#### Scenario: Jitter применяется после ограничения
- **WHEN** `jitter=0.5`, задержка до jitter ограничена `max_delay=60`, а `rng.uniform(0.5, 1.5)` вернул `1.5`
- **THEN** результат равен `90`

#### Scenario: Без jitter rng не трогается
- **WHEN** `jitter=0` и передан `rng`
- **THEN** состояние `rng` не меняется

#### Scenario: Номер попытки меньше 1
- **WHEN** вызывается `delay_for(0)`
- **THEN** выбрасывается `ConfigError`

### Requirement: Классификация ошибок
`is_retryable(exc)` SHALL возвращать `False` для исключений, являющихся экземплярами любого класса из `non_retryable` (с учётом наследования, как обычный `except`), и всегда для `PermanentJobError` и её наследников, независимо от `non_retryable`. Для остальных исключений SHALL возвращать `True`. `PermanentJobError` SHALL наследоваться от `JobqError`.

#### Scenario: Наследник неповторяемого класса
- **WHEN** `non_retryable=(ValueError,)` и обработчик бросил `UnicodeError` (наследник `ValueError`)
- **THEN** `is_retryable` возвращает `False`

#### Scenario: PermanentJobError
- **WHEN** обработчик бросил `PermanentJobError`, а `non_retryable` пуст
- **THEN** `is_retryable` возвращает `False`

### Requirement: Выбор политики
Очередь SHALL принимать `default_retry_policy` (keyword-only, по умолчанию `None`), позволять задавать политику типа задания через `set_retry_policy(job_type, policy)` и снимать её передачей `None`. `retry_policy_for(job_type)` SHALL возвращать действующую политику: политику типа, а если её нет — дефолт очереди, а если нет и его — `None`. Политика типа SHALL заменять дефолт целиком, поля не сливаются. При ошибке SHALL применяться политика, действующая в момент ошибки, а не в момент постановки.

#### Scenario: Политика типа заменяет дефолт
- **WHEN** дефолт задаёт `non_retryable=(ValueError,)`, а политика типа создана без `non_retryable`
- **THEN** для этого типа `ValueError` считается повторяемой

#### Scenario: Снятие политики типа
- **WHEN** политика типа снята через `set_retry_policy(job_type, None)`
- **THEN** `retry_policy_for(job_type)` возвращает дефолт очереди (или `None`, если дефолта нет)

#### Scenario: Политика меняется между постановкой и ошибкой
- **WHEN** задание поставлено без политики, затем задана политика типа, затем обработчик упал
- **THEN** применяется заданная политика

### Requirement: Решение воркера при падении обработчика
Когда обработчик бросает исключение (`Exception`), воркер SHALL выбрать результат в таком порядке: (1) если политики нет или ошибка неповторяемая (`is_retryable` ложно) — статус `FAILED`, даже на последней попытке; (2) иначе если `job.attempts >= max_attempts` — статус `DEAD_LETTERED`; (3) иначе статус `RETRY_SCHEDULED` и `run_at = now + delay_for(job.attempts, rng)` по часам очереди. `job.error` SHALL содержать последнюю ошибку в формате `"ИмяКласса: сообщение"`. Задержка и `rng` SHALL использоваться только в случае (3). Отсутствие обработчика для типа задания — ошибка конфигурации: статус `FAILED` сразу, без повторов, независимо от политики. Без действующей политики поведение SHALL совпадать с прежним. `max_attempts=1` означает «без повторов, но в dead-letter».

#### Scenario: Планирование повтора
- **WHEN** обработчик упал на попытке 1 при `max_attempts=3`, `base_delay=10`
- **THEN** статус `RETRY_SCHEDULED`, `run_at` равен текущему времени плюс 10 секунд, `error` содержит последнюю ошибку, счётчик `jobs.retried` вырос на 1

#### Scenario: Попытки кончились
- **WHEN** обработчик упал на попытке 3 при `max_attempts=3` и ошибка повторяемая
- **THEN** статус `DEAD_LETTERED`, запись появилась в `dead_letters()`

#### Scenario: Одна попытка
- **WHEN** `max_attempts=1` и обработчик упал с повторяемой ошибкой
- **THEN** статус `DEAD_LETTERED`, а не `FAILED`

#### Scenario: Неповторяемая ошибка на последней попытке
- **WHEN** на последней попытке обработчик бросил исключение из `non_retryable`
- **THEN** статус `FAILED`, в dead-letter запись не добавляется

#### Scenario: Нет обработчика
- **WHEN** для типа задания не зарегистрирован обработчик, политика задана
- **THEN** статус `FAILED` сразу, `rng` не использовался

#### Scenario: Предсказуемый rng
- **WHEN** `jitter > 0`, воркер создан с `rng` и задание идёт в `FAILED` или `DEAD_LETTERED`
- **THEN** `rng` не вызывается; при планировании повтора вызывается ровно один раз

#### Scenario: Повтор берётся по времени
- **WHEN** задание в `RETRY_SCHEDULED` и часы дошли до его `run_at`
- **THEN** воркер берёт его в работу наравне с `PENDING`; до `run_at` не берёт

### Requirement: Статусы в отчёте и статистике
`JobStatus.RETRY_SCHEDULED` (`"retry_scheduled"`) SHALL иметь подпись «Ожидает повтора», `JobStatus.DEAD_LETTERED` (`"dead_lettered"`) — «В dead-letter». `queue.stats()` SHALL содержать оба статуса. Ни один из них не является терминальным (`is_terminal` ложно). Задание в `RETRY_SCHEDULED` SHALL быть отменяемым через `cancel`.

#### Scenario: Подписи
- **WHEN** запрашиваются `label` новых статусов
- **THEN** возвращаются «Ожидает повтора» и «В dead-letter»

#### Scenario: Отмена ожидающего повтора
- **WHEN** вызывается `cancel` для задания в `RETRY_SCHEDULED`
- **THEN** статус `CANCELLED`


### tasks.md

## 1. Модели, ошибки, метрики

- [ ] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить тестом `issubclass(PermanentJobError, JobqError)`
- [ ] 1.2 Добавить `RETRY_SCHEDULED`, `DEAD_LETTERED`, подписи «Ожидает повтора» и «В dead-letter» и `DeadLetterEntry` (frozen dataclass) в `jobq/models.py`, не включая новые статусы в `_TERMINAL`; проверить тестом подписей и `is_terminal`
- [ ] 1.3 Добавить константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` (`jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`) в `jobq/metrics.py` и дополнить docstring; проверить, что неизвестный счётчик читается как 0

## 2. RetryPolicy

- [ ] 2.1 Создать `jobq/retry.py` с `RetryPolicy`: поля и значения по умолчанию, валидация в `__post_init__` (`ConfigError`), нормализация `non_retryable` в кортеж; проверить параметризованными тестами на каждое некорректное значение (включая NaN, не-класс, список → кортеж)
- [ ] 2.2 Реализовать `delay_for` (формула, ограничение `max_delay`, jitter после ограничения, один `uniform` только при `jitter > 0`, `attempt < 1` → `ConfigError`, без `OverflowError`, `base_delay=0` → 0, `factor=1`); проверить тестами: `delay_for(5001)`, `delay_for(10**6)` с `factor=2`, `base_delay=0`, `Random(seed)` и счётчик вызовов у подставного `rng`
- [ ] 2.3 Реализовать `is_retryable` (наследование через `isinstance`, `PermanentJobError` всегда `False`); проверить тестом с наследником `ValueError`

## 3. Очередь и хранилище

- [ ] 3.1 В `InMemoryJobStore.due()` включить `RETRY_SCHEDULED`; проверить тестом, что повтор не выбирается до `run_at` и выбирается после, порядок `(run_at, seq)` сохранён
- [ ] 3.2 Расширить `_TRANSITIONS` (см. design, п. 5); проверить тестом допустимых и недопустимых переходов, включая `cancel` из `RETRY_SCHEDULED` и ошибку `cancel` из `DEAD_LETTERED`
- [ ] 3.3 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for`; проверить тестами: замена целиком, снятие через `None`, поведение без политик
- [ ] 3.4 Добавить `mark_retry_scheduled` и `mark_dead_lettered` (запись `error`, счётчики, `DeadLetterEntry` с временем очереди), `dead_letters()` (копия в порядке попадания); проверить тестами содержимого, порядка и счётчиков (`jobs.failed` не растёт)
- [ ] 3.5 Добавить `requeue_dead_letter` (то же задание, `PENDING`, `run_at=now`, `error=None`, запись удалена, `jobs.requeued`; `JobNotFoundError` и `InvalidTransitionError` без побочных эффектов); проверить тестами каждого сценария из `specs/dead-letter`
- [ ] 3.6 Проверить тестом, что `purge_finished` не удаляет `RETRY_SCHEDULED` и `DEAD_LETTERED`

## 4. Воркер

- [ ] 4.1 Добавить в `Worker.__init__` keyword-only `rng` (по умолчанию `random.Random()`); проверить, что старые вызовы `Worker(queue, registry, name=...)` работают
- [ ] 4.2 Реализовать выбор исхода в `run_once` в порядке из design, п. 4 (нет обработчика → `FAILED`; нет политики/неповторяемая → `FAILED`; исчерпано → `DEAD_LETTERED`; иначе `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`); проверить тестами со сценариями из `specs/job-retry`, включая `max_attempts=1`, неповторяемую ошибку на последней попытке, политику на момент ошибки и число обращений к `rng`
- [ ] 4.3 Защититься от `OverflowError` при построении `timedelta` для огромного `max_delay` (design, «Риски»); проверить тестом с `max_delay=1e20`
- [ ] 4.4 Сквозной тест: повторы идут по `ManualClock`, задание в итоге `SUCCEEDED` с `error is None`; и цикл «dead-letter → requeue → успех»

## 5. Экспорты и документация

- [ ] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`; проверить импортом `from jobq import ...`
- [ ] 5.2 Обновить `README.md` (модуль `retry.py`, раздел о повторах и dead-letter, новые счётчики и статусы)
- [ ] 5.3 Проверить, что отчёт `render_report` показывает новые подписи (новый тест без правок `dashboard.py`), что `git diff` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты, и что `python -m pytest -q` проходит целиком
