## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз (WH-214). Нужно резервировать товар под заказ в момент оформления, а неоплаченный резерв должен сам перестать действовать через TTL. Фоновых задач нет, поэтому истечение определяется по часам сервиса в момент обращения.

## What Changes

- Новые операции `Inventory`: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved`.
- Новые модели `ReservationStatus`, `ReservationLine`, `Reservation` и ошибки `ReservationError` (+ `NotFound`, `Expired`, `State`, `Duplicate`) с атрибутом `order_id`.
- `DEFAULT_RESERVATION_TTL = 15 минут` (по обсуждению в задаче, а не 30 минут из исходного текста).
- `issue` и `transfer` (расход со склада-источника) не могут забирать товар из активных резервов.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` пишет обычные `ISSUE`.
- Старый API и формат журнала не меняются; код без резервов ведёт себя как раньше. `cli.py`, `reports.py` и существующие тесты не трогаем, зависимостей не добавляем.

## Capabilities

### New Capabilities
- `order-reservations`: резервирование товара под заказ с TTL, подтверждение, отмена, продление, учёт доступного остатка и защита резервов от расхода.

### Modified Capabilities

(нет: в `openspec/specs/` спецификаций пока нет; влияние на `issue`/`transfer` описано в новой спецификации)

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, новый `warehouse/reservations.py`, `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов), README (список модулей).
- Тесты: новые файлы тестов; существующие не меняются.
- Формат журнала не меняется, новые виды событий видны внешней выгрузке.
