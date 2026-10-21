## 1. Базовые типы

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` в новом тесте
- [x] 1.2 В `jobq/models.py` добавить `JobStatus.RETRY_SCHEDULED`/`DEAD_LETTERED`, подписи «Ожидает повтора»/«В dead-letter», `is_terminal` (DEAD_LETTERED терминален, RETRY_SCHEDULED нет) и `DeadLetterEntry`; проверить тестом подписей и `is_terminal`, существующие тесты зелёные
- [x] 1.3 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` и обновить docstring; проверить импортом констант в тесте

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy` (поля, значения по умолчанию, frozen, `non_retryable` → tuple, валидация → `ConfigError`); тесты на все недопустимые и граничные значения, NaN/inf, bool, не-класс в `non_retryable`
- [x] 2.2 Реализовать `delay_for` (рост, потолок, `base_delay=0`, `factor=1`, `attempt=5000` и `10**9` без `OverflowError`, жёсткий потолок после джиттера, один `uniform` на вызов, `rng` не трогается при `jitter=0`, `attempt<1` → `ConfigError`); property-тест: результат в `[0, max_delay]` на сетке значений
- [x] 2.3 Реализовать `is_retryable` (наследники `non_retryable`, `PermanentJobError` всегда `False`); тесты из спецификации `retry-policy`

## 3. Очередь и хранилище

- [x] 3.1 В `jobq/store.py` расширить `due()` на `RETRY_SCHEDULED`; тест: повтор виден только при `run_at <= now`, порядок `(run_at, seq)` сохранён
- [x] 3.2 В `jobq/queue.py` добавить `default_retry_policy` (keyword-only), `set_retry_policy`, `retry_policy_for` с валидацией и заменой (без слияния); тесты на замену дефолта, снятие через `None`, `ConfigError`
- [x] 3.3 Обновить `_TRANSITIONS`, добавить `mark_retry_scheduled`, `mark_dead_lettered` (запись в dead-letter, счётчики), очистку `error` в `mark_succeeded`; тесты переходов и счётчиков, отмена `RETRY_SCHEDULED` ok, отмена `DEAD_LETTERED` → `InvalidTransitionError`
- [x] 3.4 Реализовать `dead_letters()` (копия, порядок попадания) и `requeue_dead_letter` (то же задание, `PENDING`, `run_at=now`, `error=None`, `attempts=0`, счётчик, ошибки `InvalidTransitionError`/`JobNotFoundError`); тесты по спецификации `dead-letter`
- [x] 3.5 Исключить `DEAD_LETTERED` из `purge_finished`; тест: SUCCEEDED удалён, dead-letter и `RETRY_SCHEDULED` остались

## 4. Воркер

- [x] 4.1 Добавить keyword-only `rng` в `Worker` и `_handle_failure` с порядком: нет политики → `FAILED`; неповторяемая → `FAILED`; `attempts >= max_attempts` → `DEAD_LETTERED`; иначе `RETRY_SCHEDULED` с `run_at = now + delay_for(attempts, rng)`; `UnknownJobTypeError` → сразу `FAILED`; тесты на каждую ветку, `max_attempts=1`, политику на момент ошибки, последнюю ошибку в `job.error`
- [x] 4.2 Тесты расхода `rng`: один `uniform` на повтор при `jitter>0`, ноль при `jitter=0`, `FAILED` и `DEAD_LETTERED`; сквозной сценарий с `ManualClock` (падение → ожидание → успех, `error=None`, `attempts`), счётчики `retried/dead_lettered/requeued/failed/started`, перезапуск из dead-letter с последующим повтором

## 5. Экспорт, отчёт и документация

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`; проверить `from jobq import ...`
- [x] 5.2 Новый тест отчёта: `render_report` содержит строки «Ожидает повтора» и «В dead-letter»; убедиться через `git diff --stat`, что `jobq/dashboard.py` и `jobq/cli.py` не изменены
- [x] 5.3 Обновить `README.md` (модуль `retry.py`, раздел о повторах и dead-letter, ограничение хранения записей в памяти очереди); выполнить `python -m pytest -q` — все старые и новые тесты зелёные, существующие тесты не изменены
