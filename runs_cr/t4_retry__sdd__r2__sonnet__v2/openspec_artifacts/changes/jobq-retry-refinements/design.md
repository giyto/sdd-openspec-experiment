## Context

Решение об ошибке принимает `Worker._handle_error`; переходы и dead-letter живут в `JobQueue` (`mark_dead_lettered`, `requeue_dead_letter`, `purge_finished`); задержку считает `RetryPolicy.delay_for`. Задание в dead-letter не терминально и `finished_at` у него `None`, поэтому текущая очистка его не видит. Мотивация — в proposal.md.

## Goals / Non-Goals

**Goals:**
- Реализовать поведение из спеков без изменения сигнатур существующих публичных методов.

**Non-Goals:**
- `dashboard.py`, `cli.py`, новые зависимости, изменение существующих тестов.
- Новые метрики или статусы.

## Decisions

1. **Причина dead-letter.** `DeadLetterReason(str, Enum)` в `models.py`; `DeadLetterEntry.reason` последним полем со значением по умолчанию `EXHAUSTED` (старые вызовы конструктора работают). `mark_dead_lettered(job_id, error, *, reason=DeadLetterReason.EXHAUSTED)` — необязательный именованный параметр. Отдельный метод отвергнут как дублирование.
2. **Ветвление в воркере.** Порядок: нет политики → `FAILED`; `not is_retryable` → dead-letter `NON_RETRYABLE`; `attempts >= max_attempts` → `EXHAUSTED`; иначе повтор. Неповторяемость проверяется раньше счётчика, поэтому «причина важнее счётчика» выполняется сама. Задержка и `rng` в первых трёх ветках не трогаются.
3. **RetryLaterError.** Класс в `errors.py` (наследник `JobqError`), валидация в `__init__` (`ConfigError`). В ветке повтора воркер при `isinstance(exc, RetryLaterError)` берёт `min(exc.retry_after, policy.max_delay)` вместо `policy.delay_for`, `rng` не передаётся. `is_retryable` не меняется. Отдельный метод политики для ограничения отвергнут: лишний публичный API.
4. **Джиттер.** В `delay_for` диапазон `uniform(1 - jitter, 1)`; зажим `[0, max_delay]` остаётся как защита от некорректного генератора.
5. **Очистка.** `purge_finished` дополнительно обходит копию `_dead_letters`: при `dead_lettered_at <= cutoff` удаляет запись и задание из хранилища, прибавляет к общему `removed` (один `jobs.purged`). Основной цикл по терминальным заданиям не меняется.
6. **Массовый возврат.** `requeue_all_dead_letters(job_type=None)`: снимок `dead_letters()`, фильтр по типу, последовательные вызовы `requeue_dead_letter`, возврат списка заданий. Валидация типа — `ConfigError`, как в `set_retry_policy`.
7. **Экспорт.** `DeadLetterReason` и `RetryLaterError` добавить в `jobq/__init__.py` и `__all__`; обновить докстринг `PermanentJobError` (больше не «сразу FAILED»).

## Risks / Trade-offs

- [Существующие тесты фиксируют отменённое поведение (неповторяемая ошибка → `FAILED`, джиттер вверх, `purge_finished` не трогает dead-letter) и упадут] → править их запрещено; на этапе apply перечислить такие тесты в отчёте как ожидаемые, остальные должны проходить.
- [Необратимое удаление заданий из dead-letter] → ограничено параметром `older_than`; его значение по умолчанию `0.0` очищает всё старое, это следует из тикета — предупредить дежурных.
- [Противоречие в тикете про джиттер для `RetryLaterError`] → принята поздняя правка (без джиттера), зафиксировано в proposal.md.
- [Записи без причины] → хранилище в памяти, миграции нет; значение по умолчанию `EXHAUSTED`.
