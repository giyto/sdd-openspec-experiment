## Context

Все смены статуса идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; воркер сейчас на любую ошибку вызывает `mark_failed`. `InMemoryJobStore.due()` выбирает только `PENDING`. `dashboard.render_report` и `stats()` обходят все значения `JobStatus`, поэтому новые статусы и подписи попадут в отчёт без правок `dashboard.py`/`cli.py` (они не наши). Время только из `queue.clock`; ошибки конфигурации — `ConfigError`; только stdlib. Требования — в specs; мотивация — в proposal.md.

## Goals / Non-Goals

**Goals:**
- Политика, решение воркера и dead-letter без изменений существующих сигнатур и тестов.
- Детерминизм для тестов: ровно один `rng.uniform` на запланированный повтор.

**Non-Goals:**
- Персистентность журнала dead-letter, потокобезопасность, автоповтор из dead-letter, правки dashboard/cli.

## Decisions

1. **`jobq/retry.py` с замороженным dataclass.** Проверка в `__post_init__`, `non_retryable` нормализуется через `object.__setattr__(self, ..., tuple(...))`. Ошибки — `ConfigError` (не `ValueError`, по соглашению пакета).
2. **Безопасный расчёт задержки.** `base_delay == 0` → `0.0`; `factor == 1` → `base_delay`; иначе привести `factor` к `float` и считать `base * factor ** (attempt - 1)` в `try`, при `OverflowError` брать `inf`, затем `min(raw, max_delay)`. Приведение к `float` нужно, чтобы целый factor не породил гигантский int. Jitter применяется после ограничения, но `max_delay` — жёсткий потолок: если с разбросом результат больше `max_delay`, возвращается ровно `max_delay` (`min(capped * uniform, max_delay)`). Альтернатива «цикл до достижения max_delay» — O(attempt), хуже.
3. **Решение о судьбе задания — в воркере, переходы — в очереди.** В очереди новые `mark_retry_scheduled(job_id, error, delay)` и `mark_dead_lettered(job_id, error)` рядом с `mark_failed`; воркер вызывает `retry_policy_for`, `is_retryable`, `delay_for`. Так порядок проверок и обращение к `rng` в одном месте. `Worker(rng=None)` создаёт собственный `random.Random()`.
4. **Порядок проверок**: нет обработчика → FAILED до всякой политики; нет политики → FAILED; неповторяемая → FAILED; `attempts >= max_attempts` → DEAD_LETTERED; иначе RETRY_SCHEDULED. `delay_for` вызывается только в последней ветке.
5. **Таблица переходов**: `PENDING→{RUNNING,CANCELLED}`, `RETRY_SCHEDULED→{RUNNING,CANCELLED}`, `RUNNING→{SUCCEEDED,FAILED,RETRY_SCHEDULED,DEAD_LETTERED}`, `DEAD_LETTERED→{PENDING}` (достижим только из `requeue_dead_letter`; `cancel` бросит `InvalidTransitionError`, поэтому `cancel` должен проверять переход отдельно от requeue).
6. **Выборка готовых**: `store.due()` включает `PENDING` и `RETRY_SCHEDULED`, сортировка `(run_at, seq)` прежняя.
7. **Журнал** — список `DeadLetterEntry` в `JobQueue`, `dead_letters()` отдаёт копию; запись удаляется по `job_id` при возврате. Хранилище не расширяем.
8. **Терминальность**: `DEAD_LETTERED` терминален для воркера, но `purge_finished` его пропускает, иначе журнал ссылался бы на удалённое задание. `finished_at` ставится при входе в `DEAD_LETTERED` и сбрасывается при возврате. `RETRY_SCHEDULED` не терминален, `finished_at` не ставится.
9. **Возврат из dead-letter сбрасывает `attempts` в 0** (решение продукта): вернувшееся задание получает полный набор попыток, как новое. Прежнее число попыток остаётся в записи `DeadLetterEntry` до возврата и пишется в лог при возврате.
10. **Метрики**: константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`, инкремент в самих `mark_*`/`requeue_dead_letter`; обновить docstring модуля.
11. **Политика определяется в момент ошибки** (`retry_policy_for` вызывается в воркере), в задание не копируется.

## Допущения (неоднозначности тикета)

- Отмена `RETRY_SCHEDULED` разрешена (задание ещё не выполняется).
- `rng=None` у `delay_for` при `jitter>0` — генератор модуля `random`.
- NaN, `bool` и нецелый `max_attempts` — ошибка конфигурации.
- Не-`Exception` (`KeyboardInterrupt`) воркер не перехватывает, как и раньше.
- Существующий тест `test_stats_lists_every_status` сверяет ключи с `JobStatus`, поэтому остаётся зелёным; тест отчёта сверяет строки по `status.label`.

## Risks / Trade-offs

- [Две новые строки в отчёте и `stats()` могут удивить потребителей] → указано в proposal; `dashboard.py` не правим.
- [Переполнение при больших `attempt`] → отдельные тесты на 5000/10000 и `base_delay=0`.
- [Журнал в памяти теряется при рестарте] → вне объёма, как и само хранилище.
