## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать повторно (WH-214). Нужно удерживать товар под заказ с момента оформления, а неоплаченный резерв должен сам перестать действовать по TTL (фоновых задач нет, истечение определяется по часам сервиса в момент обращения).

## What Changes

- Новые методы `Inventory`: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved`.
- Новые типы: `ReservationStatus`, `ReservationLine`, `Reservation` (`warehouse/models.py`); исключения `ReservationError` и наследники (`warehouse/errors.py`); `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (`warehouse/reservations.py`).
- `issue` и `transfer` (расход со склада-источника) не могут забрать товар из чужих активных резервов: ограничены `available`.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` пишет обычные `ISSUE`.
- Не меняется: конструктор и сигнатуры старого API, формат строки журнала, `on_hand`/`stock_levels` (физический остаток), `cli.py`, `reports.py`, существующие тесты, зависимости.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказы с TTL, подтверждение/отмена/продление, расчёт доступного остатка, влияние резервов на расход, события журнала.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций; влияние на `issue`/`transfer` описано в новой спецификации)

## Impact

- Код: `warehouse/models.py`, `errors.py`, `inventory.py`, `storage.py` (хранение резервов), новый `warehouse/reservations.py`, экспорты в `warehouse/__init__.py`; новые тесты.
- Журнал: новые типы событий для внешней выгрузки (существующие строки не меняются).
- Поведение `issue`/`transfer` меняется только при наличии активных резервов.

## Допущения

Зафиксированы в `design.md` (раздел «Допущения»): границы истечения, повторный резерв на `order_id`, отмена истёкшего, отсчёт продления от текущего времени, отрицательный `available`, порядок проверок.
