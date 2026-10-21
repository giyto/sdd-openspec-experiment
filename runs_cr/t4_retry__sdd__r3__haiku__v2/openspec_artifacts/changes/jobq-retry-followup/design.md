## Context

Текущий код (после `jobq-retry-dead-letter`): `Worker._decide_failure` в `jobq/worker.py` выбирает
`FAILED` / `DEAD_LETTERED` / `RETRY_SCHEDULED`; `RetryPolicy.delay_for` в `jobq/retry.py` считает джиттер
как `uniform(1 - jitter, 1 + jitter)`; `purge_finished` в `jobq/queue.py` пропускает все `DEAD_LETTERED`.
Мотивация и список изменений — см. `proposal.md`; поведение — см. `specs/`. Все переходы статусов по-прежнему
идут через `JobQueue._transition`, часы и метрики инжектируются, пакет использует только стандартную библиотеку.

## Goals / Non-Goals

**Goals**
- Решение о неповторяемой ошибке и о `RetryLaterError` принимает воркер, как и раньше; очередь только применяет переход.
- Формула джиттера и правило `retry_after` задаются одним местом (`RetryPolicy` для джиттера, воркер для `retry_after`).
- Сигнатуры существующих публичных методов сохраняются; новые параметры — keyword-only.

**Non-Goals**
- Без изменений в `jobq/dashboard.py`, `jobq/cli.py`, без новых зависимостей.
- Без персистентности, без фонового планировщика, без хранения причины вне `DeadLetterEntry`.
- Не меняем тесты (ограничение из тикета); см. раздел «Конфликт с существующими тестами».

## Decisions

### D1. Джиттер только сокращает задержку
`RetryPolicy.delay_for`: `capped * rng.uniform(1 - jitter, 1)`, затем `min(..., max_delay)` (clamp оставляем
как страховку, он уже не нужен по построению). Число обращений к `rng` не меняется: ровно один при `jitter > 0`.
Тест на «не позже расчётного» — в спеке, сценарий «Jitter never delays the retry».

### D2. `DeadLetterReason` и поле `reason`
`class DeadLetterReason(str, Enum)` в `jobq/models.py` с значениями `EXHAUSTED = "exhausted"`,
`NON_RETRYABLE = "non_retryable"`. `DeadLetterEntry.reason` — последнее поле dataclass.
**Отклонение от тикета:** у поля задано значение по умолчанию `DeadLetterReason.EXHAUSTED`. Причина: существующие
тесты создают `DeadLetterEntry` с пятью аргументами (`tests/test_retry_policy.py:53`, `tests/test_dead_letter.py:137,366`),
а по тикету тесты не меняются. До этой change все записи dead-letter появлялись только по исчерпанию попыток, так что
значение по умолчанию соответствует прежнему смыслу. Если нужна обязательность, это решается вместе с конфликтом тестов.
**Решение при apply:** значение по умолчанию оставлено (`EXHAUSTED`), обязательность не вводится, чтобы не менять
существующие тесты с пятью аргументами.

### D3. `RetryLaterError`
В `jobq/errors.py`: `class RetryLaterError(JobqError)` с `__init__(self, message: str = "", *, retry_after: float)`.
Проверка `retry_after < 0` и нечисловых значений — в `__init__`, исключение `ConfigError`. Это ранняя проверка:
ошибка конфигурации видна в месте, где её создают. Допущение: `ConfigError` из конструктора, брошенный внутри
обработчика, воспринимается воркером как обычная ошибка (попадает в ветку решения по политике). Так сделано
намеренно, чтобы воркер не требовал отдельной ветки для ошибок конструирования.
`retry_after` не-конечный (`nan`, `inf`) тоже отклоняется как `ConfigError`: иначе `min` не даст ограниченного значения
при `nan`. (Допущение, в тикете не сказано.)

### D4. Решение воркера (`Worker._decide_failure`)
```
policy = self._queue.retry_policy_for(job.job_type)
error = format_error(exc)
if policy is None:
    return self._queue.mark_failed(job.id, error)
if not policy.is_retryable(exc):
    return self._queue.mark_dead_lettered(job.id, error, reason=DeadLetterReason.NON_RETRYABLE)
if job.attempts >= policy.max_attempts:
    return self._queue.mark_dead_lettered(job.id, error, reason=DeadLetterReason.EXHAUSTED)
if isinstance(exc, RetryLaterError):
    delay = min(exc.retry_after, policy.max_delay)   # rng не трогаем
else:
    delay = policy.delay_for(job.attempts, self._rng)
return self._queue.mark_retry_scheduled(job.id, error, delay)
```
Порядок проверок: `policy is None` → `non_retryable` → исчерпание → повтор. Это выполняет решение тимлида:
неповторяемая ошибка на последней попытке получает `non_retryable`. `RetryLaterError` на последней попытке — `exhausted`.
`RetryLaterError` проходит через `is_retryable`, так что его можно добавить в `non_retryable` политики.
`UnknownJobTypeError` ветка в `run_once` не меняется (`FAILED`, политика не запрашивается).

### D5. Очередь: причина и очистка
- `mark_dead_lettered(job_id, error, *, reason: DeadLetterReason = DeadLetterReason.EXHAUSTED)`: keyword-only
  параметр с значением по умолчанию, старые вызовы (`tests/test_dead_letter.py:98,131,169`) работают.
  Причина записывается в `DeadLetterEntry.reason`.
