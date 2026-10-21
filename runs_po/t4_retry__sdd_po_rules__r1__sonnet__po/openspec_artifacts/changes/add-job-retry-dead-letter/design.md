## Context

Сейчас `Worker.run_once` при любом `Exception` вызывает `queue.mark_failed`. Статусы меняются только через `JobQueue._transition` по таблице `_TRANSITIONS`; `InMemoryJobStore.due` отбирает только `PENDING`; `purge_finished` удаляет все терминальные задания; `dashboard.render_report` перебирает `JobStatus` и берёт `label`, поэтому новые статусы появятся в отчёте без правок `dashboard.py`/`cli.py` (они закрыты для изменений). Мотивация — в proposal.md.

## Goals / Non-Goals

**Goals:**
- Повторы и dead-letter без изменения поведения при отсутствии политик.
- Детерминированность для тестов: время только из `queue.clock`, случайность только из `rng`.

**Non-Goals:**
- Персистентность dead-letter, повторы вне воркера, асинхронность, изменение `dashboard.py`/`cli.py`.
- Выделение отдельного публичного класса хранилища dead-letter.

## Decisions

**1. `RetryPolicy` как frozen dataclass с `__post_init__`.** Валидация в `__post_init__`, `non_retryable` нормализуется в `tuple` через `object.__setattr__`. Все нарушения — `ConfigError`, включая нечисловые типы и NaN (проверки в форме `not (x >= 0)`), чтобы не выпускать `TypeError`. Класс исключения проверяется `isinstance(x, type) and issubclass(x, BaseException)`. Нечитаемый как последовательность `non_retryable` (например, одиночный класс) — `ConfigError`. Альтернатива — валидация в `JobQueue`: отвергнута, политика должна быть корректной сразу при создании.

**2. Безопасный `delay_for`.** Порядок: проверка `attempt >= 1`; если `base_delay == 0` — база 0; иначе при `factor == 1` — `base_delay`; иначе `factor ** (attempt - 1)` внутри `try/except OverflowError` с результатом `max_delay` (для больших `attempt` ограничение достигается задолго до переполнения, поэтому при `OverflowError` ответ однозначно `max_delay`); затем `min(..., max_delay)`. Умножение `base_delay * inf` не даёт исключения и отсекается `min`, а `0 * inf` (NaN) исключён отдельной веткой `base_delay == 0`. Jitter — после ограничения: `min(delay * rng.uniform(1 - j, 1 + j), max_delay)` (`max_delay` — жёсткий потолок и для джиттера); при `jitter == 0` ветка не обращается к `rng`. Если `rng is None` и `jitter > 0`, создаётся `random.Random()` (глобальное состояние `random` не используется). Альтернатива — вычисление через логарифмы: сложнее и теряет точность на малых значениях.

**3. Таблица переходов.** `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`, `RETRY_SCHEDULED → {RUNNING, CANCELLED}`, `DEAD_LETTERED → {PENDING}`. Переход `DEAD_LETTERED → PENDING` выполняет только `requeue_dead_letter`. Новые методы очереди `mark_retry_scheduled(job_id, error, delay)` и `mark_dead_lettered(job_id, error)` (по образцу `mark_failed`) инкапсулируют переход, запись `error`, счётчик и запись в dead-letter. `mark_succeeded` дополнительно очищает `error`, чтобы выполнить инвариант «у SUCCEEDED `error` всегда `None`» после успешного повтора. Метод `mark_retry_scheduled` принимает уже посчитанную задержку: `rng` остаётся ответственностью воркера, а очередь не знает о политиках при переходе.

**4. Решение принимает воркер, политику даёт очередь.** Воркер в `except Exception` вызывает `queue.retry_policy_for(job.job_type)` в момент ошибки и применяет цепочку: нет политики → `mark_failed`; `not is_retryable` → `mark_failed`; `job.attempts >= max_attempts` → `mark_dead_lettered`; иначе `delay_for(job.attempts, rng)` → `mark_retry_scheduled`. `delay_for` вызывается только в последней ветке — этим обеспечивается «`rng` трогаем, только когда реально планируем повтор». Ветка `UnknownJobTypeError` не меняется (всегда `FAILED`). Политики хранятся в очереди (`dict[str, RetryPolicy]` + дефолт), политика типа заменяет дефолт целиком, без слияния. Воркер держит `self._rng = rng if rng is not None else random.Random()`.

**5. Хранилище.** `InMemoryJobStore.due` выбирает `PENDING` и `RETRY_SCHEDULED` с `run_at <= now`, сортировка прежняя `(run_at, seq)`. Изменение внутри `store.py`, публичная сигнатура та же.

**6. Dead-letter внутри `JobQueue`.** Список `DeadLetterEntry` (frozen dataclass в `models.py`) в порядке добавления; `dead_letters()` возвращает копию. `requeue_dead_letter` сначала находит задание (`JobNotFoundError`), затем делает переход (`InvalidTransitionError` до любых изменений), после чего выставляет `run_at = now`, `error = None`, `finished_at = None`, удаляет запись по `job_id`, увеличивает `jobs.requeued`. `attempts` сбрасывается в 0 (полный набор попыток, как у нового задания). Альтернатива — хранить dead-letter в `store`: потребовала бы расширять `InMemoryJobStore`, а выбранный вариант оставляет интерфейс хранилища нетронутым.

**7. Терминальность и очистка.** `DEAD_LETTERED.is_terminal == True` (воркер его не берёт), `RETRY_SCHEDULED` — нет. `purge_finished` явно пропускает `DEAD_LETTERED`, иначе запись в `dead_letters()` осталась бы без задания, а «единственный выход — requeue». `finished_at` при dead-letter ставится, при requeue сбрасывается. `cancel` допускается из `RETRY_SCHEDULED` (через таблицу переходов), из `DEAD_LETTERED` — нет.

**8. Метрики и модели.** В `metrics.py` константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` со значениями `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`; счётчик растёт внутри метода перехода, сразу после успешного `_transition`. Подписи новых статусов добавляются в `_LABELS`. Новые имена экспортируются из `jobq/__init__.py` (`RetryPolicy`, `PermanentJobError`, `DeadLetterEntry`). Публичные сигнатуры из задачи реализуются дословно, новые параметры — keyword-only после `*`.

## Risks / Trade-offs

- [Две новые строки в `stats()` и отчёте меняют вывод для потребителей] → существующие тесты проверяют статусы через перебор `JobStatus`; изменение нужно по задаче, `dashboard.py` не правим.
- [Задание в `RETRY_SCHEDULED` можно отменить] → допущение, безопасно, задание не выполняется.
- [Dead-letter не переживает перезапуск процесса] → как и хранилище, в памяти; вне объёма.
- [`purge_finished` не удаляет dead-letter] → память освобождается только после `requeue_dead_letter`; приемлемо для малого объёма.
