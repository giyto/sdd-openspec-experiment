## 1. Основа: ошибки, модели, метрики

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить новым тестом `issubclass(PermanentJobError, JobqError)`
- [x] 1.2 Добавить `RETRY_SCHEDULED`/`DEAD_LETTERED` в `JobStatus` с подписями «Ожидает повтора»/«В dead-letter» (не терминальные) и `DeadLetterEntry` в `jobq/models.py`; проверить тестом значений, подписей и `is_terminal`, существующие тесты зелёные
- [x] 1.3 Добавить константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `jobq/metrics.py` и обновить docstring; проверить, что `Metrics().get("jobs.retried") == 0`

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy`, валидацией (`ConfigError`) и приведением `non_retryable` к tuple; проверить тестами значений по умолчанию и всех некорректных параметров
- [x] 2.2 Реализовать `delay_for` (экспонента, потолок, джиттер и повторное ограничение, без OverflowError, `base_delay=0`, `attempt<1`); проверить тестами `attempt=5000`, `max_attempts=10000`, джиттера и числа вызовов `rng`
- [x] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError`); проверить тестами из спецификации

## 3. Очередь и хранилище

- [x] 3.1 Расширить `InMemoryJobStore.due()` на `RETRY_SCHEDULED`; проверить тестом общего порядка `(run_at, seq)` и прежними тестами `due`
- [x] 3.2 Добавить в `JobQueue` keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` с проверкой типа (`ConfigError`); проверить тестами замены без слияния и снятия политики
- [x] 3.3 Обновить `_TRANSITIONS`, добавить `mark_retry_scheduled`, `mark_dead_lettered` со счётчиками; проверить допустимые и недопустимые переходы (`InvalidTransitionError`), в том числе `cancel` из `RETRY_SCHEDULED` и из `DEAD_LETTERED`
- [x] 3.4 Реализовать `dead_letters()` и `requeue_dead_letter` (то же задание, `PENDING`, `run_at=now`, `error=None`, `attempts=0`, запись удалена, `jobs.requeued`); проверить тестами порядка, ошибок и неизменного размера хранилища
- [x] 3.5 Убедиться, что `purge_finished` не удаляет новые статусы; проверить тестом с `older_than=0`

## 4. Воркер

- [x] 4.1 Добавить `rng` в `Worker` и ветвление `FAILED`/`DEAD_LETTERED`/`RETRY_SCHEDULED` по действующей политике; проверить тестами: без политики, `max_attempts=1`, исчерпание попыток, неповторяемая ошибка на последней попытке, нет обработчика
- [x] 4.2 Проверить использование `rng` (один `uniform` на повтор, ноль при `jitter=0`, `FAILED`, dead-letter) и смену политики между постановкой и ошибкой тестами с `ManualClock`
- [x] 4.3 Сквозные тесты: падение → повтор после `run_at` → успех; падение до dead-letter → `requeue_dead_letter` → новый полный набор попыток; сверить счётчики

## 5. Экспорт, документация, итоговая проверка

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`, обновить `README.md`; проверить импортом `from jobq import ...`
- [x] 5.2 Проверить отчёт: `render_report` показывает «Ожидает повтора» и «В dead-letter»; `dashboard.py` и `cli.py` не изменены (`git diff --stat`); `python -m pytest -q` зелёный, существующие тесты не изменены
- [x] 5.3 Сверить публичный API реализации с proposal и specs (имена, порядок и keyword-only параметры, значения enum `"retry_scheduled"`/`"dead_lettered"`, имена счётчиков) и зафиксировать результат сверки
