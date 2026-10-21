## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз (WH-214). Нужно удерживать товар под заказ с момента оформления, а неоплаченные резервы должны сами переставать действовать по TTL — без фоновых задач, по часам сервиса в момент обращения.

## What Changes

- В `Inventory` добавляются резервы: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, а также запросы `available` и `reserved`.
- Новые модели `ReservationStatus`, `ReservationLine`, `Reservation` (`warehouse/models.py`), ошибки `ReservationError` и наследники (`warehouse/errors.py`), константа `DEFAULT_RESERVATION_TTL = 15 минут` (`warehouse/reservations.py`; значение из обновления в обсуждении, а не 30 минут из исходного текста).
- Истечение вычисляется лениво при обращении, в журнал не пишется и физический остаток не трогает.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` дополнительно пишет обычные `ISSUE` по строкам.
- **Изменение поведения `issue`** (и `transfer` со склада-источника — см. design): они не могут забрать товар из активных резервов, при нехватке доступного — `InsufficientStockError`. Для кода без резервов поведение прежнее.
- Не меняются: формат строки журнала, конструктор `Inventory`, `receive/adjust/on_hand/stock_levels`, `cli.py`, `reports.py`, существующие тесты; новых зависимостей нет.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказы с TTL, подтверждение, отмена, продление, учёт резервов в доступном остатке и в расходных операциях, события журнала.

### Modified Capabilities
<!-- В openspec/specs пока нет спецификаций, изменять нечего. Влияние на issue/transfer описано в новой спецификации. -->

## Impact

- Код: `warehouse/inventory.py`, `warehouse/models.py`, `warehouse/errors.py`, `warehouse/storage.py` (хранение резервов), новый `warehouse/reservations.py`, экспорт в `warehouse/__init__.py`, строка в README.
- Журнал: новые типы событий. Внешняя выгрузка и `reports.movement_summary` увидят события `RESERVE` с полем `sku`; `movement_summary` заведёт для такого SKU запись с нулями, если у него нет других движений за период (см. design, «Риски»). `reports.py` по условию задачи не меняется.
- Зависимости: нет.
