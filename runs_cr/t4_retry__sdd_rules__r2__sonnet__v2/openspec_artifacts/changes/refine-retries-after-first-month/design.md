## Context

Состояние после JOBQ-212: `Worker._handle_failure` выбирает `FAILED` / `DEAD_LETTERED` / `RETRY_SCHEDULED`, `RetryPolicy.delay_for` считает задержку, `JobQueue` хранит записи dead-letter в списке `_dead_letters`, `purge_finished` удаляет только терминальные задания. Требования — в `specs/` этого изменения; мотивация — в proposal.md. `jobq/dashboard.py` и `jobq/cli.py` не трогаем, публичные сигнатуры сохраняем.

## Goals / Non-Goals

**Goals:**
- Реализовать пересмотренные правила (dead-letter для неповторяемых ошибок, джиттер вниз, очистка dead-letter, `RetryLaterError`, `requeue_all_dead_letters`, `reason`) с минимальным диффом.

**Non-Goals:**
- Фильтры/поиск по `reason` в очереди, изменение отчёта дежурных и CLI.
- Отдельная метрика по причинам, изменение `requeue_dead_letter`.
- Редактирование существующих тестов.

## Decisions

1. **`reason` передаётся в `mark_dead_lettered` как keyword-only параметр** `reason: DeadLetterReason = DeadLetterReason.EXHAUSTED`. Сигнатура остаётся совместимой. Альтернатива — два отдельных метода: больше публичной поверхности без выгоды.
2. **`DeadLetterEntry.reason` имеет значение по умолчанию `EXHAUSTED`.** Тикет требует «поле последним»; дефолт сохраняет работоспособность кода, создающего запись пятью аргументами (требование «старые вызовы должны работать»). `DeadLetterReason` живёт в `jobq/models.py`, экспортируется из `jobq`.
3. **Порядок решений в `_handle_failure`:** политики нет → `FAILED`; `not is_retryable` → `DEAD_LETTERED(NON_RETRYABLE)`; `attempts >= max_attempts` → `DEAD_LETTERED(EXHAUSTED)`; иначе повтор. Проверка неповторяемости идёт раньше счётчика, поэтому «причина важнее счётчика» получается сама. `UnknownJobTypeError` обрабатывается до `_handle_failure` и остаётся `FAILED` (это не ошибка обработчика).
4. **Задержка повтора:** если `isinstance(exc, RetryLaterError)`, то `delay = min(exc.retry_after, policy.max_delay)` без вызова `delay_for` и `rng`; иначе `policy.delay_for(attempts, rng)`. Решение тимлида от 04.11 (без джиттера) заменяет первоначальную формулировку тикета «к этой задержке тоже применяем джиттер»; считаем его актуальным. Проверка `isinstance` стоит после проверки на неповторяемость и исчерпание.
5. **`RetryLaterError.__init__`** валидирует `retry_after` (число, не bool, не NaN, `>= 0`, иначе `ConfigError`), вызывает `super().__init__(message)` и хранит `float(retry_after)`. `inf` допустим: он режется `max_delay`. Исключение подклассом `JobqError`, как заявлено в тикете.
6. **Джиттер:** в `delay_for` заменить диапазон на `uniform(1 - jitter, 1)`. Итоговое `max(min(delay, max_delay), 0.0)` оставить как защиту от кривого `rng`.
7. **Очистка:** `purge_finished` дополнительно проходит по `_dead_letters`; для записи с `dead_lettered_at <= cutoff`, у которой задание ещё в `DEAD_LETTERED`, удаляет задание из хранилища и запись из списка (один проход с пересборкой списка, порядок сохраняется). Возраст берётся из записи, а не из `finished_at`. Счётчик `jobs.purged` и результат суммируют оба вида. Альтернатива «считать от `finished_at`» эквивалентна сейчас (оба равны моменту попадания), но запись — первоисточник по тикету.
8. **`requeue_all_dead_letters`:** берёт снимок `dead_letters()`, фильтрует по `job_type` (если не `None`), для каждой записи вызывает `requeue_dead_letter(entry.job_id)` и собирает результаты. Порядок — порядок `dead_letters()`. Никакой отдельной валидации `job_type` нет: неизвестный или пустой тип просто даёт `[]`.

## Риски / Trade-offs

- [Существующие тесты закрепляют старое поведение: `FAILED` для неповторяемых ошибок (`tests/test_retry_worker.py`, `tests/test_dead_letter.py`), `purge_finished` не трогает dead-letter, `uniform(1 - jitter, 1 + jitter)` (`tests/test_retry_policy.py`)] → по условию их не меняем; при реализации сообщить, какие тесты падают из-за отменённых договорённостей, и не подгонять под них код. Правка тестов — отдельное решение владельцев.
- [`purge_finished()` с `older_than=0` по умолчанию теперь удаляет весь dead-letter, включая невостребованные записи] → это следствие тикета; зафиксировать в README, что оператору стоит вызывать с ненулевым `older_than`.
- [Записи dead-letter хранятся в списке, очистка линейна по размеру (40 тыс. — приемлемо)] → без оптимизации.
- [Если `RetryLaterError` включён в `non_retryable`, он станет `non_retryable`] → принято как следствие общего правила.

## Допущения

- Для типа без политики поведение прежнее: любая ошибка → `FAILED`, включая `PermanentJobError` и `RetryLaterError`.
- `retry_after = 0` допустим (повтор немедленно); `retry_after` может быть меньше `base_delay`.
- Повтор по `RetryLaterError` не зависит от номера попытки; попытки считаются как обычно.
- Метрика `jobs.purged` учитывает удалённые из dead-letter.
- Перезапуск по пустому/неизвестному `job_type` не ошибка.

## Migration Plan

Состояние в памяти, миграции данных нет. Записи dead-letter, созданные до изменения, не существуют вне процесса. Откат — возврат коммита.

## Итоги реализации

- `RetryLaterError`: `bool` и не-числа отвергаются как `ConfigError`; `inf` допустим.
- `purge_finished` удаляет запись dead-letter только если задание ещё в `DEAD_LETTERED` (иначе запись просто сохраняется/не учитывается).
- Новые тесты — в `tests/test_refine_retries.py`; существующие не менялись.
- Существующие тесты, падающие из-за отменённых договорённостей (не правились): `test_dead_letter.py::test_purge_keeps_dead_letter`, `test_retry_policy.py::test_jitter_applied_and_capped`, `test_retry_worker.py::test_permanent_error_fails`, `test_retry_worker.py::test_non_retryable_on_last_attempt_and_subclass`.
