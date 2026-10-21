## Context

Изменения ложатся на уже реализованные `Worker._handle_failure`, `JobQueue.mark_dead_lettered`,
`JobQueue.purge_finished` и `RetryPolicy.delay_for` из `jobq-retry-dead-letter`. Все переходы статусов
по-прежнему идут через `JobQueue._transition`. Время берётся из `queue.clock`. Новых зависимостей нет.

Требования вынесены в `specs/job-retry/spec.md` и `specs/dead-letter/spec.md`. Здесь описано, как их
реализовать и какие неоднозначности решены.

## Goals / Non-Goals

**Goals:**
- Решение «повторить / в dead-letter / в FAILED» остаётся только в воркере, а причина попадания в
  dead-letter фиксируется в записи.
- Старые вызовы публичного API работают без изменений.
- Новое поведение покрыто новыми тестами в отдельных файлах.

**Non-Goals:**
- Изменения `jobq/dashboard.py` и `jobq/cli.py` (ограничение тикета).
- Персистентность dead-letter (хранилище по-прежнему в памяти).
- Изменение существующих тестов (ограничение тикета; см. конфликт ниже).

## Decisions

**1. `DeadLetterReason` в `jobq/models.py`.** `class DeadLetterReason(str, Enum)` с `EXHAUSTED = "exhausted"`
и `NON_RETRYABLE = "non_retryable"`, по образцу `JobStatus`.

**2. `DeadLetterEntry.reason` — последнее поле с значением по умолчанию `EXHAUSTED`.** Ticket пишет поле
без умолчания, но `tests/test_retry.py::test_dead_letter_entry_is_frozen` создаёт `DeadLetterEntry` без
`reason`. Без умолчания этот существующий тест упадёт на конструкторе. До этого изменения любая запись
dead-letter означала исчерпание попыток, поэтому `EXHAUSTED` — историческое значение по умолчанию.

**3. `RetryLaterError` в `jobq/errors.py`.** Конструктор `__init__(self, message: str = "", *, retry_after: float)`.
Проверка в конструкторе: `retry_after` — `int`/`float` (не `bool`), конечное и `>= 0`; иначе `ConfigError`.
Это тот же приём, что у `RetryPolicy.__post_init__`: ошибка конфигурации видна в месте, где её создали.
Сообщение передаётся в `super().__init__(message)`, поэтому `format_error` даёт `"RetryLaterError: <текст>"`.

**4. `mark_dead_lettered(job_id, error, *, reason=DeadLetterReason.EXHAUSTED)`.** Keyword-only параметр с
умолчанием сохраняет прежний вызов `mark_dead_lettered(job_id, error)` (метод появился в предыдущем
change, но старые вызовы должны работать). Запись создаётся с `reason=reason`.

**5. Порядок решения в `Worker._handle_failure`.** Воркер проверяет условия по порядку:
1. Политики нет → `mark_failed` (как раньше).
2. `not policy.is_retryable(exc)` (включая `PermanentJobError`) → `mark_dead_lettered(..., reason=NON_RETRYABLE)`.
   Проверка стоит раньше исчерпания, поэтому на последней попытке причина — `non_retryable` (решение тимлида).
3. `job.attempts >= policy.max_attempts` → `mark_dead_lettered(..., reason=EXHAUSTED)`.
4. `isinstance(exc, RetryLaterError)` → `schedule_retry` с `run_at = now + min(exc.retry_after, policy.max_delay)`.
   `rng` не используется. Джиттер не применяется (решение тимлида от 04.11).
5. Иначе `schedule_retry` с `policy.delay_for(job.attempts, self._rng)`, как сейчас.

Неизвестный тип задания по-прежнему уходит в `FAILED` до `_handle_failure`, поэтому политика на него не
действует (требование «unknown job type fails without retry» не меняется).

**6. Джиттер в `RetryPolicy.delay_for`.** Множитель меняется на `rng.uniform(1 - self.jitter, 1)`.
Ограничение `min(..., self.max_delay)` после умножения сохраняется, хотя при множителе не больше 1 оно
избыточно. Причина: `tests/test_retry.py::test_jitter_is_applied_then_capped_again` подставляет `rng`,
который возвращает `1.5`, и ожидает `10.0`. Без cap результат был бы `15.0`. Сигнатура не меняется.

**7. `purge_finished` для dead-letter.** Ветка `if job.status is JobStatus.DEAD_LETTERED: continue`
удаляется. Вместо неё для такого задания берётся запись `self._dead_letters[job.id]` и сравнивается
`entry.dead_lettered_at <= cutoff`. Значение `dead_lettered_at` совпадает с `finished_at` задания, но
используется запись, потому что так явно видно, от какого момента считается возраст. При удалении задания
удаляется и запись (`self._dead_letters.pop(job.id)`). Счётчик `jobs.purged` увеличивается как обычно.
Удаление делается по снимку `self._store.all()`, как сейчас, поэтому изменение словаря во время обхода
безопасно.

