## 1. Базовые типы

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` в новом тесте
- [x] 1.2 Добавить в `jobq/models.py` статусы `RETRY_SCHEDULED`/`DEAD_LETTERED` (в конец enum), подписи «Ожидает повтора» и «В dead-letter», нетерминальность, и frozen dataclass `DeadLetterEntry`; проверить тестом значений, подписей, `is_terminal` и неизменяемости записи
- [x] 1.3 Добавить счётчики `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `jobq/metrics.py` и дополнить докстроку; проверить, что `Metrics().get("jobs.retried") == 0`

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy` (поля и значения по умолчанию из proposal), валидацией в `__post_init__` и приведением `non_retryable` к tuple; проверить тестами по сценариям «Параметры RetryPolicy» (умолчания, список → tuple, каждый вид некорректных параметров → `ConfigError`, граничные значения)
- [x] 2.2 Реализовать `delay_for` (ограничение `max_delay`, джиттер после ограничения с повторным ограничением результата до `max_delay`, один `uniform` только при `jitter > 0`, `base_delay == 0`, `factor == 1`, защита от `OverflowError`, `attempt < 1` → `ConfigError`); проверить тестами, включая `attempt=5000` и `attempt=10**6`, `base_delay=0`, заглушку `rng` со счётчиком вызовов, джиттер выше потолка → ровно `max_delay`
- [x] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError`); проверить тестами по сценариям классификации

## 3. Очередь

- [x] 3.1 Обновить `_TRANSITIONS` в `jobq/queue.py` (RETRY_SCHEDULED → RUNNING/CANCELLED, RUNNING → +RETRY_SCHEDULED/DEAD_LETTERED, DEAD_LETTERED → PENDING) и `InMemoryJobStore.due` (PENDING и RETRY_SCHEDULED); проверить тестами: ждёт до `run_at`, общий порядок `(run_at, seq)`, `cancel` из RETRY_SCHEDULED проходит, из DEAD_LETTERED — `InvalidTransitionError`, `purge_finished` их не удаляет
- [x] 3.2 Добавить `default_retry_policy` (keyword-only), `set_retry_policy`, `retry_policy_for` с проверками типов (`ConfigError`); проверить тестами: приоритет, замена целиком без слияния, снятие `None`, старый вызов `JobQueue(...)` без параметра
- [x] 3.3 Добавить `mark_retry_scheduled`, `mark_dead_lettered`, `dead_letters` (копия, порядок попадания), `requeue_dead_letter` (то же задание, PENDING, `run_at=now`, `error=None`, `finished_at=None`, `attempts=0`, запись удалена, ошибки `JobNotFoundError`/`InvalidTransitionError` без побочных эффектов) со счётчиками; проверить тестами по сценариям спека `dead-letter`

## 4. Воркер

- [x] 4.1 Добавить `rng` (keyword-only после `name`) в `Worker` и ветвление исхода в `run_once`: нет политики / неповторяемая → FAILED, `attempts >= max_attempts` → DEAD_LETTERED, иначе RETRY_SCHEDULED с `run_at = now + delay_for(attempts, rng)`; отсутствие обработчика → FAILED до обращения к политике; проверить тестами по сценариям «Исход упавшего задания» (`max_attempts=1`, последняя попытка с неповторяемой ошибкой, политика меняется после enqueue, подклассы `non_retryable`)
- [x] 4.2 Проверить тестами с заглушкой `rng`: ровно один `uniform` на запланированный повтор при `jitter > 0` и ни одного при `FAILED`, `DEAD_LETTERED` и `jitter == 0`
- [x] 4.3 Сквозные тесты: упало дважды и прошло с третьей попытки (`error is None`, `attempts == 3`), после возврата из dead-letter `attempts == 0` и первое же падение даёт `RETRY_SCHEDULED`, счётчики `jobs.retried/dead_lettered/requeued/failed/started`, возврат из dead-letter и успешное выполнение, строки статусов в `render_report` (без правки `dashboard.py`)

## 5. Экспорт и документация

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py` и обновить `README.md` (таблица модулей, раздел о повторах и dead-letter); проверить `from jobq import RetryPolicy, PermanentJobError, DeadLetterEntry`

## 6. Проверка

- [x] 6.1 Запустить `python -m pytest -q`: все существующие тесты проходят без изменений, `git diff --stat` не показывает `jobq/dashboard.py`, `jobq/cli.py` и существующих файлов в `tests/`
- [x] 6.2 Сверить публичный API реализации с proposal и specs: `RetryPolicy` (поля, значения по умолчанию, `delay_for`, `is_retryable`), `PermanentJobError`, `JobStatus.RETRY_SCHEDULED`/`DEAD_LETTERED` и их значения/подписи, `DeadLetterEntry` (поля), `JobQueue(...)` с `default_retry_policy`, `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`, `Worker(..., name, rng)`, имена счётчиков; проверить через `inspect.signature` и ручной просмотр, расхождения исправить
