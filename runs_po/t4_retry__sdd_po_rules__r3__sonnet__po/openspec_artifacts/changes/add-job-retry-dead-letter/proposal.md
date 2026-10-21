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
5. `requeue_dead_letter` сбрасывает `attempts` в 0 и очищает `finished_at`: вернувшееся задание получает полный набор попыток, как новое, и не уходит в dead-letter после первой же ошибки. Прежнее число попыток в самом задании не хранится (его видно в логах и в записи `DeadLetterEntry` до возврата).
5a. `max_delay` — жёсткий потолок задержки: после применения джиттера результат ограничивается `max_delay` (если с разбросом получилось больше, возвращается ровно `max_delay`).
6. `requeue_dead_letter` для неизвестного id — `JobNotFoundError`; для задания не в `DEAD_LETTERED` — `InvalidTransitionError`.
7. `failure_rate` в `dashboard.py` не меняется и `DEAD_LETTERED` не учитывает.
