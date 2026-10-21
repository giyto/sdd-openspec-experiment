Повторы и dead-letter реализованы по тикету. Вся сюита проходит: 43 теста, из них новые в `tests/test_retry.py`. `dashboard.py`, `cli.py` и существующие тесты не тронуты. Отчёт дежурных подхватывает новые статусы сам, подписи «Ожидает повтора» и «В dead-letter» заданы в моделях.

## Что сделано
- **`jobq/retry.py`:** `RetryPolicy` с проверкой параметров (ошибка конфигурации — `ConfigError`), `delay_for` и `is_retryable`. Список `non_retryable` хранится как tuple.
- **`delay_for`:** при переполнении `float` (например, `attempt=5000`) возвращает `max_delay`, при `base_delay=0` даёт 0. Случайный множитель берётся только при `jitter > 0`.
- **`PermanentJobError`** добавлена в `errors.py`. Она никогда не повторяется.
- **Модели и очередь:** новые статусы и `DeadLetterEntry`. В очередь добавлены `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter` и параметр `default_retry_policy` (keyword-only).
- **Метрики:** счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- **Воркер:** принимает `rng`. Политика берётся на момент ошибки: у типа или, если её нет, у очереди. Неповторяемая ошибка и отсутствие обработчика дают `FAILED`, исчерпанные попытки — `DEAD_LETTERED`, иначе `RETRY_SCHEDULED`. `rng` вызывается только при реальном планировании повтора.
- **Хранилище и README:** `store.due` теперь выбирает и `RETRY_SCHEDULED`, когда наступил `run_at`. В README добавлен пункт о повторах.

## Решения там, где тикет не отвечал
1. **`attempts` при `requeue_dead_letter` не сбрасывается**, потому что тикет перечисляет, что меняется, и сброса там нет. Поэтому первая же ошибка после возврата снова отправит задание в dead-letter, если `max_attempts` уже исчерпан. Если нужен свежий бюджет попыток, это правка в одну строку. Скажите, если нужно.
2. **Статус `DEAD_LETTERED` считается терминальным.** `purge_finished` его не удаляет, чтобы записи в dead-letter не остались без заданий.
3. **`RETRY_SCHEDULED` можно отменить через `cancel`**, как `PENDING`. Из `DEAD_LETTERED` разрешён только переход в `PENDING` через `requeue_dead_letter`.
4. **При успехе после повтора `job.error` очищается**, потому что в контракте у `SUCCEEDED` ошибка всегда `None`.
5. **`requeue_dead_letter` для задания не из dead-letter** бросает `InvalidTransitionError`, для неизвестного id — `JobNotFoundError`. При возврате очищается и `finished_at`.
6. **Политику проверяют на тип:** `set_retry_policy` и `default_retry_policy` принимают только `RetryPolicy` или `None`. Нечисловые параметры политики и NaN тоже дают `ConfigError`.
7. **Если очередь создана на готовом хранилище** с заданиями в `DEAD_LETTERED`, записи dead-letter восстанавливаются из него при старте.
8. **`failure_rate` и блок «Последние ошибки» в отчёте** по-прежнему учитывают только `FAILED`: `dashboard.py` по ограничению не трогали. Задания в dead-letter в них не попадают, это стоит обсудить с владельцами дашборда.