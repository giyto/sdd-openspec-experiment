# JOBQ-212: Повторы упавших заданий и dead-letter

## Описание

Сейчас любое исключение в обработчике сразу переводит задание в `FAILED`, а дежурные каждое утро
вручную перезапускают десятки заданий, хотя почти все падения временные (таймауты почтового шлюза,
503 от биллинга). Нужна настраиваемая политика повторов с экспоненциальной задержкой. Задания,
которые так и не выполнились, должны попадать в отдельную dead-letter очередь, откуда их можно
осознанно вернуть в работу.

### Публичный API

```python
# jobq/retry.py — новый модуль
@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3        # всего попыток, включая первую
    base_delay: float = 1.0      # секунды
    factor: float = 2.0
    max_delay: float = 60.0      # секунды
    jitter: float = 0.0          # от 0 до 1
    non_retryable: tuple[type[BaseException], ...] = ()  # можно передать список, хранится tuple

    def delay_for(self, attempt: int, rng: random.Random | None = None) -> float: ...
    def is_retryable(self, exc: BaseException) -> bool: ...

# jobq/errors.py
class PermanentJobError(JobqError): ...

# jobq/models.py
JobStatus.RETRY_SCHEDULED   # "retry_scheduled"
JobStatus.DEAD_LETTERED     # "dead_lettered"

@dataclass(frozen=True)
class DeadLetterEntry:
    job_id: str
    job_type: str
    attempts: int
    error: str
    dead_lettered_at: datetime

# jobq/queue.py
JobQueue(store=None, *, clock=None, metrics=None, default_retry_policy: RetryPolicy | None = None)
JobQueue.set_retry_policy(job_type: str, policy: RetryPolicy | None) -> None
JobQueue.retry_policy_for(job_type: str) -> RetryPolicy | None
JobQueue.dead_letters() -> list[DeadLetterEntry]
JobQueue.requeue_dead_letter(job_id: str) -> Job

# jobq/worker.py
Worker(queue, registry, *, name="worker", rng: random.Random | None = None)
```

### Что сделать

- `delay_for(attempt)` возвращает задержку перед следующей попыткой, если упала попытка номер
  `attempt` (нумерация с 1): `base_delay * factor ** (attempt - 1)`, но не больше `max_delay`.
  При `jitter > 0` полученная (уже ограниченная) задержка умножается на
  `rng.uniform(1 - jitter, 1 + jitter)`.
- Некорректные параметры считаются ошибкой конфигурации, как везде в проекте. Это `max_attempts < 1`,
  `base_delay < 0`, `factor < 1`, `max_delay < base_delay`, `jitter` вне `[0, 1]`, элемент
  `non_retryable`, который не является классом исключения, и `attempt < 1` в `delay_for`.
- `is_retryable` возвращает `False` для исключений из `non_retryable` и всегда для
  `PermanentJobError`: обработчик бросает её, когда точно знает, что повтор не поможет.
- Политика задаётся по умолчанию для очереди и отдельно для типа задания (`set_retry_policy`,
  `None` снимает политику типа). Если нет ни той, ни другой, всё работает как сейчас.
- Когда обработчик упал, воркер переводит задание в один из статусов. Неповторяемая ошибка даёт
  `FAILED`. Если попытки кончились, статус становится `DEAD_LETTERED` и появляется запись
  в `dead_letters()`. В остальных случаях статус `RETRY_SCHEDULED` и `run_at` = сейчас +
  `delay_for(job.attempts, rng)`. В `job.error` всегда лежит последняя ошибка. Задание в
  `RETRY_SCHEDULED` воркер берёт, когда наступил его `run_at`, как любое другое.
- `dead_letters()` отдаёт записи в порядке попадания. `requeue_dead_letter` возвращает в работу
  то же задание (новое не создаётся): статус `PENDING`, `run_at` = сейчас, `error` очищается,
  запись из dead-letter убирается. `attempts` сохраняем, чтобы было видно, сколько всего было попыток.
- Задание, которое ждёт повтора, можно отменить так же, как обычное ожидающее. Из dead-letter
  выход один — `requeue_dead_letter`.
- Новые счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued` работают по тем же
  правилам, что и существующие.
- В отчёте дежурных новые статусы подписаны «Ожидает повтора» и «В dead-letter».

### Ограничения

- `jobq/dashboard.py` и `jobq/cli.py` не трогаем, ими владеет другая команда.
- Сигнатуры существующих публичных методов не меняем, новые параметры только keyword-only.
  Старые вызовы должны работать как раньше.
- Существующие тесты не меняем, новые добавлять можно. Новых зависимостей не добавляем.

---

## Обсуждение

**Ольга Кравец (QA)**, 12.10.2026 11:05
max_attempts=1 — это то же самое, что без политики? И ещё: у биллинга бывает max_attempts=10000,
а `2.0 ** 5000` во float падает с OverflowError.

**Артём Белов (тимлид)**, 12.10.2026 11:40
max_attempts=1 означает «без повторов, но в dead-letter», а не в FAILED. delay_for должна работать
для любого attempt, в том числе при base_delay=0, и результат всегда должен быть в [0, max_delay].
Уточню: max_delay — жёсткий потолок, джиттер его тоже не пробивает.

**Ольга Кравец (QA)**, 12.10.2026 14:20
Для тестов хочу, чтобы rng был предсказуемым: один uniform на одну задержку, при jitter=0 его не
трогаем. Если задание уходит в FAILED или dead-letter, задержку ведь не считаем?

**Артём Белов (тимлид)**, 12.10.2026 14:32
Да. rng трогаем, только когда реально планируем повтор.

**Дмитрий Сафонов (дежурный)**, 13.10.2026 10:02
Вопросы из эксплуатации. 1) При non_retryable=(ValueError,) наследники ValueError тоже не
повторяются? 2) purge_finished по крону чистит все терминальные задания. Dead-letter он не снесёт?
3) Если для типа нет обработчика, это тоже будем повторять?

**Артём Белов (тимлид)**, 13.10.2026 10:30
1) Да, как обычный except, с учётом наследования. Неповторяемая ошибка всегда даёт FAILED, даже на
последней попытке, в dead-letter такие задания не кладём. 2) purge_finished dead-letter не трогает,
задания лежат там до requeue. 3) Нет, это ошибка конфигурации: сразу FAILED, как сейчас.

**Марина Лебедева (аналитик)**, 14.10.2026 09:15
Политика типа и дефолт очереди сливаются по полям? Например, если в политике типа не задан
non_retryable, его берём из дефолта?

**Артём Белов (тимлид)**, 14.10.2026 16:48
Не сливаются: политика типа заменяет дефолт целиком. Берём ту политику, которая действует в момент
ошибки, а не ту, что была при enqueue.
UPD по requeue: attempts всё-таки обнуляем, иначе перезапущенное задание после первой же ошибки
снова уйдёт в dead-letter. Сколько попыток было до перезапуска, видно в логах.
