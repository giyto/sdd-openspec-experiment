## Why

Сейчас товар списывается только при отгрузке: пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать повторно, и складу приходится извиняться перед клиентом (WH-214). Нужно резервировать товар под заказ в момент оформления; неоплаченный резерв должен сам перестать действовать по истечении TTL. Фоновых задач нет, поэтому истечение определяется лениво — по часам сервиса в момент обращения.

## What Changes

- В `Inventory` добавляются резервы: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved`.
- В `warehouse/models.py`: `ReservationStatus` (`ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`), `ReservationLine(warehouse, sku, qty)`, `Reservation(order_id, lines, created_at, expires_at, status)` — неизменяемые датаклассы-снимки.
- В `warehouse/errors.py`: `ReservationError(WarehouseError)` с атрибутом `order_id` и наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`.
- Новый модуль `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (по обсуждению в задаче: 15 минут, а не 30 из исходного текста).
- `issue` (и `transfer` как расход со склада-источника) не может забрать товар из чужих активных резервов: учитывается только доступное; `available` никогда не отрицателен (минимум 0). Повторный `reserve` на заказ с действующим или подтверждённым резервом — `DuplicateReservationError`, с истёкшим или отменённым — заменяет его. `extend` ставит срок `now + ttl` и никогда его не сокращает.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; при `confirm` пишется обычный `ISSUE` на каждую строку.
- Не меняется: конструктор и прочий API `Inventory`, `on_hand`/`stock_levels` (физический остаток), формат журнала, `cli.py`, `reports.py`, существующие тесты, зависимости.

## Capabilities

### New Capabilities
- `inventory-reservations`: резервирование товара под заказы с TTL, подтверждение, отмена, продление, учёт доступного остатка, события журнала.

### Modified Capabilities
<!-- Основных спецификаций в openspec/specs/ пока нет; ограничение расхода резервами описано в новой capability. -->

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, `warehouse/reservations.py` (новый), `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов); тесты добавляются отдельным файлом.
- API: только добавления; поведение кода без резервов не меняется.
- Зависимости и формат журнала: без изменений.
