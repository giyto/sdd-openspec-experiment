## 1. Ошибки, статусы, метрики

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py` и экспортировать из `jobq/__init__.py`; проверить `python -c "from jobq import PermanentJobError"`
- [x] 1.2 В `jobq/models.py` добавить `RETRY_SCHEDULED = "retry_scheduled"` (подпись «Ожидает повтора», не терминальный) и `DEAD_LETTERED = "dead_lettered"` (подпись «В dead-letter», терминальный) в конец перечисления; добавить frozen dataclass `DeadLetterEntry` с полями из спецификации; проверить подписи и `is_terminal` через интерактивный вызов или тест из 5.2
- [x] 1.3 В `jobq/metrics.py` добавить константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` и обновить docstring модуля; проверить импортом

## 2. Политика повторов (`jobq/retry.py`)

- [x] 2.1 Создать `jobq/retry.py` с frozen dataclass `RetryPolicy` (значения по умолчанию из спецификации) и валидацией в `__post_init__` через `ConfigError`: диапазоны, `NaN`/бесконечность, `non_retryable` как классы исключений, приведение к `tuple`; проверить тестами из 5.1 на каждое некорректное значение
- [x] 2.2 Реализовать `delay_for(attempt, rng=None)`: формула с ограничением `max_delay`, ветка при `OverflowError` через логарифмы, `base_delay == 0` и `factor == 1` без вычислений, джиттер с повторным ограничением, `rng` не трогаем при `jitter == 0`, `ConfigError` при `attempt < 1`; проверить тестами из 5.1 (включая `attempt=5000` и стаб `rng`)
- [x] 2.3 Реализовать `is_retryable(exc)`: `non_retryable` с учётом наследования, `PermanentJobError` всегда `False`; проверить тестами из 5.1

## 3. Очередь (`jobq/queue.py`, `jobq/store.py`)

- [x] 3.1 Добавить keyword-only параметр `default_retry_policy` в `JobQueue.__init__` с проверкой типа (`RetryPolicy | None`, иначе `ConfigError`); реализовать `set_retry_policy` и `retry_policy_for` по правилам замены без слияния; проверить тестами из 5.2
- [x] 3.2 Расширить `_TRANSITIONS` по таблице из design.md (п. 8); проверить, что `cancel()` работает из `RETRY_SCHEDULED` и не работает из `DEAD_LETTERED`
- [x] 3.3 Реализовать `mark_retry_scheduled(job_id, error, delay)` (`run_at = clock.now() + delay`, счётчик `jobs.retried`) и `mark_dead_lettered(job_id, error)` (запись `DeadLetterEntry`, `finished_at`, счётчик `jobs.dead_lettered`); в `mark_succeeded` очищать `error`; проверить тестами из 5.2
- [x] 3.4 Хранить dead-letter записи в `JobQueue` (dict по `job_id`), реализовать `dead_letters()` в порядке попадания и `requeue_dead_letter(job_id)` (`PENDING`, `run_at = now`, сброс `error`, `finished_at`, `attempts = 0`, счётчик `jobs.requeued`, лог с числом прошлых попыток, `JobNotFoundError` и `InvalidTransitionError` по спецификации); проверить тестами из 5.2
- [x] 3.5 В `purge_finished` пропускать `DEAD_LETTERED`; проверить тестом «очистка не трогает dead-letter» из 5.2
- [x] 3.6 В `InMemoryJobStore.due()` включить `RETRY_SCHEDULED` наравне с `PENDING`, сортировка без изменений; проверить тестом из 5.3, что задание запускается при наступлении `run_at`

## 4. Воркер (`jobq/worker.py`)

- [x] 4.1 Добавить keyword-only параметр `rng: random.Random | None = None` в `Worker.__init__` и сохранить его; проверить `inspect.signature` в тесте 5.3
- [x] 4.2 В `run_once` после падения обработчика реализовать решение по порядку из спецификации `job-retry` (нет политики → `FAILED`; не повторяется → `FAILED`; `attempts >= max_attempts` → `DEAD_LETTERED`; иначе `RETRY_SCHEDULED` с `delay_for(job.attempts, rng)`); политика берётся на момент ошибки; проверить тестами из 5.3
- [x] 4.3 Оставить `UnknownJobTypeError` в `FAILED` без повтора; проверить тестом из 5.3

## 5. Тесты (только новые файлы)

- [x] 5.1 Создать `tests/test_retry.py` для `RetryPolicy`: валидация, кортеж `non_retryable`, `delay_for` (рост, потолок, `attempt=5000`, `base_delay=0`, джиттер со стабом `rng`, `rng` не вызывается при `jitter=0`, `attempt < 1`), `is_retryable`; выполнить `python -m pytest tests/test_retry.py -q`
- [x] 5.2 Создать `tests/test_dead_letter.py` для очереди: разрешение политик, `dead_letters()` и порядок, `requeue_dead_letter` (тот же `id`, сброс полей, `attempts = 0`, ошибки), `purge_finished` не трогает dead-letter, `cancel()` запрещён из `DEAD_LETTERED`, подписи статусов; выполнить `python -m pytest tests/test_dead_letter.py -q`
- [x] 5.3 Создать `tests/test_retry_worker.py` для воркера: сценарии из `job-retry` (первое падение, `run_at` не наступил, `max_attempts=1`, неповторяемая ошибка, `PermanentJobError` на последней попытке, нет обработчика, нет политики, политика на момент ошибки, успех после повтора), метрики (`jobs.started` = 3, `jobs.retried` = 2 и т.д.), сигнатуры `Worker` и `JobQueue`; выполнить `python -m pytest tests/test_retry_worker.py -q`
- [x] 5.4 Проверить, что существующие тесты не изменены и проходят: `git diff --stat -- tests/` пусто для существующих файлов, `python -m pytest -q` зелёный целиком

## 6. Документация и проверка границ

- [x] 6.1 В `README.md` добавить строку `jobq/retry.py` в таблицу модулей с описанием «`RetryPolicy`: политика повторов»; проверить `grep -n "retry.py" README.md`
- [x] 6.2 Проверить, что `jobq/dashboard.py` и `jobq/cli.py` не изменены: `git diff --stat -- jobq/dashboard.py jobq/cli.py` пусто
- [x] 6.3 Проверить, что новые зависимости не добавлены: `pytest.ini` и импорты в `jobq/retry.py` используют только стандартную библиотеку (`math`, `random`, `dataclasses`, `typing`)