**8. `requeue_all_dead_letters(job_type=None)`.**
```python
if job_type == "":
    raise ConfigError("job_type must be a non-empty string")
entries = [e for e in self._dead_letters.values() if job_type is None or e.job_type == job_type]
return [self.requeue_dead_letter(e.job_id) for e in entries]
```
Список `entries` строится до перезапуска, потому что `requeue_dead_letter` удаляет записи из словаря.
Каждое задание идёт через `requeue_dead_letter`, поэтому лог и `jobs.requeued` работают так же.

**9. Экспорт.** `RetryLaterError` и `DeadLetterReason` добавляются в `jobq/__init__.py` и `__all__`.

**10. README.** В разделе «Соглашения» пункт о повторах дополняется: `RetryLaterError`, причины dead-letter,
очистка по возрасту, `requeue_all_dead_letters`. Прежнее утверждение «исчерпавшие попытки попадают в
dead-letter» дополняется неповторяемыми ошибками. Раздел «Модули» не меняется.

## Конфликт с существующими тестами

Ticket запрещает менять существующие тесты, но четыре из них проверяют поведение, которое JOBQ-237 отменяет.
После реализации они упадут. Это ожидаемо, и тесты не переписываются:

| Тест | Ожидает сейчас | После change |
|---|---|---|
| `tests/test_dead_letter.py::test_permanent_error_fails_job` | `FAILED` | `DEAD_LETTERED`, reason `non_retryable` |
| `tests/test_dead_letter.py::test_non_retryable_error_fails_even_on_last_attempt` | `FAILED`, пустой dead-letter | `DEAD_LETTERED`, reason `non_retryable` |
| `tests/test_dead_letter.py::test_rng_is_not_consulted_for_non_retryable_failure` | `FAILED` (проверка rng проходит) | `DEAD_LETTERED`; падает только проверка статуса |
| `tests/test_dead_letter.py::test_purge_keeps_dead_letters` | `purge_finished == 0` | `purge_finished == 1` |

Решение на этот момент: реализуем поведение из тикета, существующие тесты не трогаем, в отчёте перечисляем
падения с выводом pytest. Обновить эти четыре теста можно только с явным согласием команды (рекомендация:
отдельный коммит, который меняет ожидания этих тестов на новые).

Другие существующие тесты проходят без изменений: сценарии джиттера в `test_retry.py` дают тот же результат
из-за сохранённого `min`, `test_worker.py` не использует политику повторов.

## Assumptions (неоднозначности, решённые без участия пользователя)

- **`RetryLaterError` без политики** → `FAILED`. Тикет описывает `RetryLaterError` как «следующую попытку
  планируем через retry_after вместо задержки из политики», то есть при отсутствии политики повторов нет.
- **`RetryLaterError` с классом в `non_retryable`** → неповторяемая ошибка (`non_retryable`). Правило 2 проверяется раньше.
- **`RetryLaterError(retry_after=0)`** → `run_at = now`. Задание берётся следующим `run_once`.
- **`RetryLaterError`, сконструированный с неверным `retry_after`** → `ConfigError` поднимается в обработчике.
  Воркер ловит его как обычное исключение, и задание становится повторяемой ошибкой. Ошибка конфигурации
  видна в тексте задания (`ConfigError: ...`) и в логе.
- **`requeue_all_dead_letters("")`** → `ConfigError`, как у `set_retry_policy`. Тикет этого случая не описывает.
- **`DeadLetterEntry.reason`** — значение по умолчанию `EXHAUSTED` (решение 2).
- **`purge_finished` и запись в dead-letter** — возраст считается от `dead_lettered_at`, а не от времени
  последней ошибки (сценарий в spec).

## Risks / Trade-offs

- **[Четыре существующих теста упадут]** → Зафиксировано выше; решение о их обновлении принимает команда.
- **[Очистка удаляет dead-letter без просмотра]** Записи, которые кому-то нужны, пропадут после
  `purge_finished`. → Требование тикета. Перезапуск нужного до очистки — в `requeue_dead_letter` или
  `requeue_all_dead_letters`.
- **[Джиттер вниз снижает среднюю задержку]** Повторы чаще, чем раньше, но не позже расчётного времени.
  → Требование SLA почты.

## Migration Plan

Миграции данных нет: состояние в памяти. Старые вызовы работают. Поведение изменяется для заданий с политикой
повторов, у которых падает `PermanentJobError` или неповторяемое исключение: они теперь в dead-letter, а не
`FAILED`. Откат — возврат `_handle_failure` к прежней ветке `mark_failed`.
