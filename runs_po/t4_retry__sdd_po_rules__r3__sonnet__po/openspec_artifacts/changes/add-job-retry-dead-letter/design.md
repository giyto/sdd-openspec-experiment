## Context

Все переходы статусов идут через `JobQueue._transition` и таблицу `_TRANSITIONS`; воркер сейчас переводит упавшее задание в `FAILED` через `mark_failed`; готовые к запуску задания выбирает `InMemoryJobStore.due` (только `PENDING`). Отчёт `dashboard.py` перебирает `JobStatus` и берёт `status.label`, поэтому подписи достаточно добавить в `models.py`. Мотивацию и допущения см. в `proposal.md`, требования — в `specs/`.

## Goals / Non-Goals

**Goals:**
- Реализовать политику повторов и dead-letter, не меняя публичных сигнатур и существующих тестов.
- Сохранить поведение «как раньше», когда политики нет.

**Non-Goals:**
- Правки `dashboard.py`, `cli.py`, персистентность dead-letter, внешние зависимости.
- Хранение прежнего числа попыток в задании после `requeue_dead_letter` (оно доступно в логах).

## Decisions

1. **`jobq/retry.py` — самостоятельный модуль без зависимости от `queue`/`worker`.** `RetryPolicy` — `@dataclass(frozen=True)`; валидация и приведение `non_retryable` к `tuple` в `__post_init__` (через `object.__setattr__`). Ошибки — `ConfigError`. Проверка класса исключения: `isinstance(x, type) and issubclass(x, BaseException)`. Проверку чисел делаем в форме «not (условие корректности)», чтобы NaN отвергался. `bool` для `max_attempts` отвергаем.

2. **`delay_for` без переполнения.** Порядок: проверить `attempt >= 1`; если `base_delay == 0` → `0.0` (до возведения в степень, иначе `0 * inf`); если `factor == 1` → `min(base_delay, max_delay)`; иначе считать в `try: factor ** (attempt - 1)` с перехватом `OverflowError` → результат `max_delay`. Как вторая защита: если множитель `inf`, результат `max_delay`. Затем `min(raw, max_delay)`, затем при `jitter > 0` умножение на `rng.uniform(1 - jitter, 1 + jitter)` (`rng or random` — модульный генератор по умолчанию) и повторное ограничение `min(result, max_delay)`: `max_delay` — жёсткий потолок, джиттер его не превышает (при превышении возвращается ровно `max_delay`). Вызов `uniform` по-прежнему ровно один. Альтернатива — логарифмическое сравнение; отвергнута как менее читаемая и менее точная на границе. `attempt` — целое; при больших значениях `factor ** n` с целыми операндами не используется (factor приводится к `float`), чтобы не строить огромные int.

3. **Классификация.** `is_retryable`: `False`, если `isinstance(exc, PermanentJobError)` или `isinstance(exc, self.non_retryable)` (пустой tuple даёт `False`), иначе `True`. `PermanentJobError` добавляется в `errors.py` рядом с остальными.

4. **Статусы и таблица переходов.** В `JobStatus` добавляются `RETRY_SCHEDULED`, `DEAD_LETTERED` (в конец, чтобы порядок существующих строк отчёта не менялся), подписи в `_LABELS`. `_TERMINAL` не расширяется. Новая таблица:
   - `PENDING → {RUNNING, CANCELLED}` (как было);
   - `RETRY_SCHEDULED → {RUNNING, CANCELLED}`;
   - `RUNNING → {SUCCEEDED, FAILED, RETRY_SCHEDULED, DEAD_LETTERED}`;
   - `DEAD_LETTERED → {PENDING}` — используется только `requeue_dead_letter`.
   Так недопустимые переходы по-прежнему ловит `_transition` и выбрасывается `InvalidTransitionError`. Не терминальность обоих статусов нужна, чтобы `purge_finished` (отбор по `is_terminal`) их не удалял.

5. **Выборка.** `InMemoryJobStore.due` принимает `PENDING` и `RETRY_SCHEDULED`; сортировка `(run_at, seq)` прежняя. Нет смысла плодить отдельный метод: `next_due` и воркер не меняются.

