## 1. Базовые типы

- [x] 1.1 В `jobq/models.py` добавить `DeadLetterReason(str, Enum)` (`exhausted`, `non_retryable`) и последнее поле `DeadLetterEntry.reason` со значением по умолчанию `EXHAUSTED`; тесты на значения и совместимость 5-аргументного конструктора
- [x] 1.2 В `jobq/errors.py` добавить `RetryLaterError(JobqError)` с `retry_after`, `ConfigError` при `< 0` и NaN; тесты: атрибут, сообщение по умолчанию, отрицательное значение, `issubclass`
- [x] 1.3 Экспортировать `DeadLetterReason`, `RetryLaterError` из `jobq/__init__.py`; проверить импорт

## 2. Политика

- [x] 2.1 В `RetryPolicy.delay_for` заменить множитель на `rng.uniform(1 - jitter, 1)`, зажим `[0, max_delay]` оставить; тесты: аргументы `(0.5, 1)`, результат 7.5, значение стаба >1 не увеличивает задержку, один вызов, `jitter=0` без вызова

## 3. Очередь

- [x] 3.1 `mark_dead_lettered(job_id, error, reason=DeadLetterReason.EXHAUSTED)`: сохранять причину в записи; тесты обеих причин и старого вызова
- [x] 3.2 `purge_finished`: удалять `DEAD_LETTERED` по `dead_lettered_at <= now - older_than`, убирать запись из `dead_letters()`, считать в результате и `jobs.purged`; тесты: старый, свежий, возраст от попадания в dead-letter, прочие статусы без изменений
- [x] 3.3 Добавить `requeue_all_dead_letters(job_type=None)` поверх `requeue_dead_letter`; тесты: все, по типу, порядок, пустой dead-letter, нет нужного типа, счётчик `jobs.requeued`, атрибуты перезапущенных заданий

## 4. Воркер

- [x] 4.1 Переписать `_handle_failure`: нет политики → `FAILED`; неповторяемая → dead-letter `non_retryable`; исчерпание → `exhausted`; иначе повтор. Тесты: первая и последняя попытка, `PermanentJobError`, класс из `non_retryable`, нет политики, нет обработчика, счётчики `jobs.failed`/`jobs.dead_lettered`, `rng` не трогается
- [x] 4.2 Обработка `RetryLaterError`: задержка `min(retry_after, max_delay)`, без `rng` и джиттера; на последней попытке — `exhausted`; тесты: в пределах потолка, `3600` при `max_delay=60`, `0`, последняя попытка, `jitter>0` с проверкой, что `uniform` не вызывался, без политики → `FAILED`

## 5. Завершение

- [x] 5.1 Обновить тесты, закреплявшие заменённое поведение (см. design.md, решение 7), и только их; перечислить изменённые тесты в отчёте
- [x] 5.2 Обновить `README.md` (причина, `RetryLaterError`, массовый возврат, предупреждение про `purge_finished` с `older_than=0`)
- [x] 5.3 Запустить `pytest` целиком; убедиться, что `git diff` не затрагивает `jobq/dashboard.py`, `jobq/cli.py` и нет новых зависимостей
