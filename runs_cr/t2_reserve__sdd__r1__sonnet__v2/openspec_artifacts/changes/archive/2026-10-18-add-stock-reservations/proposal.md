## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз (WH-214). Нужно резервировать товар под заказ в момент оформления; неоплаченный резерв должен сам перестать действовать через TTL без фоновых задач.

## What Changes

- Новые методы `Inventory`: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved`.
- Новые модели `ReservationStatus`, `ReservationLine`, `Reservation`; новые ошибки `ReservationError` и четыре наследника (у всех атрибут `order_id`); константа `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (значение из обновления маркетинга, не 30).
- Истечение вычисляется лениво по часам сервиса в момент обращения; в `expires_at` резерв уже не действует; в журнал истечение не пишется.
- `issue` (и `transfer` с исходного склада, см. допущения в design.md) не может забрать товар из активных резервов.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` пишет обычные `ISSUE` с `ref` = номер заказа.
- Совместимость: конструктор и `receive/issue/transfer/adjust/on_hand/stock_levels` без резервов работают как раньше; `cli.py`, `reports.py`, существующие тесты и зависимости не меняются. Не BREAKING.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказ с TTL, подтверждение, отмена, продление, запросы `available`/`reserved`, влияние резервов на `issue`, события журнала.

### Modified Capabilities

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, новый `warehouse/reservations.py`, `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов), `warehouse/__init__.py` (экспорт).
- Журнал: новые типы событий; формат строки не меняется. `reports.movement_summary` учтёт `ISSUE` от `confirm` как обычный расход — это ожидаемо.
- Зависимости: нет. Тесты: добавляются новые, существующие не меняются.
