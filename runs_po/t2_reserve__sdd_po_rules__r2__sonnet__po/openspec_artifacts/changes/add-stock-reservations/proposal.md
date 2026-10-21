## Why

Сейчас товар списывается только при отгрузке: пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз, и склад вынужден извиняться перед клиентом (WH-214). Нужно удерживать товар под заказ с момента оформления, а неоплаченные резервы должны сами переставать действовать по TTL — без фоновых задач, по часам сервиса в момент обращения.

## What Changes

- В `warehouse/models.py` добавляются `ReservationStatus` (`ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`), `ReservationLine(warehouse, sku, qty)` и `Reservation(order_id, lines, created_at, expires_at, status)` — неизменяемые датаклассы, как задано в задаче.
- В `warehouse/errors.py` добавляются `ReservationError(WarehouseError)` и её наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у всех атрибут `order_id`.
- Новый модуль `warehouse/reservations.py` с константой `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (по обновлению от 13.10: 15 минут, а не 30).
- В `Inventory` добавляются методы `reserve(order_id, lines, ttl=None)`, `confirm(order_id)`, `cancel(order_id)`, `extend(order_id, ttl)`, `get_reservation(order_id)`, `available(warehouse, sku)`, `reserved(warehouse, sku)`.
- Истечение резерва определяется лениво, по часам сервиса в момент обращения; в журнал не пишется. `CONFIRMED` и `CANCELLED` окончательные и истечением не меняются.
- `issue` (и `transfer`, у которого для источника «проверки те же, что у `issue`») не могут забрать товар из чужих активных резервов.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` дополнительно пишет обычные `ISSUE` с `ref` = номер заказа.
- Старый API (`Inventory(...)`, `receive/issue/transfer/adjust/on_hand/stock_levels`) для кода без резервов работает как раньше. Не меняются `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты; зависимости не добавляются.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказы с TTL — создание, подтверждение, отмена, продление, запросы `available`/`reserved`, учёт резервов при расходе, события журнала.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций. Влияние на `issue`/`transfer` описано в новой спецификации как требование при наличии активных резервов; поведение без резервов не меняется.)

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, `warehouse/inventory.py`, новый `warehouse/reservations.py`; возможно `warehouse/storage.py` (хранение резервов) и `warehouse/__init__.py` (экспорт новых имён).
- Журнал: четыре новых типа событий; формат строки не меняется. Отчёт `movement_summary` игнорирует незнакомые типы событий, но `RESERVE*` с полем `sku` добавят в сводку нулевую строку для SKU, по которому были только резервы (reports.py не трогаем — принято).
- Зависимости: нет. Публичный API старых методов не ломается.

## Допущения (решения без ответа автора)

- Резерв истёк, когда `now >= expires_at` (в момент `expires_at` резерв уже не действует).
- `extend` отсчитывает срок от момента запроса: `новый срок = now + ttl`. Срок никогда не сокращается: если `now + ttl` не позже текущего `expires_at`, резерв возвращается как есть, `RESERVE_EXTEND` не пишется.
- Повторный `reserve` с тем же `order_id` — `DuplicateReservationError`, только если прежний резерв действующий (`ACTIVE`) или подтверждённый (`CONFIRMED`). Если прежний истёк или отменён, новый резерв разрешён и полностью заменяет старый: старая запись удаляется из хранилища и из `get_reservation`.
- `cancel` истёкшего резерва — не ошибка и не действие: статус остаётся `EXPIRED`, журнал не пишется.
- `available` не бывает отрицательным: если инвентаризация (`adjust`) опустила физический остаток ниже резервов, `available` = 0.
