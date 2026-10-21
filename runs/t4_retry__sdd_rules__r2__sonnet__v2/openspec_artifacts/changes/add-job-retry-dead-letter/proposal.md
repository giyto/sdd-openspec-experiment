## Why

Сейчас любое исключение в обработчике сразу переводит задание в `FAILED`, и дежурные каждое утро вручную перезапускают десятки заданий, хотя почти все падения временные (таймауты почтового шлюза, 503 от биллинга). Нужны настраиваемые повторы с экспоненциальной задержкой и отдельное dead-letter-хранилище для заданий, которые так и не выполнились (JOBQ-212).

## What Changes

- Новый модуль `jobq/retry.py`: `RetryPolicy` (frozen dataclass) с полями `max_attempts=3`, `base_delay=1.0`, `factor=2.0`, `max_delay=60.0`, `jitter=0.0`, `non_retryable=()` и методами `delay_for(attempt, rng=None) -> float`, `is_retryable(exc) -> bool`.
- `jobq/errors.py`: `PermanentJobError(JobqError)` — обработчик бросает её, когда повтор точно не поможет.
- `jobq/models.py`: статусы `JobStatus.RETRY_SCHEDULED = "retry_scheduled"` и `JobStatus.DEAD_LETTERED = "dead_lettered"` с подписями «Ожидает повтора» и «В dead-letter»; `DeadLetterEntry(job_id, job_type, attempts, error, dead_lettered_at)` (frozen dataclass).
- `jobq/queue.py`: `JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy=None)`, `set_retry_policy(job_type, policy)`, `retry_policy_for(job_type)`, `dead_letters()`, `requeue_dead_letter(job_id) -> Job`; новые допустимые переходы.
- `jobq/worker.py`: `Worker(queue, registry, *, name="worker", rng=None)`; при падении обработчика воркер выбирает между `FAILED`, `RETRY_SCHEDULED` и `DEAD_LETTERED`.
- Выборка готовых заданий учитывает `RETRY_SCHEDULED` с наступившим `run_at`.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- Без политики (ни очереди по умолчанию, ни типа) поведение не меняется: любое исключение даёт `FAILED`.
- Ограничения: `jobq/dashboard.py` и `jobq/cli.py` не меняются (подписи в отчёте появляются через `JobStatus.label`); сигнатуры существующих публичных методов не меняются, новые параметры только keyword-only; существующие тесты не меняются; новых зависимостей нет.

Не **BREAKING**: старые вызовы работают как раньше. Единственное наблюдаемое отличие для существующих потребителей — `queue.stats()` и отчёт дежурных содержат две новые строки статусов (с нулями, пока политика не включена).

## Capabilities

### New Capabilities
- `retry-policy`: `RetryPolicy` — валидация параметров, расчёт задержки `delay_for`, классификация ошибок `is_retryable`, `PermanentJobError`.
- `job-retry-execution`: выбор политики (дефолт очереди / тип), решение воркера при падении обработчика, статус `RETRY_SCHEDULED`, планирование `run_at`, отмена, метрики `jobs.retried`.
- `dead-letter-queue`: статус `DEAD_LETTERED`, `DeadLetterEntry`, `dead_letters()`, `requeue_dead_letter`, взаимодействие с `purge_finished`, метрики `jobs.dead_lettered`/`jobs.requeued`, подписи статусов в отчёте.

### Modified Capabilities
<!-- В openspec/specs/ пока нет спецификаций; существующее поведение описано в коде и README и не меняется. -->

## Impact

- Код: `jobq/retry.py` (новый), `jobq/errors.py`, `jobq/models.py`, `jobq/queue.py`, `jobq/store.py` (условие `due`), `jobq/worker.py`, `jobq/metrics.py`, `jobq/__init__.py` (экспорт), `README.md`.
- Тесты: только новые файлы; существующие не меняются.
- Зависимости: нет. Публичный API существующих методов: без изменений.

## Допущения

Решения по неоднозначностям, принятые без возможности уточнить (подробности в design.md):

- Итоговая версия по требованию из обсуждения: `requeue_dead_letter` **обнуляет** `attempts` (UPD тимлида отменяет исходную формулировку «attempts сохраняем»).
- `DEAD_LETTERED` не является терминальным статусом (`is_terminal` = `False`), поэтому `purge_finished` его не трогает; выход из него один — `requeue_dead_letter`.
- Переменная `rng=None` при `jitter > 0` заменяется общим генератором модуля `random`.
