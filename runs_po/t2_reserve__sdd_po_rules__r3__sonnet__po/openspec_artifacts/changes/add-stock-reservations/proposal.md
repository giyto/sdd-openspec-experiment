## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать повторно (WH-214). Нужно резервировать товар под заказ в момент оформления; неоплаченный резерв должен сам перестать действовать по истечении TTL.

## What Changes

- В `Inventory` добавляются методы `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved` (сигнатуры — как в задаче, без изменений).
- В `warehouse/models.py` добавляются `ReservationStatus` (`ACTIVE`, `EXPIRED`, `CONFIRMED`, `CANCELLED`), `ReservationLine`, `Reservation`.
- В `warehouse/errors.py` добавляются `ReservationError(WarehouseError)` и наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у всех атрибут `order_id`.
- Новый модуль `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (значение уточнено в обсуждении: 15 минут, а не 30 из текста задачи).
- Истечение вычисляется лениво по часам сервиса в момент обращения: фоновых задач нет, в журнал истечение не пишется.
- `issue` (и `transfer` как расход со склада-источника) не может забрать товар из чужих активных резервов.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` пишет обычные `ISSUE` с `ref` = номер заказа.
- Не ломается: конструктор и `receive/issue/transfer/adjust/on_hand/stock_levels` для кода без резервов; `on_hand`/`stock_levels` по-прежнему показывают физический остаток. `cli.py`, `reports.py` и существующие тесты не меняются, зависимостей не добавляется.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказ с TTL, подтверждение, отмена, продление, запросы `available`/`reserved`, влияние резервов на расход и записи в журнале.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций; поведение `issue`/`transfer` при наличии резервов описано в новой capability, без резервов оно не меняется)

## Impact

- Код: `warehouse/inventory.py`, `warehouse/models.py`, `warehouse/errors.py`, `warehouse/__init__.py` (экспорт), новый `warehouse/reservations.py`, `warehouse/storage.py` (хранение резервов); новый `tests/test_reservations.py`.
- Формат строки журнала не меняется, добавляются только новые типы событий (внешняя выгрузка увидит новые `kind`).
- Зависимости: нет.