6. **Методы очереди для воркера.** Добавляются `mark_retry_scheduled(job_id, error, run_at)` и `mark_dead_lettered(job_id, error)` по образцу `mark_failed`: переход, запись `error`, счётчик (`jobs.retried` / `jobs.dead_lettered`), для dead-letter — `finished_at` и запись `DeadLetterEntry` в приватный список. Счётчики увеличиваются внутри этих методов в момент перехода, как существующие. Решение о том, какой метод вызвать, принимает воркер (там известны исключение и `rng`); альтернатива — один метод `handle_failure` в очереди — отвергнута: воркер уже владеет разбором исключения, а очередь остаётся набором переходов.

7. **Хранение dead-letter.** `JobQueue._dead_letters: list[DeadLetterEntry]` в порядке попадания; `dead_letters()` возвращает копию. `requeue_dead_letter(job_id)`: `store.get` (даёт `JobNotFoundError`), `_transition(job, PENDING)` (даёт `InvalidTransitionError`, если статус не `DEAD_LETTERED`), затем `run_at = now`, `attempts = 0`, `error = None`, `finished_at = None`, удаление записи по `job_id` из списка, `jobs.requeued`. Все проверки идут до побочных эффектов. Запись ищется по `job_id`; у задания в `DEAD_LETTERED` она ровно одна, потому что повторное попадание возможно только после возврата, который запись удаляет.

8. **Политики в очереди.** `_default_retry_policy` и `_retry_policies: dict[str, RetryPolicy]`. `retry_policy_for` — `dict.get(job_type, default)` (политика типа заменяет дефолт целиком). Проверки типа аргумента и непустоты `job_type` — `ConfigError`. Политику читаем в момент ошибки (в воркере), а не сохраняем в задание.

9. **Логика воркера.** В `run_once`:
   - отсутствие обработчика — как раньше, `mark_failed` до любого обращения к политике;
   - при исключении: `policy = queue.retry_policy_for(job.job_type)`; `error = format_error(exc)`; `policy is None or not policy.is_retryable(exc)` → `mark_failed`; `job.attempts >= policy.max_attempts` → `mark_dead_lettered`; иначе `delay = policy.delay_for(job.attempts, self._rng)`, `run_at = queue.clock.now() + timedelta(seconds=delay)`, `mark_retry_scheduled`. `delay_for` вызывается только в последней ветке — этим гарантируется, что `rng` не трогается при `FAILED`/`DEAD_LETTERED`. `Worker.__init__` получает `rng` (keyword-only, после `name`), без `rng` передаётся `None`.
   - Ловится по-прежнему `except Exception`; `PermanentJobError` — наследник `Exception`.

10. **Метрики.** В `metrics.py` константы `JOBS_RETRIED`, `JOBS_DEAD_LETTERED`, `JOBS_REQUEUED`; докстрока модуля дополняется.

11. **Экспорт и документация.** В `jobq/__init__.py` добавляются `RetryPolicy`, `PermanentJobError`, `DeadLetterEntry`; в `README.md` — строка про `retry.py` и раздел про повторы.

12. **Тесты.** Новые файлы `tests/test_retry.py` (политика, `delay_for`, валидация), `tests/test_worker_retry.py` (исходы, rng, счётчики, dead-letter и requeue, purge, отчёт). Существующие тесты не меняются; используется `ManualClock` и подменный `rng` (`random.Random(seed)` или заглушка со счётчиком вызовов `uniform`).

## Risks / Trade-offs

- [Прежнее число попыток теряется из задания при возврате из dead-letter] → по решению владельца продукта оно смотрится в логах; запись `DeadLetterEntry` удаляется при возврате.
- [Очень большой `max_delay` при сложении с `now` может выйти за пределы `timedelta`/`datetime`] → конфигурация с задержкой порядка сотен миллиардов секунд не ожидается; специальной защиты не вводим.
- [Не терминальные `DEAD_LETTERED`/`RETRY_SCHEDULED` не попадают в `failure_rate` и «Последние ошибки» отчёта] → `dashboard.py` вне зоны правок; видно в строках статусов и счётчиках.
- [Валидация NaN/бесконечностей строже текста задачи] → допущение 2 из proposal; на допустимые по задаче значения не влияет.
