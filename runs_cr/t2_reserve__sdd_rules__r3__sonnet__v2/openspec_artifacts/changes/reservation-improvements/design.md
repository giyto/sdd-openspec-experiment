## Context

`Inventory` хранит резервы как изменяемые `ReservationRecord` в `InMemoryStore` (по одному на `order_id`); статус `EXPIRED` вычисляется по часам (`effective_status`) и в журнал не пишется. Формат журнала менять нельзя; публичный API из задачи (`Availability`, `MAX_RESERVATION_LIFETIME`, `reservations`, `availability`, `sweep_expired`) используется дословно.

## Goals / Non-Goals

**Goals:** реализовать замену, возврат, новые TTL и предел, три новых метода, сохранив атомарность (ошибка не меняет ни резервы, ни журнал).
**Non-Goals:** CLI, отчёты, фоновые задачи, изменение существующих тестов, новые зависимости.

## Decisions

- **Замена резерва.** В `reserve` после валидации: если существующий резерв `ACTIVE`, при проверке наличия его количество по позиции добавляется к свободному (`free = max(0, on_hand - (reserved - qty заменяемого по позиции))`). Только после успешной проверки пишутся `RESERVE_CANCEL` старого, затем `RESERVE` нового. Старый record получает `CANCELLED`, новый `ReservationRecord` кладётся вместо него. Подтверждённый — по-прежнему `DuplicateReservationError`; истёкший или отменённый — как раньше, без `RESERVE_CANCEL`.
- **Возврат.** В `cancel` для `CONFIRMED`: по строкам увеличить остаток на `qty` и записать `RECEIVE` (`ref` = order_id) приватным помощником по образцу `_write_issue`, затем статус `CANCELLED` и `RESERVE_CANCEL`. Статус `CANCELLED` делает повторный `cancel` no-op.
- **Предел срока.** `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`, `DEFAULT_RESERVATION_TTL = timedelta(minutes=20)` в `reservations.py`. В `reserve` `ttl > MAX` даёт `ValidationError` до любых изменений. В `extend` `new_expires = min(now + ttl, created_at + MAX)`; дальше прежняя логика: событие только при реальном росте срока.
- **Учёт истечения.** В `ReservationRecord` добавляется поле `expire_logged: bool = False`. Замена и повторный резерв создают новый record, поэтому «другой резерв» учитывается отдельно без составного ключа. `sweep_expired` выбирает records со статусом `EXPIRED` и `not expire_logged`, сортирует по `(expires_at, order_id)`, пишет `RESERVE_EXPIRE(order, expires)`, ставит флаг и возвращает список. Статусы и остатки не затрагиваются.
- **Обзор и доступность.** `reservations`: снимки всех records через `snapshot`, сортировка `(created_at, order_id)`, фильтр по эффективному статусу. `availability`: объединение позиций из `store.positions()` и позиций активных резервов, фильтр по складу, сортировка `(warehouse, sku)`; значения берутся из `get_qty`, `_reserved`, `_available`, чтобы совпадать с одноимёнными методами.

## Risks / Trade-offs

- Существующие тесты на 15 минут, `DuplicateReservationError` для активного резерва и `ReservationStateError` при отмене подтверждённого перестанут проходить; тесты не меняем по условию задачи, расхождение сообщаем явно.
- Резерв, истёкший и затем вытесненный новым `reserve` до вызова `sweep_expired`, остаётся неучтённым (хранилище не хранит историю). Принимаем: планировщик вызывает sweep достаточно часто.

## Assumptions

- Предел равен двум часам: уточнение Ольги Смирновой от 10.11 приоритетнее текста задачи («один час»).
- Для замены действует вся валидация `reserve`, включая предел `ttl`.
- `RESERVE_EXPIRE` пишется со временем события = текущее время часов; `expires` = `expires_at` резерва.
- Возврат не проверяет `available` и работает при любом остатке на складе.
- `extend` не ограничивает сам `ttl` пределом, только итоговый срок.
