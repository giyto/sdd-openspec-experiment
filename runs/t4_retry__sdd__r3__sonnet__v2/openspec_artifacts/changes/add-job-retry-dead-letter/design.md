## Context

Мотивация и состав изменений: см. `proposal.md`, требования: `specs/`. Текущее устройство:

- Все смены статуса идут через `JobQueue._transition` по таблице `_TRANSITIONS`; воркер зовёт `mark_running/mark_succeeded/mark_failed`.
- `InMemoryJobStore.due()` выбирает только `PENDING`.
- `purge_finished` удаляет всё, что `is_terminal` и имеет `finished_at`.
- `mark_succeeded` не очищает `error` (раньше это было не нужно: успех наступал только с первой попытки без ошибки).
- `dashboard.render_report` перебирает `JobStatus` и берёт `label`; `dashboard.py` и `cli.py` менять нельзя.
- Ошибки конфигурации — `ConfigError`; только стандартная библиотека; время только из `queue.clock`.

## Goals / Non-Goals

**Goals:**
- Повторы и dead-letter без изменения поведения при отсутствии политики.
- Детерминированность для тестов: расход `rng` строго по одному `uniform` на реально планируемый повтор.

**Non-Goals:**
- Персистентное хранилище dead-letter, ручное «перемещение» заданий в dead-letter, повтор по `BaseException`, настройка политики на уровне отдельного задания, изменения `dashboard.py`/`cli.py` (включая `failure_rate`).

## Decisions

1. **`RetryPolicy` — frozen dataclass с `__post_init__`-валидацией** в `jobq/retry.py`. `non_retryable` приводится к `tuple` через `object.__setattr__`. Валидация числовых полей написана в форме `not (x >= 0)` и проверяет конечность (`math.isfinite`), чтобы NaN/inf отвергались `ConfigError`. `bool` в `max_attempts` отвергается. Альтернатива — пропускать inf в `max_delay`: отвергнута, т.к. ломает гарантию «результат в `[0, max_delay]`» как конечного числа.

2. **Безопасный `delay_for`.** Порядок: проверка `attempt >= 1` → `raw`: если `base_delay == 0` → `0.0`; если `factor == 1` → `base_delay`; иначе `base_delay * factor ** (attempt - 1)` в `try/except OverflowError` (при переполнении `raw = max_delay`); `delay = min(raw, max_delay)` (inf тоже срезается). Затем при `jitter > 0`: `delay *= rng.uniform(1 - jitter, 1 + jitter)` и `min(max(delay, 0.0), max_delay)`. Один вызов `uniform` на задержку, при `jitter == 0` `rng` не трогается. Если `rng is None` при `jitter > 0`, используется общий модульный `random`. При `base_delay == 0` и `jitter > 0` `uniform` всё равно вызывается один раз, чтобы расход `rng` не зависел от значений. Альтернатива — вычисление через логарифмы: сложнее и менее точно.

3. **Новые статусы и переходы.** `_TRANSITIONS`:
   - `PENDING → {RUNNING, CANCELLED}` (без изменений);
   - `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`;
   - `RETRY_SCHEDULED → {RUNNING, CANCELLED}`;
   - `DEAD_LETTERED → {PENDING}` (только через `requeue_dead_letter`).
   Отмена `DEAD_LETTERED` отклоняется естественным образом таблицей.

4. **`is_terminal`:** `RETRY_SCHEDULED` — не терминальный; `DEAD_LETTERED` — терминальный (воркер его не берёт, выход только через `requeue_dead_letter`), но `purge_finished` явно его исключает (`job.status is not DEAD_LETTERED`). Так не нужно менять смысл `is_terminal` для остального кода; `finished_at` у dead-letter заполняется временем перехода. Альтернатива — считать его нетерминальным: тогда исказился бы смысл «воркер больше не выполнит».

5. **`due()` в хранилище** выбирает `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`. Это единственная правка `store.py`; сигнатуры не меняются.

