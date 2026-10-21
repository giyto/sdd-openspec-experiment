## 1. Базовые типы

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить, что `issubclass(PermanentJobError, JobqError)` (тест)
- [x] 1.2 В `jobq/models.py` добавить статусы `RETRY_SCHEDULED`, `DEAD_LETTERED`, подписи «Ожидает повтора» / «В dead-letter», `DEAD_LETTERED` в терминальные, и `DeadLetterEntry` (frozen); тест на значения, подписи, `is_terminal`
- [x] 1.3 Создать `jobq/retry.py` с `RetryPolicy` (валидация через `ConfigError`, `non_retryable` в tuple, `delay_for` без `OverflowError`, `is_retryable`); тесты на все сценарии retry-policy, включая `delay_for(5000)` при `max_attempts=10000`, `base_delay=0`, джиттер с подменным `rng` (один `uniform`, при `jitter=0` не вызывается, результат не выше `max_delay` даже при `uniform` > 1)

## 2. Очередь, хранилище, метрики

- [x] 2.1 В `jobq/metrics.py` добавить `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` и обновить docstring; тест имён счётчиков
- [x] 2.2 В `jobq/store.py` расширить `due` на `RETRY_SCHEDULED`; тест: повтор не берётся до `run_at`, порядок `(run_at, seq)` сохранён
- [x] 2.3 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` (замена, а не слияние; `None` снимает; `ConfigError` на неверный тип/пустой тип); тесты приоритета политик
- [x] 2.4 В `JobQueue` расширить `_TRANSITIONS`, добавить `mark_retry_scheduled`, `mark_dead_lettered`, `dead_letters`, `requeue_dead_letter`; `mark_succeeded` обнуляет `error`; `purge_finished` пропускает `DEAD_LETTERED`; тесты: счётчики, порядок записей, поля после requeue (включая `attempts == 0`), `JobNotFoundError`/`InvalidTransitionError`, `cancel` для `RETRY_SCHEDULED` и запрет для `DEAD_LETTERED`

## 3. Воркер

- [x] 3.1 В `Worker.__init__` добавить keyword-only `rng`; в обработчике ошибки реализовать выбор FAILED / RETRY_SCHEDULED / DEAD_LETTERED по политике на момент ошибки; ветка «нет обработчика» остаётся `FAILED`; тесты: временная ошибка, исчерпание попыток, `max_attempts=1`, `PermanentJobError` и наследник `non_retryable` на последней попытке → `FAILED`, `rng` не трогается при FAILED/dead-letter, ровно один `uniform` на повтор, смена политики после enqueue, успех после повтора (`error is None`)
- [x] 3.2 Сквозной тест с `ManualClock`: цепочка падений → dead-letter → `requeue_dead_letter` (счётчик попыток сброшен, снова полный набор повторов) → успех; проверить счётчики `jobs.retried/dead_lettered/requeued` и строки «Ожидает повтора» / «В dead-letter» в `render_report`

## 4. Завершение

- [x] 4.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` из `jobq/__init__.py`, описать функциональность в `README.md`; проверить импорт `from jobq import ...`
- [x] 4.2 Запустить полный `pytest`: все существующие тесты проходят без изменений, `git diff --stat` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты
