## 1. Базовые типы

- [x] 1.1 Добавить `PermanentJobError(JobqError)` в `jobq/errors.py`; проверить `issubclass(PermanentJobError, JobqError)` тестом
- [x] 1.2 В `jobq/models.py` добавить `JobStatus.RETRY_SCHEDULED`, `JobStatus.DEAD_LETTERED`, подписи «Ожидает повтора» и «В dead-letter», `is_terminal` (True только для DEAD_LETTERED из новых) и frozen dataclass `DeadLetterEntry`; проверить тестом подписей и флагов терминальности
- [x] 1.3 В `jobq/metrics.py` добавить константы `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` и дополнить описание в docstring; проверить, что константы доступны и неизвестные счётчики читаются как 0

## 2. RetryPolicy

- [x] 2.1 Создать `jobq/retry.py` с `RetryPolicy` (поля, значения по умолчанию, frozen, нормализация `non_retryable` в tuple, валидация с `ConfigError`, включая NaN и не-классы); проверить тестами на каждое некорректное значение и на граничные допустимые
- [x] 2.2 Реализовать `delay_for` без `OverflowError` (`attempt` 5000 и 10**9, `base_delay=0`, `factor=1`, ограничение `max_delay`, jitter после ограничения с повторным ограничением результата `max_delay` (uniform=1.2 при `max_delay=10` даёт 10), один `uniform`, `rng` не трогается при `jitter=0`, `ConfigError` при `attempt < 1`); проверить unit-тестами со стаб-`rng`
- [x] 2.3 Реализовать `is_retryable` (наследование `non_retryable`, `PermanentJobError` всегда False); проверить тестами

## 3. Очередь и хранилище

- [x] 3.1 В `InMemoryJobStore.due` включить `RETRY_SCHEDULED`; проверить, что задание выбирается только при `run_at <= now`, порядок `(run_at, seq)` сохранён
- [x] 3.2 В `JobQueue` добавить keyword-only `default_retry_policy`, `set_retry_policy`, `retry_policy_for` (политика типа заменяет дефолт целиком, `ConfigError` на некорректные аргументы); проверить тестами, включая снятие политики и отсутствие слияния
- [x] 3.3 Расширить `_TRANSITIONS`, добавить `mark_retry_scheduled` и `mark_dead_lettered` (запись `error`, `run_at`, `finished_at`, запись в dead-letter, счётчики `jobs.retried`/`jobs.dead_lettered`), очистку `error` в `mark_succeeded`; проверить тестами переходов, счётчиков и `InvalidTransitionError`
- [x] 3.4 Реализовать `dead_letters()` (копия, порядок попадания) и `requeue_dead_letter` (то же задание, `PENDING`, `run_at=now`, `error=None`, `attempts=0`, удаление записи, `jobs.requeued`, ошибки без побочных эффектов); `purge_finished` пропускает `DEAD_LETTERED`; проверить тестами

## 4. Воркер

- [x] 4.1 Добавить в `Worker` keyword-only `rng` и цепочку решений при падении обработчика (нет политики / неповторяемая → FAILED, исчерпано → DEAD_LETTERED, иначе RETRY_SCHEDULED с `delay_for(job.attempts, rng)`; нет обработчика → FAILED; политика берётся в момент ошибки); проверить тестами worker, включая `max_attempts=1`, неповторяемую ошибку на последней попытке и наследников
- [x] 4.2 Проверить тестом с подсчитывающим `rng`, что `uniform` вызывается ровно один раз только при планировании повтора и ни разу при `jitter=0`, FAILED и dead-letter
- [x] 4.3 Сквозной тест: упавшее задание повторяется после `clock.advance`, успех очищает `error`, dead-letter → `requeue_dead_letter` → повторное выполнение; проверить значения счётчиков

## 5. Оформление

- [x] 5.1 Экспортировать `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` в `jobq/__init__.py`, обновить таблицу модулей и описание повторов в `README.md`; проверить импортом из `jobq`
- [x] 5.2 Запустить `python -m pytest -q`: существующие тесты не изменены и проходят, `git diff` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты, отчёт `render_report` содержит подписи новых статусов
- [x] 5.3 Сверить публичный API реализации с proposal и specs (имена, порядок и вид параметров, keyword-only, значения enum `"retry_scheduled"`/`"dead_lettered"`, поля `DeadLetterEntry`, имена счётчиков) и устранить расхождения