6. **Dead-letter живёт в `JobQueue`:** упорядоченный `dict[job_id, DeadLetterEntry]` (порядок вставки = порядок попадания). `dead_letters()` возвращает `list(values())`. Хранилище задания остаётся единственным источником правды о самом задании; запись содержит снимок `attempts`/`error`/времени. Альтернатива — выводить список из `store.by_status(DEAD_LETTERED)`: теряет порядок попадания и `dead_lettered_at`.

7. **API перехода для воркера.** Новые методы очереди (по образцу существующих `mark_*`): `mark_retry_scheduled(job_id, error, run_at)` (ставит `error`, `run_at`, счётчик `jobs.retried`), `mark_dead_lettered(job_id, error)` (ставит `error`, `finished_at`, создаёт запись, счётчик `jobs.dead_lettered`). Счётчик увеличивается ровно в момент перехода, как у `jobs.failed`. `mark_succeeded` теперь делает `job.error = None` (инвариант «у SUCCEEDED error всегда None» из docstring `Job`).

8. **Решение воркера** выносится в небольшой приватный метод `Worker._handle_failure(job, exc)`: политика берётся через `queue.retry_policy_for(job.job_type)` в момент ошибки; порядок проверок — политика → `is_retryable` → `attempts >= max_attempts` → расписание повтора, ровно как в спецификации. `delay_for` и `rng` вызываются только в последней ветке, поэтому `rng` не расходуется на `FAILED`/`DEAD_LETTERED`. Ветка «нет обработчика» (`UnknownJobTypeError`) остаётся прямым `mark_failed` до обращения к политике. `except Exception` сохраняется как раньше. `rng` по умолчанию — `random.Random()`, создаваемый воркером при `rng=None`.

9. **`requeue_dead_letter`:** проверка существования (`JobNotFoundError` из хранилища), `_transition(job, PENDING)` (даёт `InvalidTransitionError` для не-dead-letter), затем `run_at = now`, `error = None`, `attempts = 0`, `finished_at = None`, `result = None`, удаление записи, `jobs.requeued`. Обнуление `attempts` взято из последнего уточнения тимлида (UPD в обсуждении), оно переопределяет формулировку «attempts сохраняем» в описании; прежнее число попыток остаётся в логах (`logger.info` при requeue с прежним значением) и в `DeadLetterEntry`, пока запись не удалена.

10. **Валидация в очереди:** `default_retry_policy` и `set_retry_policy` проверяют тип (`RetryPolicy` или `None`) и непустой `job_type`, иначе `ConfigError`. Политики типов хранятся в `dict[str, RetryPolicy]`; `retry_policy_for` возвращает политику типа, иначе дефолт. Слияния полей нет.

11. **Метрики и отчёт.** Константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `metrics.py` + обновление docstring модуля. `_LABELS` дополняется «Ожидает повтора» и «В dead-letter» (влезают в `LABEL_WIDTH=18`). Отчёт подхватывает их без правок `dashboard.py`.

12. **Экспорт и документация.** `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry` экспортируются из `jobq/__init__.py`; README получает модуль `retry.py` и раздел о повторах.

## Risks / Trade-offs

- [Dead-letter хранится в памяти очереди, а не в хранилище; новая `JobQueue` над тем же `store` не увидит записей] → хранилище и так в памяти процесса; зафиксировать в README. Статус задания в store остаётся `DEAD_LETTERED`.
- [`failure_rate` в `dashboard.py` не учитывает dead-letter как провал] → файл не наш; сообщить владельцам в описании PR.
- [Существующий тест `stats()` проверяет множество ключей по `JobStatus`] → новые ключи появляются автоматически, тест остаётся зелёным.
- [Смена `is_terminal`/due может затронуть чужой код] → `grep` показал использование только в `queue.py`/`store.py`; проверить полным прогоном тестов.
- [Допущение: `max_attempts` ограничивает `attempts` после `requeue` заново с нуля] → зафиксировано в п.9 и в спецификации.

## Migration Plan

Изменение обратно совместимо: без политики поведение прежнее. Откат — revert коммита; в сохранённых данных нет (хранилище в памяти).

## Open Questions

- Нужно ли отдельное публичное чтение `DeadLetterEntry` по `job_id`? Сейчас достаточно `dead_letters()`; можно добавить позже без влияния на спецификации.
