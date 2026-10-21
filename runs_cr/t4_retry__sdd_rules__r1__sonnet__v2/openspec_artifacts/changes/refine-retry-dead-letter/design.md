## Context

Повторы и dead-letter реализованы в `retry.py`, `worker.py` (`_handle_failure`) и `queue.py` (`mark_dead_lettered`, `purge_finished`, `requeue_dead_letter`). Тикет JOBQ-237 пересматривает три договорённости JOBQ-212 и добавляет причину попадания в dead-letter, `RetryLaterError` и массовый requeue. Публичный API, заданный в тикете, переносится дословно.

## Goals / Non-Goals

**Goals:**
- Изменить исходы падения, джиттер и очистку, добавить `DeadLetterReason`, `RetryLaterError`, `requeue_all_dead_letters`.
- Сохранить совместимость старых вызовов.

**Non-Goals:**
- `dashboard.py`, `cli.py`, зависимости, персистентность dead-letter.

## Decisions

1. **Порядок проверок в `Worker._handle_failure`.** Нет политики → `FAILED`; не `policy.is_retryable(exc)` → `mark_dead_lettered(..., reason=NON_RETRYABLE)`; `attempts >= max_attempts` → `mark_dead_lettered(..., reason=EXHAUSTED)`; иначе повтор. Проверка неповторяемости стоит раньше исчерпания, поэтому на последней попытке причина `non_retryable` («причина важнее счётчика»). Отсутствие обработчика обрабатывается в `run_once` до `_handle_failure` и остаётся `FAILED`.
2. **`RetryLaterError` в воркере.** Если `isinstance(exc, RetryLaterError)` и повтор допустим, `delay = min(exc.retry_after, policy.max_delay)`; `delay_for` и `rng` не вызываются. Сигнатура `delay_for` не меняется. Альтернатива (параметр `delay_for(..., override=...)`) отвергнута: меняет публичный метод, а джиттер к этому значению не нужен.
3. **`RetryLaterError` в `errors.py`.** Конструктор `(message="", *, retry_after)` вызывает `super().__init__(message)`; валидация `retry_after` (число, не `bool`, `>= 0`, не `NaN`) бросает `ConfigError` из того же модуля. `inf` допустим, срезается потолком.
4. **Джиттер.** В `delay_for`: `delay *= source.uniform(1 - jitter, 1)`; повторное ограничение `min(delay, max_delay)` убирается как избыточное (множитель `<= 1`), но результат по-прежнему зажимается снизу нулём. При `jitter == 1` вызывается `uniform(1 - 1, 1)`, то есть `(0, 1)`.
5. **`DeadLetterEntry.reason`.** Последнее поле с умолчанием `DeadLetterReason.EXHAUSTED`, чтобы существующие конструкторы записей работали. `DeadLetterReason(str, Enum)` в `models.py`. `mark_dead_lettered(job_id, error, *, reason=EXHAUSTED)` — keyword-only добавление, старые вызовы целы.
6. **Очистка dead-letter.** `purge_finished` помимо терминальных заданий обходит `self._dead_letters`: запись с `dead_lettered_at <= cutoff` удаляется вместе с заданием из хранилища. Возраст считается от `dead_lettered_at`, а не от `finished_at` (у dead-letter задания он не выставляется). Удалённые записи пересобираются одним списком, порядок остальных сохраняется. Число удалённых и `jobs.purged` включают dead-letter задания.
7. **`requeue_all_dead_letters`.** Берёт снимок `dead_letters()`, фильтрует по `job_type` (если задан) и последовательно вызывает `requeue_dead_letter(entry.job_id)`; возвращает список заданий в порядке снимка. Пустой результат — `[]`. Пустая строка `job_type` — `ConfigError`, проверяется до любых изменений, поэтому массовая операция либо не меняет ничего, либо проходит целиком.
8. **Экспорт.** `DeadLetterReason` и `RetryLaterError` добавляются в `jobq/__init__.py` и `__all__`.

## Risks / Trade-offs

- [Поведение меняется для существующих развёртываний: задания с неповторяемыми ошибками теперь в dead-letter] → описано в proposal; счётчик `jobs.failed` для них не растёт.
- [`purge_finished` необратимо удаляет dead-letter, которые ещё не разобраны] → правило возраста задаёт вызывающий; по умолчанию `older_than=0.0` удаляет всё, как и для остальных завершённых.
- [Существующие тесты JOBQ-212 противоречат новому поведению] → список тестов в proposal; их обновляет реализация, прочие тесты не трогаются.
- [`RetryLaterError`, попавшая под `non_retryable`] → уходит в dead-letter как неповторяемая; считается осознанной настройкой.

## Open Questions

(нет; неоднозначности зафиксированы как допущения в proposal)
