Политика повторов и dead-letter очередь готовы. Все 48 тестов проходят: 36 прежних, которые я не менял, и 12 новых в `tests/test_retry.py`. Ничего не закоммичено.

## Что сделано
- **`jobq/retry.py`:** новый модуль с `RetryPolicy`, `delay_for` и `is_retryable`.
- **Переполнение:** `delay_for` не падает при `max_attempts=10000`. При `OverflowError` возвращается `max_delay`, а при `base_delay=0` задержка равна 0.
- **Валидация:** все перечисленные в тикете случаи дают `ConfigError`. `non_retryable` принимает список и хранит tuple.
- **Ошибки и модели:** добавлены `PermanentJobError`, статусы `RETRY_SCHEDULED` и `DEAD_LETTERED` (подписи «Ожидает повтора» и «В dead-letter») и `DeadLetterEntry`.
- **Очередь:** новые keyword-only параметр `default_retry_policy` и методы `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`. Политика типа заменяет дефолт целиком. Берётся та, что действует в момент ошибки.
- **Worker:** новый keyword-only параметр `rng`. Логика при падении обработчика:
  - Нет политики, ошибка неповторяемая (включая наследников `non_retryable` и `PermanentJobError`) или нет обработчика для типа: `FAILED`, даже на последней попытке.
  - Попытки кончились: `DEAD_LETTERED`, запись попадает в `dead_letters()`.
  - Иначе: `RETRY_SCHEDULED` с `run_at = now + delay_for(job.attempts, rng)`. `rng` используется только в этой ветке и только при `jitter > 0`.
- **Счётчики:** `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- **Остальное:** `store.due` берёт и `RETRY_SCHEDULED`, новые сущности экспортированы из `jobq`. `dashboard.py` и `cli.py` не тронуты: отчёт сам подхватывает новые статусы через `JobStatus`.

## Решения там, где тикет не был однозначным
- **`attempts` при `requeue_dead_letter`:** не сбрасываются, потому что тикет перечисляет, что меняется, а `attempts` там нет. Возвращённое задание при первой же ошибке снова попадёт в dead-letter, если `max_attempts` уже выбран. Если нужен свежий бюджет попыток, это одна строка в `requeue_dead_letter`.
- **`DEAD_LETTERED` не считается терминальным:** иначе `purge_finished` мог бы удалить задание, а запись в dead-letter осталась бы без него. `finished_at` при попадании в dead-letter ставится и при возврате очищается.
- **Отмена и требеование к статусу:**
  - `cancel` разрешён из `RETRY_SCHEDULED`, но не из `DEAD_LETTERED`.
  - `requeue_dead_letter` для несуществующего id бросает `JobNotFoundError`, для задания не в dead-letter — `InvalidTransitionError`.
- **Состояние dead-letter:** хранится в памяти очереди, а не в `store`. С персистентным хранилищем записи нужно будет восстанавливать из заданий со статусом `DEAD_LETTERED`.
- **Jitter может превысить `max_delay`:** по тикету множитель применяется к уже ограниченной задержке.
- **Проверка типов:** `set_retry_policy` и `default_retry_policy` принимают только `RetryPolicy` или `None`, иначе `ConfigError`. `attempt` в `delay_for` должен быть целым числом ≥ 1.