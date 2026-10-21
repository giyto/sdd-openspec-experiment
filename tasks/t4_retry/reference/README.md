# jobq

Небольшая очередь фоновых заданий для внутренних сервисов: задания ставятся в очередь
с временем запуска, синхронный воркер забирает готовые задания по порядку и вызывает
обработчик, зарегистрированный для типа задания. Хранилище — в памяти процесса.

## Модули

| Модуль              | Назначение                                                         |
|---------------------|--------------------------------------------------------------------|
| `jobq/models.py`    | `Job` (dataclass) и `JobStatus` (статусы, подписи для отчёта)      |
| `jobq/queue.py`     | `JobQueue`: постановка, выборка готовых, переходы статусов         |
| `jobq/worker.py`    | `Worker`: синхронное выполнение готовых заданий                    |
| `jobq/registry.py`  | `HandlerRegistry`: обработчики по типу задания                     |
| `jobq/store.py`     | `InMemoryJobStore`: хранилище в памяти                             |
| `jobq/metrics.py`   | `Metrics`: счётчики `jobs.*`                                       |
| `jobq/clock.py`     | `Clock`, `SystemClock`, `ManualClock`                              |
| `jobq/errors.py`    | иерархия исключений                                                |
| `jobq/dashboard.py` | текстовый отчёт для дежурных (используется другой командой)        |
| `jobq/cli.py`       | демо-утилита командной строки                                      |

## Быстрый пример

```python
from jobq import HandlerRegistry, JobQueue, ManualClock, Worker

clock = ManualClock()
queue = JobQueue(clock=clock)
registry = HandlerRegistry()
registry.register("send_email", lambda job: f"sent to {job.payload['to']}")

queue.enqueue("send_email", {"to": "ops@example.com"}, delay=30)
worker = Worker(queue, registry)
worker.run_pending()      # 0 — ещё рано
clock.advance(30)
worker.run_pending()      # 1
```

## Повторы и dead-letter

Политика повторов (`jobq.retry.RetryPolicy`) задаётся дефолтом очереди
(`JobQueue(default_retry_policy=...)`) или по типу (`queue.set_retry_policy(type, policy)`).
Упавшее задание переходит в `retry_scheduled` (экспоненциальная задержка с джиттером через
`Worker(rng=...)`), после исчерпания `max_attempts` — в `dead_lettered`
(`queue.dead_letters()`, `queue.requeue_dead_letter(job_id)`). Неповторяемые ошибки
(`non_retryable`, `PermanentJobError`) сразу дают `failed`.

## Соглашения

- **Время.** Никаких `datetime.now()` в коде пакета: время берётся только из часов,
  внедрённых в `JobQueue` (`queue.clock`). Все моменты — aware `datetime` в UTC.
  Длительности и задержки — `float` в секундах.
- **Ошибки.** Пакет выбрасывает только наследников `jobq.errors.JobqError`
  (`ConfigError`, `InvalidJobError`, `JobNotFoundError`, `InvalidTransitionError`, ...).
- **Статусы.** Статус задания меняется только через методы `JobQueue`, которые
  сверяются с таблицей допустимых переходов. Прямое присваивание `job.status` запрещено.
- **Текст ошибки** в `Job.error` — всегда `"ИмяКласса: сообщение"` (`worker.format_error`).
- **Метрики.** Счётчики называются `jobs.<событие>`, константы лежат в `jobq/metrics.py`.
  Метрики очереди доступны как `queue.metrics`.
- **Логирование** — через модульный логгер `logging.getLogger(__name__)`, без `print`
  (кроме `cli.py`).
- **Модели** — `dataclass`; публичные параметры-настройки передаются keyword-only.
- Только стандартная библиотека Python 3.13.

## Тесты

```
python -m pytest -q
```