- `purge_finished`: для `DEAD_LETTERED` использует `entry.dead_lettered_at` вместо `job.finished_at` (они равны, но
  правило по тикету — «от момента попадания в dead-letter»). Удаляет задание из хранилища и запись из `_dead_letters`.
  Счётчик `jobs.purged` увеличивается на число удалённых заданий, включая dead-letter.
  Пропуск `DEAD_LETTERED` в цикле убираем: исключение теперь только по возрасту.
  Допущение: `purge_finished` удаляет и dead-letter-задания (`store.remove`), так что это не просто удаление записи.
  Это соответствует «запись из `dead_letters()` тоже исчезает» и не оставляет висячих заданий.

### D6. `requeue_all_dead_letters(job_type=None)`
```
def requeue_all_dead_letters(self, job_type: str | None = None) -> list[Job]:
    entries = self.dead_letters()          # новый список, порядок вставки
    return [self.requeue_dead_letter(e.job_id)
            for e in entries if job_type is None or e.job_type == job_type]
```
Каждое задание идёт через `requeue_dead_letter` (тот же переход, та же метрика). Пустой результат — пустой список, без
исключения. `job_type` пустая строка — просто не совпадёт ни с одним типом (пустой список); валидацию не добавляем,
так как для `set_retry_policy` она уже есть, а здесь фильтр, а не конфигурация. (Допущение.)

### D7. Публичный API
`jobq/__init__.py` экспортирует `RetryLaterError` и `DeadLetterReason` (и добавляет их в `__all__`). Новые
методы `requeue_all_dead_letters` и параметр `reason` доступны без дополнительного экспорта.

## Конфликт с существующими тестами (нужно решить до apply)

Тикет требует «существующие тесты проекта не меняем», но часть из них проверяет прежнее поведение, которое тикет
отменяет. После реализации они упадут:

| Тест | Что проверяет | Почему падает |
|---|---|---|
| `tests/test_dead_letter.py::test_non_retryable_marks_failed` (≈ стр. 320) | `KeyError` при `non_retryable` → `FAILED` | теперь `DEAD_LETTERED` / `non_retryable` |
| `tests/test_dead_letter.py::test_permanent_error_on_last_attempt_marks_failed` (≈ стр. 330) | `PermanentJobError` на последней попытке → `FAILED` | теперь `DEAD_LETTERED` / `non_retryable` |
| `tests/test_dead_letter.py::test_rng_is_drawn_only_when_retry_is_scheduled` (≈ стр. 428) | `permanent`-тип → `FAILED` | теперь `DEAD_LETTERED` |

Остальные существующие тесты совместимы: `CountingRandom` в обоих файлах возвращает фиксированное значение,
поэтому джиттер `uniform(1 - j, 1)` не ломает их проверки; пятиаргументный `DeadLetterEntry` работает за счёт D2.

| `tests/test_dead_letter.py::test_purge_leaves_dead_letters_in_place` (≈ стр. 257) | `purge_finished` не трогает dead-letter | теперь dead-letter старше порога удаляется (spec «Purge removes old dead letters»); **найдено при apply, в исходной таблице не было** |

**Решение при apply (принято без пользователя, 2026-10-18):** выбран вариант 1. Существующие тесты не меняются,
четыре падения из таблицы принимаются и перечисляются в отчёте. Новые проверки на новое поведение добавлены
отдельным файлом `tests/test_retry_followup.py` и не трогают существующие. Вариант 2 (пометка старых тестов
как устаревших) требует явного согласия, поэтому не выполнялся.

Варианты (решает пользователь, в apply они не выбираются самостоятельно):
1. Оставить тесты как есть, принять три падения и сообщить об этом в отчёте по apply. Тесты не трогаем.
2. Добавить новые тесты на новое поведение рядом, старые пометить как устаревшие в отдельном изменении
   (нарушает «не меняем тесты», нужно явное согласие).
Рекомендация: вариант 2, но только после подтверждения; до этого в `tasks.md` зафиксированы проверки, которые
падают по ожидаемой причине.

## Risks / Trade-offs

- **[Изменение поведения для существующих политик]** Любой тип с политикой начинает класть неповторяемые ошибки
  в dead-letter. Это BREAKING по тикету, его надо отметить в релиз-нотах. → Типы без политики не затронуты.
- **[Очистка удаляет задания из хранилища]** `purge_finished` теперь удаляет и dead-letter записи старше порога.
  → Порог задаёт вызывающий код через `older_than`; по умолчанию `0` удалит всё, поэтому в README отметить.
- **[Значение по умолчанию у `reason`]** Отклонение от буквального текста тикета (D2). → Согласовать вместе с конфликтом тестов.
- **[`retry_after` без джиттера]** Все клиенты, которые получили `Retry-After`, придут в одну и ту же секунду.
  → Это решение тимлида (UPD 04.11), записано как правило; риск принят.
- **[Ограничение `max_delay` для `retry_after`]** `Retry-After: 3600` при `max_delay=60` даёт задержку 60 с: это
  ожидаемое поведение по тикету, но оно скрывает длинные ответы биллинга. → Логируем фактический `retry_after` и
  итоговую задержку на уровне `info` (в `Worker`).

## Migration Plan

Хранилище в памяти, миграций нет. Откат — revert коммита: новых данных на диске нет. Существующие вызовы без политики
ведут себя как раньше.

## Open Questions

- Конфликт тестов (раздел выше) — нужен ответ пользователя до apply.
- Допустим ли `default=EXHAUSTED` у `DeadLetterEntry.reason` вместо обязательного поля (D2) — подтвердить вместе с тестами.
