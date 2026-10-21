## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать повторно (WH-214). Нужно резервировать товар под заказ в момент оформления, а неоплаченный резерв должен сам прекращать действовать по TTL.

## What Changes

- В `Inventory` добавляются операции `reserve`, `confirm`, `cancel`, `extend`, `get_reservation` и запросы `available`, `reserved`.
- Новые публичные типы: `ReservationStatus`, `ReservationLine`, `Reservation` (`warehouse/models.py`), иерархия `ReservationError` и наследники (`warehouse/errors.py`), `DEFAULT_RESERVATION_TTL = 15 минут` (`warehouse/reservations.py`).
- Истечение резерва вычисляется лениво по часам сервиса в момент обращения; фоновых задач нет, в журнал истечение не пишется.
- `issue` (и `transfer` как расход со склада-источника) больше не может забирать товар из чужих активных резервов.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` пишет обычные `ISSUE`. Формат строки журнала не меняется.
- Старое поведение для кода без резервов не меняется. `cli.py`, `reports.py`, существующие тесты и зависимости не трогаются.

## Capabilities

### New Capabilities
- `order-reservations`: резервирование товара под заказы с TTL, подтверждение, отмена, продление, расчёт доступного остатка и влияние резервов на расход.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций; ограничение расхода активными резервами описано в новой спецификации)

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, `warehouse/reservations.py` (новый), `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов), `warehouse/__init__.py` (экспорт).
- Публичный API `Inventory` расширяется; существующие сигнатуры сохраняются.
- Внешняя выгрузка журнала получает новые типы событий; существующие строки не меняются.
- Новых зависимостей нет.
