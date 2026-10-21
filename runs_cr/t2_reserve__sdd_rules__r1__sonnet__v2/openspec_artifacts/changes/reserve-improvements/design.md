## Context

Хранилище (`InMemoryStore`) держит одну запись `ReservationRecord` на `order_id`; `EXPIRED` вычисляется (`effective_status`), в записи не хранится. Новый `reserve` по неактивному заказу уже перезаписывает запись. Журнал только на добавление (`EventLog`), формат строки менять нельзя. Публичный API из задачи (`Availability`, `MAX_RESERVATION_LIFETIME`, `reservations`, `availability`, `sweep_expired`) переносится дословно; мотивация — в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:**
- Реализовать поведение из specs, не меняя сигнатуры старого API и формат журнала.
- Сохранить атомарность: любая ошибка не меняет ни состояние, ни журнал.

**Non-Goals:**
- Изменения `warehouse/cli.py`, `warehouse/reports.py`, существующих тестов, новые зависимости.
- Фоновый планировщик, хранение истории заменённых резервов, запись истечения в `reserve`/`get_reservation`.

## Decisions

- **Предел и TTL — константы в `reservations.py`.** `DEFAULT_RESERVATION_TTL = 20 мин`, `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`. Значение 2 часа взято из комментария в обсуждении (он новее и перекрывает «один час» в тексте задачи). Проверка `ttl > MAX` в `reserve` — рядом с `_validate_ttl`, до любых изменений состояния. `extend` эту проверку не использует, а ограничивает результат: `min(now + ttl, created_at + MAX)`, далее прежняя логика «не сокращать».
- **Замена в `reserve`.** После валидации: если существующий резерв `CONFIRMED` → `DuplicateReservationError`. Проверка наличия идёт по сумме строк позиции с учётом того, что вклад заменяемого активного резерва в `reserved` не считается. Только после успешной проверки: `RESERVE_CANCEL` по старому, `status = CANCELLED` у старой записи, новая запись через `put_reservation`, `RESERVE` по строкам. Альтернатива «сначала отменить, потом резервировать с откатом» отвергнута: проще и надёжнее сначала проверить.
- **Возврат в `cancel`.** Для `CONFIRMED`: по каждой строке в порядке строк увеличить остаток и записать `RECEIVE` с `ref=order_id`, затем `status = CANCELLED` и `RESERVE_CANCEL`. Валидация складов и SKU не повторяется (данные уже валидны), формат события тот же, что у `receive`. `CONFIRMED` не зависит от часов, поэтому срок значения не имеет.
- **Однократность `sweep_expired`.** В `ReservationRecord` добавляется поле-флаг (например, `expire_logged: bool = False`). Метод перебирает записи, выбирает `effective_status == EXPIRED` и не помеченные, сортирует по `(expires_at, order_id)`, пишет `RESERVE_EXPIRE` со временем `now`, ставит флаг. Замена создаёт новую запись с чистым флагом, поэтому новый резерв того же заказа обрабатывается отдельно (требование из обсуждения). Альтернатива «множество (order_id, expires_at)» отвергнута: хрупка при совпадении срока у двух резервов одного заказа.
- **`reservations`.** Снимки `snapshot(record, now)` по всем записям, фильтр по статусу, сортировка `(created_at, order_id)`.
- **`availability`.** Множество позиций из `store.positions()` (остаток > 0) и из строк активных резервов; сортировка по `(warehouse, sku)`; значения через внутренние `_reserved`/`_available` с одним `now`, чтобы совпадать с публичными методами. Фильтр по складу — как в `stock_levels`.
- **`Availability`** — frozen dataclass в `models.py`; экспорт из `warehouse/__init__.py` по образцу `StockLevel`, если он там экспортируется.

## Risks / Trade-offs

- [Истёкший резерв заменяется до вызова `sweep_expired`: запись перезаписывается, `RESERVE_EXPIRE` по нему уже не будет записан] → принято допущение: история заменённых резервов не хранится; планировщик вызывает `sweep_expired` достаточно часто.
- [Поведение `reserve`/`cancel` меняется несовместимо с прежними договорённостями] → целевое изменение; существующие тесты на `DuplicateReservationError` для активного резерва и `ReservationStateError` при отмене подтверждённого устареют, но по рамкам задачи не меняются — отразить расхождение в отчёте при реализации.
- [`RESERVE_CANCEL` пишется, а новый резерв не создаётся] → порядок «сначала проверить, потом писать» это исключает.

## Assumptions

- Предельный срок — 2 часа (последнее уточнение в обсуждении), а не 1 час из текста задачи.
- `ttl` ровно равный пределу допустим; превышение — `ValidationError`.
- Замена с `RESERVE_CANCEL` применяется только к активному резерву; для истёкшего/отменённого/возвращённого поведение прежнее (перезапись без `RESERVE_CANCEL`).
- Возврат не зависит от текущего `available` и не повторяет валидацию складов и SKU.
- `reservations(status)` не проверяет тип `status`; неизвестное значение даёт пустой список.
- Время события `RESERVE_EXPIRE` — текущее время по часам сервиса.

## Implementation Notes

- Старые тесты `tests/test_reservations.py` не менялись и устарели по замыслу изменения (9 падений): `test_effective_status_boundary`, `test_reserve_multi_warehouse`, `test_expiry`, `test_extend_never_shortens`, `test_extend_errors`, `test_confirm_expired_and_repeated`, `test_cancel_expired_and_confirmed`, `test_expired_reservation_does_not_block_issue` завязаны на прежний TTL 15 минут (время продвигается на 15 минут, а резерв теперь живёт 20); `test_duplicates_and_replacement` ожидает `DuplicateReservationError` для активного резерва и `ReservationStateError` при отмене подтверждённого. Остальные 68 существующих тестов проходят.
- Новое поведение покрыто тестами в `tests/test_reserve_improvements.py` (новый файл).
- `reserve` при замене исключает заменяемый заказ из `_reserved` через параметр `exclude`; запись о старом резерве перезаписывается новой.
