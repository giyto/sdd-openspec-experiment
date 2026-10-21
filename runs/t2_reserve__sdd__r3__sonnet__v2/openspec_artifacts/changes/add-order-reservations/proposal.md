## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз (WH-214). Нужно удерживать товар под заказ с момента оформления и автоматически освобождать его, если заказ не оплачен.

## What Changes

- В `Inventory` добавляются резервы под заказ: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved`.
- Резерв не меняет физический остаток; `confirm` превращает его в отгрузку (обычные `ISSUE` по строкам).
- Истечение по TTL (по умолчанию 15 минут) определяется лениво, по часам сервиса в момент обращения; фоновых задач нет, истечение в журнал не пишется.
- `issue` (и `transfer` как расход со склада-источника) больше не забирает товар из чужих активных резервов.
- Новые модели `ReservationStatus`, `ReservationLine`, `Reservation`, ошибки `Reservation*Error`, константа `DEFAULT_RESERVATION_TTL`.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`. Формат строки журнала не меняется.
- Не ломается: конструктор и `receive/issue/transfer/adjust/on_hand/stock_levels` для кода без резервов; `on_hand`/`stock_levels` показывают физический остаток. `cli.py`, `reports.py` и существующие тесты не меняются, новых зависимостей нет.

## Capabilities

### New Capabilities
- `order-reservations`: резервирование товара под заказы с TTL, подтверждением, отменой, продлением, запросами `available`/`reserved` и защитой резервов от `issue`/`transfer`.

### Modified Capabilities

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, новый `warehouse/reservations.py`, `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов), `warehouse/__init__.py` (экспорт новых имён), новые тесты.
- Публичный API `Inventory` расширяется; существующие сигнатуры не меняются.
- Зависимости, CLI и отчёты не затронуты. `movement_summary` увидит `ISSUE` от `confirm` как обычный расход; события `RESERVE*` без поля `qty` в ветках сводки не участвуют.
