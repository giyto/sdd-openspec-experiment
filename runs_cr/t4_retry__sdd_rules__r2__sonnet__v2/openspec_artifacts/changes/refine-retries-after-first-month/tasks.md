## 1. Ошибки и модели

- [x] 1.1 Добавить `RetryLaterError(JobqError)` в `jobq/errors.py` с `__init__(self, message: str = "", *, retry_after: float)`, валидацией (`< 0`, NaN, не число → `ConfigError`) и атрибутом `retry_after: float`; проверить новыми тестами в отдельном файле (создание, `retry_after=-1`, `0`, `inf`)
- [x] 1.2 Добавить `DeadLetterReason(str, Enum)` (`EXHAUSTED = "exhausted"`, `NON_RETRYABLE = "non_retryable"`) и последнее поле `DeadLetterEntry.reason` со значением по умолчанию `EXHAUSTED` в `jobq/models.py`; проверить, что создание записи пятью аргументами работает
- [x] 1.3 Экспортировать `RetryLaterError` и `DeadLetterReason` из `jobq/__init__.py` (`__all__`); проверить `from jobq import RetryLaterError, DeadLetterReason`

## 2. Политика повторов

- [x] 2.1 В `RetryPolicy.delay_for` заменить диапазон джиттера на `rng.uniform(1 - jitter, 1)`; проверить новыми тестами: один вызов `uniform` с `(1 - jitter, 1)`, результат не больше расчётной задержки, `jitter == 0` не трогает `rng`

## 3. Очередь

- [x] 3.1 `JobQueue.mark_dead_lettered(job_id, error, *, reason=DeadLetterReason.EXHAUSTED)`: записывать `reason` в `DeadLetterEntry`; проверить, что вызов без `reason` даёт `exhausted`
- [x] 3.2 `JobQueue.purge_finished`: дополнительно удалять `DEAD_LETTERED` с `dead_lettered_at <= now - older_than` вместе с записью из `dead_letters()` (порядок остальных сохраняется), учитывать их в результате и в `jobs.purged`; проверить новыми тестами сценарии из спеки dead-letter-queue (возраст, порядок, `RETRY_SCHEDULED` остаётся)
- [x] 3.3 Добавить `JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]` через `requeue_dead_letter` по снимку `dead_letters()`; проверить: все, по типу, порядок, пустой результат `[]`, `jobs.requeued`

## 4. Воркер

- [x] 4.1 В `Worker._handle_failure` реализовать порядок: нет политики → `FAILED`; неповторяемая → `mark_dead_lettered(..., reason=NON_RETRYABLE)`; `attempts >= max_attempts` → `EXHAUSTED`; иначе повтор; `UnknownJobTypeError` остаётся `FAILED`; проверить тестами, включая неповторяемую ошибку на последней попытке и `jobs.failed == 0`
- [x] 4.2 Для `RetryLaterError` планировать `run_at = now + min(retry_after, max_delay)` без `delay_for` и без обращения к `rng`; проверить тестами: обычный случай, `retry_after=3600` при `max_delay=60`, `retry_after=0`, последняя попытка → `EXHAUSTED`, подсчитывающий `rng` не вызван при `jitter > 0`

## 5. Документация и проверка

- [x] 5.1 Обновить раздел «Повторы и dead-letter» в `README.md` (неповторяемые → dead-letter, джиттер только вниз, `RetryLaterError`, `reason`, `requeue_all_dead_letters`, очистка dead-letter, предупреждение про `purge_finished()` с `older_than=0`); проверить чтением раздела
- [x] 5.2 Запустить `pytest`; убедиться, что падают только существующие тесты, закрепляющие отменённое поведение (неповторяемые → `FAILED`, очистка не трогает dead-letter, двусторонний джиттер); не редактировать их, перечислить в отчёте
- [x] 5.3 Проверить, что `jobq/dashboard.py`, `jobq/cli.py` и существующие тесты не изменены (`git diff --stat`), зависимости не добавлены
- [x] 5.4 Сверить публичный API реализации с proposal и specs: `DeadLetterReason` (значения), `DeadLetterEntry.reason` последним полем, `RetryLaterError(message="", *, retry_after)` и атрибут `retry_after`, `JobQueue.requeue_all_dead_letters(job_type=None) -> list[Job]`, `mark_dead_lettered` с keyword-only `reason`, экспорты из `jobq`, неизменные старые сигнатуры
