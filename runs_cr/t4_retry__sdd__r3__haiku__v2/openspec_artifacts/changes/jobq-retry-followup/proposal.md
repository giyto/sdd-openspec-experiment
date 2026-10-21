## Why

Повторы и dead-letter работают месяц, и по итогам накопились претензии (JOBQ-237). Три договорённости
из JOBQ-212 не сработали на практике:

- неповторяемая ошибка переводила задание в `FAILED`, минуя dead-letter. Такие задания в основном
  оказываются с кривыми данными; их чинят руками и потом ищут по логам;
- джиттер разбрасывал задержку в обе стороны, а почте нужен SLA «повтор не позже расчётного времени»;
- `purge_finished` не трогал dead-letter, и там скопилось около 40 тысяч записей.

Кроме того, биллинг присылает `Retry-After`, и текущая политика не умеет его учитывать.

## What Changes

- **BREAKING** для типов с политикой повторов: неповторяемая ошибка (включая `PermanentJobError`)
  переводит задание в `DEAD_LETTERED` с причиной `non_retryable` вместо `FAILED`, без повторов.
  Для типов без политики и для неизвестных типов поведение не меняется (`FAILED`).
- **BREAKING** джиттер только уменьшает задержку: множитель `rng.uniform(1 - jitter, 1)` вместо
  `rng.uniform(1 - jitter, 1 + jitter)`. Повтор не приходит позже расчётного времени.
- `DeadLetterEntry.reason: DeadLetterReason` (новое последнее поле): `exhausted` (кончились попытки)
  или `non_retryable` (неповторяемая ошибка; при неповторяемой ошибке на последней попытке — тоже
  `non_retryable`).
- Новое исключение `RetryLaterError(message="", *, retry_after: float)`: обработчик бросает его,
  когда внешний сервис сам назвал время следующей попытки. Следующая попытка планируется через
  `retry_after` секунд, но не позже `max_delay`. Джиттер к этой задержке не применяется и `rng`
  не используется. `retry_after < 0` — `ConfigError`. Ошибка остаётся временной: проверка
  повторяемости и лимит попыток действуют как обычно.
- `purge_finished` чистит dead-letter по тому же правилу возраста, отсчитывая от `dead_lettered_at`.
  Удалённая запись пропадает из `dead_letters()`, задание удаляется из хранилища.
- `JobQueue.requeue_all_dead_letters(job_type: str | None = None) -> list[Job]`: перезапускает
  записи в порядке `dead_letters()` (всё содержимое или только тип `job_type`) через
  `requeue_dead_letter`; возвращает перезапущенные задания, при пустом результате — пустой список.

## Capabilities

### New Capabilities
<!-- Новых capability нет: изменения касаются существующих job-retry и dead-letter. -->

### Modified Capabilities
- `job-retry`: решение воркера при падении (неповторяемая ошибка → dead-letter при наличии политики;
  `RetryLaterError`), формула джиттера, ограничение задержки `max_delay`.
- `dead-letter`: `DeadLetterReason` и поле `reason`, очистка dead-letter в `purge_finished`,
  `requeue_all_dead_letters`.

## Impact

- Код: `jobq/models.py` (`DeadLetterReason`, поле `reason`), `jobq/errors.py` (`RetryLaterError`),
  `jobq/retry.py` (джиттер `uniform(1 - jitter, 1)`), `jobq/worker.py` (новая ветка решения),
  `jobq/queue.py` (`mark_dead_lettered` с причиной, `purge_finished`, `requeue_all_dead_letters`),
  `jobq/__init__.py` (экспорт `RetryLaterError`, `DeadLetterReason`).
- API: только добавления и одно изменение поведения (см. BREAKING). Сигнатуры существующих публичных
  методов не меняются; новый параметр `reason` у `mark_dead_lettered` — keyword-only со значением
  по умолчанию `EXHAUSTED`, старые вызовы работают.
- Не затрагивается: `jobq/dashboard.py`, `jobq/cli.py`, новые зависимости.
- Тесты: существующие тесты не меняются. Часть из них описывает прежнее поведение (см. design.md,
  раздел «Конфликт с существующими тестами»), и после изменения они упадут. Это нужно решить до apply.
