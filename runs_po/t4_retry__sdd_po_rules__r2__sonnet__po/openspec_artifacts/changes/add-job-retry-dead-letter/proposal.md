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
- `requeue_dead_letter` сбрасывает `attempts` в 0: вернувшееся вручную задание получает полный набор попыток, как новое. История прежних попыток хранится в логах, в самом задании не сохраняется.
- Переход в `DEAD_LETTERED` не увеличивает `jobs.failed` (счётчик растёт только при переходе в свой статус).
