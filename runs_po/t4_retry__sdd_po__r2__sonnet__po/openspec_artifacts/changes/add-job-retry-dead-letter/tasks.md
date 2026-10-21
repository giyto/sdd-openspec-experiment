## 1. Основа: ошибки, модели, метрики

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py` и экспорт в `jobq/__init__.py`; проверить `issubclass(PermanentJobError, JobqError)` тестом
- [x] 1.2 Добавить `RETRY_SCHEDULED`/`DEAD_LETTERED`, подписи «Ожидает повтора»/«В dead-letter», терминальность (`DEAD_LETTERED` терминален, `RETRY_SCHEDULED` нет) и `DeadLetterEntry` в `jobq/models.py`; тест на `value`, `label`, `is_terminal`
- [x] 1.3 Добавить константы `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` и обновить docstring в `jobq/metrics.py`; тест, что счётчики читаются как 0

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py`: замороженный dataclass, значения по умолчанию, нормализация `non_retryable` в tuple, валидация с `ConfigError` (включая NaN, не-классы, bool/нецелый `max_attempts`); параметризованный тест на каждое некорректное значение
- [x] 2.2 Реализовать `delay_for` без `OverflowError` (`base_delay=0`, `factor=1`, attempt 5000/10000, целый factor), jitter после ограничения с жёстким потолком `max_delay` (сценарий 1.25 при `max_delay=60` → 60.0), ровно один `uniform`, без вызова при `jitter=0`, `attempt<1` → `ConfigError`; тесты с подменным rng
- [x] 2.3 Реализовать `is_retryable` (наследование, `PermanentJobError` всегда False); тесты по сценариям спецификации
- [x] 2.4 Экспортировать `RetryPolicy`, `DeadLetterEntry` из `jobq/__init__.py`; проверить импортом `from jobq import RetryPolicy, DeadLetterEntry`

## 3. Очередь

- [x] 3.1 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` с валидацией; тесты: замена целиком, снятие политики, `None`, смена политики после enqueue
- [x] 3.2 Расширить `_TRANSITIONS` и `InMemoryJobStore.due()` (включить `RETRY_SCHEDULED`), разрешить `cancel` из `RETRY_SCHEDULED`; тест: до `run_at` не выбирается, после — выбирается в порядке `(run_at, seq)`
- [x] 3.3 Добавить `mark_retry_scheduled` и `mark_dead_lettered` (ошибка, `run_at`, `finished_at`, запись журнала, счётчики); тесты на счётчики и поля
- [x] 3.4 Добавить `dead_letters()` (копия, порядок попадания) и `requeue_dead_letter()` (то же задание, PENDING, run_at=now, `attempts=0`, error/finished_at очищены, лог с прежним числом попыток, запись удалена, `jobs.requeued`; `JobNotFoundError`/`InvalidTransitionError` без побочных эффектов); тесты по сценариям спецификации, включая запрет `cancel` из dead-letter
- [x] 3.5 Сделать `purge_finished` пропускающим `DEAD_LETTERED`; тест, что задание и запись остаются

## 4. Воркер

- [x] 4.1 Добавить `Worker(..., rng=None)` keyword-only и ветвление при ошибке обработчика в порядке: нет обработчика → FAILED, нет политики → FAILED, неповторяемая → FAILED, `attempts >= max_attempts` → DEAD_LETTERED, иначе RETRY_SCHEDULED с `delay_for(job.attempts, rng)`; `rng` не трогается вне последней ветки; тесты со всеми сценариями `job-retry`, включая `max_attempts=1` и `PermanentJobError`
- [x] 4.2 Сквозные тесты на ManualClock: упало дважды, успех на третьем запуске (`error=None`); путь retry, retry, dead-letter, requeue, success со сверкой счётчиков
- [x] 4.3 Тест обратной совместимости: без политики любая ошибка даёт FAILED; тест, что `render_report` содержит новые подписи

## 5. Документация и проверка

- [x] 5.1 Обновить README (таблица модулей, `retry.py`, раздел про повторы и dead-letter, сброс `attempts` при возврате из dead-letter); проверить, что файл содержит новый раздел
- [x] 5.2 Запустить `python -m pytest -q`: все существующие и новые тесты зелёные; `git diff --stat` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты
