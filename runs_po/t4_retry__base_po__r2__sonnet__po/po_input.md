Повторы и dead-letter из JOBQ-212 сделаны. Все 42 теста проходят: 36 прежних без изменений и 6 новых в `tests/test_retry.py`. `dashboard.py` и `cli.py` не менял. Подписи новых статусов в отчёте появились сами, потому что отчёт строится по `JobStatus`.

## Что сделано
- **`jobq/retry.py`:** `RetryPolicy` с валидацией, `delay_for` и `is_retryable`. Расчёт задержки идёт через `float`. Иначе `factor=2` (int) при огромном `attempt` считал бы точное большое целое и зависал. При `base_delay=0` результат 0, при `OverflowError` задержка равна `max_delay`.
- **`errors.py`:** добавлена `PermanentJobError`.
- **`models.py`:** статусы `RETRY_SCHEDULED` и `DEAD_LETTERED` с подписями «Ожидает повтора» и «В dead-letter», а также `DeadLetterEntry`.
- **`queue.py`:**
  - Параметр `default_retry_policy`, методы `set_retry_policy`, `retry_policy_for`, `dead_letters`, `requeue_dead_letter`.
  - Новые методы `mark_retry_scheduled` и `mark_dead_lettered`.
  - Таблица переходов расширена.
- **`store.py`:** воркер теперь берёт и `RETRY_SCHEDULED`, когда наступил `run_at`.
- **`worker.py`:** параметр `rng`. Политика берётся в момент ошибки, и тип полностью заменяет дефолт. `rng` трогается только при планировании повтора и только при `jitter > 0`.
- **`metrics.py`:** счётчики `jobs.retried`, `jobs.dead_lettered`, `jobs.requeued`.
- **`__init__.py`:** экспортированы `RetryPolicy`, `PermanentJobError` и `DeadLetterEntry`.

## Решения там, где тикет молчал
- **`max_attempts=1`:** без повторов, но падение уходит в dead-letter, как сказал тимлид.
- **Исчерпание попыток:** условие `attempts >= max_attempts`.
- **`DEAD_LETTERED` считается терминальным.** `purge_finished` его не удаляет, иначе запись в dead-letter осталась бы без задания. Для dead-letter выход один — `requeue_dead_letter`.
- **`requeue_dead_letter`:** `attempts` не сбрасываю, потому что тикет это не требует. После возврата задание получает одну попытку до следующего dead-letter, если не сменить политику. Если нужен сброс, это одна строка. `finished_at` очищаю.
- **Ошибки `requeue_dead_letter`:** для задания не в dead-letter будет `InvalidTransitionError`, для неизвестного id — `JobNotFoundError`.
- **Отмена:** `cancel` работает и для `RETRY_SCHEDULED`.
- **`job.error` после успеха:** `mark_succeeded` теперь обнуляет `error`. Это нужно, чтобы выполнялось правило «у SUCCEEDED `error` всегда `None`» после успешного повтора.
- **Валидация `RetryPolicy`:** отвергаю `NaN`, `inf`, не-числа и bool. `max_delay=inf` («без потолка») поэтому недопустим. Ошибки конфигурации — `ConfigError`.
- **Jitter:** множитель применяется после ограничения `max_delay`, поэтому итог может чуть превысить `max_delay`, как написано в тикете.
- **Если `rng` у воркера не передан:** он создаёт свой `random.Random()`.
- **Обработчик не найден:** сразу `FAILED`, повторов нет.

Ограничение: `failure_rate` и блок «Последние ошибки» в дашборде считают только `FAILED`. Задания в dead-letter там не видны, но менять дашборд запрещено — это вопрос к другой команде.

Коммит не делал: вы о нём не просили.