## Why

Сейчас товар списывается только при отгрузке: пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз (WH-214). Нужно резервировать товар под заказ при оформлении, а неоплаченный резерв должен сам перестать действовать через TTL. Фоновых задач нет, поэтому истечение определяется по часам сервиса в момент обращения.

## What Changes

- В `Inventory` добавляются методы `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved`.
- Новые модели в `warehouse/models.py`: `ReservationStatus` (`ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`), `ReservationLine(warehouse, sku, qty)`, `Reservation(order_id, lines, created_at, expires_at, status)`.
- Новые ошибки в `warehouse/errors.py` (у всех атрибут `order_id`): `ReservationError(WarehouseError)`, `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`.
- Новый модуль `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (по решению маркетинга; значение 30 минут в исходном тексте тикета отменено).
- `Inventory.issue` (и `transfer` как расход со склада-источника) не забирает товар из чужих активных резервов: просят больше `available` — `InsufficientStockError`.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` пишет обычные `ISSUE` с `ref` = номер заказа. Формат строки журнала не меняется.
- Не меняются: конструктор `Inventory`, `receive/issue/transfer/adjust/on_hand/stock_levels` для кода без резервов, `cli.py`, `reports.py`, существующие тесты; зависимости не добавляются.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказ с TTL, подтверждение, отмена, продление, расчёт `available`/`reserved`, учёт резервов при расходе, события журнала.

### Modified Capabilities
<!-- В openspec/specs нет существующих спецификаций; поведение расхода без резервов не меняется. -->

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов), новый `warehouse/reservations.py`, экспорты в `warehouse/__init__.py`; новые тесты.
- Поведение `issue`/`transfer` меняется только при наличии активных резервов на позиции.
- Отчёты: `movement_summary` учитывает только `RECEIVE/ISSUE/ADJUST`, поэтому события резервов его не искажают, а `ISSUE` от `confirm` попадает в «расход» (ожидаемо).
- Зависимости и CLI не затрагиваются.
