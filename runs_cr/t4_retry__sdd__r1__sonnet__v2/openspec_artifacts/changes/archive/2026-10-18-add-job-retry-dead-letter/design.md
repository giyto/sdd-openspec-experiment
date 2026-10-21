## Context

Все смены статуса идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; воркер сейчас вызывает `mark_failed` на любую ошибку; `InMemoryJobStore.due` выбирает только `PENDING`; `purge_finished` удаляет всё с `is_terminal`; `mark_succeeded` не трогает `error`, а модель обещает, что у `SUCCEEDED` `error` всегда `None`. `dashboard.render_report` и `stats()` перебирают `JobStatus`, поэтому новые статусы появятся в отчёте сами. Мотивацию см. в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:**
- Минимальное расширение существующей машины статусов без обхода `_transition`.
- Решение о статусе принимает воркер, а очередь предоставляет явные `mark_*` методы и владеет dead-letter.

**Non-Goals:**
- Не трогаем `dashboard.py`, `cli.py`; отчёт не получает отдельной секции dead-letter и `failure_rate` не меняется.
- Нет персистентности dead-letter, нет изменения сигнатур существующих методов.

## Decisions

1. **`RetryPolicy` — frozen dataclass с валидацией в `__post_init__`**; `non_retryable` нормализуется в tuple через `object.__setattr__`. Проверка: `isinstance(x, type) and issubclass(x, BaseException)`; одиночный класс вместо последовательности — `ConfigError`. NaN отвергаем явно (сравнения с NaN иначе проходят молча). Альтернатива (валидация при использовании) отвергнута: ошибки конфигурации должны всплывать при создании.

2. **Расчёт задержки без переполнения.** `base_delay == 0` → 0 без возведения в степень. Иначе `factor ** (attempt - 1)` в `try/except OverflowError` → `max_delay`; бесконечный или превысивший потолок результат ограничивается `min(..., max_delay)`. При `factor == 1` степень не считается (результат `base_delay`). Далее при `jitter > 0` ровно один `rng.uniform(1 - jitter, 1 + jitter)`, результат зажимается в `[0, max_delay]` (джиттер потолок не пробивает). Альтернатива «ограничить attempt константой» отвергнута: ломает точность для малых factor, близких к 1. Рассмотрено вычисление через логарифмы — сложнее и менее читаемо, чем перехват `OverflowError`. Для `rng=None` используется модуль `random`.

3. **Состояние dead-letter в очереди**: упорядоченный словарь `job_id -> DeadLetterEntry` в `JobQueue`. `dead_letters()` отдаёт новый список. Альтернатива — вычислять из заданий в хранилище: теряется порядок попадания и `dead_lettered_at`. Следствие: dead-letter привязан к экземпляру очереди, а не к хранилищу (допущение).

4. **Статусы и переходы.** `PENDING→{RUNNING, CANCELLED}`, `RETRY_SCHEDULED→{RUNNING, CANCELLED}`, `RUNNING→{SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`, `DEAD_LETTERED→{PENDING}` (используется только `requeue_dead_letter`; `cancel` в dead-letter отвергается таблицей). Новые статусы не terminal: `RETRY_SCHEDULED` ещё будет выполняться, а `DEAD_LETTERED` покидается через requeue, и `purge_finished` его не снесёт. Дополнительно `finished_at` для них не выставляется, поэтому `purge_finished` не удалит их и по условию `finished_at`; явная проверка на `DEAD_LETTERED` в `purge_finished` добавляется как защита. `store.due` выбирает `PENDING` и `RETRY_SCHEDULED`.

5. **API очереди для воркера:** `mark_retry_scheduled(job_id, error, run_at)`, `mark_dead_lettered(job_id, error)` (создаёт запись и счётчик), `requeue_dead_letter`. Воркер вызывает `queue.retry_policy_for(job.job_type)` в момент ошибки, затем: нет политики → `mark_failed`; `not is_retryable` → `mark_failed`; `attempts >= max_attempts` → `mark_dead_lettered`; иначе `delay_for` (единственное место, где трогается `rng`) → `mark_retry_scheduled` с `run_at = clock.now() + timedelta(seconds=delay)`. Ошибка «нет обработчика» остаётся прямым `mark_failed` до ветки политики.

6. **`requeue_dead_letter`:** сначала `store.get` (JobNotFoundError), затем `_transition` в `PENDING` (InvalidTransitionError до любых изменений), после этого `run_at=now`, `error=None`, `attempts=0`, удаление записи, `jobs.requeued`. По финальному решению тимлида `attempts` обнуляется (ранняя формулировка про сохранение отменена); количество попыток до перезапуска остаётся в логах, поэтому `requeue_dead_letter` логирует число прошлых попыток на уровне INFO.

7. **`mark_succeeded` очищает `error`**, чтобы сохранить инвариант модели «у SUCCEEDED `error is None`» после повторов.

8. **Конструктор:** `JobQueue(..., default_retry_policy=None)` — keyword-only, проверка типа (`ConfigError`). `Worker(..., rng=None)` — keyword-only; по умолчанию `random.Random()`.

9. **Метрики:** константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED` в `metrics.py`; увеличиваются внутри `mark_*`/`requeue_dead_letter` после успешного `_transition`, как существующие.

## Risks / Trade-offs

- [`run_pending` с `base_delay=0` обрабатывает повторы в том же вызове] → цикл конечен благодаря `max_attempts`; зафиксировать тестом.
- [Хранилище, переданное в очередь, уже содержит `DEAD_LETTERED` задания (другой экземпляр очереди)] → их нет в `dead_letters()` и `requeue_dead_letter` для них не сработает корректно; допущение: dead-letter живёт в рамках экземпляра очереди, in-memory хранилище не разделяется.
- [Отчёт не показывает ошибки dead-letter, `failure_rate` их не учитывает] → вне зоны (dashboard принадлежит другой команде); отметить в README.
- [Новые статусы расширяют `stats()`] → существующие тесты сверяют ключи с `JobStatus`; внешним потребителям сообщить.

## Migration Plan

Чисто аддитивное изменение: без политик поведение прежнее. Откат — удаление политик (или версии кода): активные `RETRY_SCHEDULED`/`DEAD_LETTERED` задания в памяти процесса при перезапуске теряются вместе с хранилищем.

## Решения при реализации

- Сигнатура `RetryPolicy.delay_for(attempt, rng=None)`: `rng` — необязательный второй аргумент; воркер передаёт свой генератор, без него используется модуль `random`.
- `DeadLetterEntry` — frozen dataclass в `jobq/models.py`.
- `Worker` по умолчанию создаёт `random.Random()`.
