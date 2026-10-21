## Why

Сейчас товар списывается только при отгрузке. Пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз, и склад вынужден извиняться перед клиентом. Нужно резервировать товар под заказ в момент оформления, а неоплаченный резерв должен сам перестать действовать через TTL. Фоновых задач нет, поэтому истечение определяется лениво, по часам сервиса в момент обращения.

## What Changes

- В `Inventory` добавляются методы `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved` (сигнатуры дословно как в задаче WH-214).
- В `warehouse/models.py`: `ReservationStatus(str, Enum)` со значениями `ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`; `ReservationLine(warehouse, sku, qty)`; `Reservation(order_id, lines, created_at, expires_at, status)` — frozen-датаклассы.
- В `warehouse/errors.py`: `ReservationError(WarehouseError)` и наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у всех атрибут `order_id`.
- Новый модуль `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (по обновлению от 13.10: 15 минут, а не 30).
- Новые типы событий журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`. Само истечение в журнал не пишется.
- `issue` (и `transfer` как «обычный расход» с теми же проверками) не может забрать товар из чужих активных резервов: ограничен `available`.
- Физический остаток резервом не меняется; `on_hand` и `stock_levels` по-прежнему показывают физический остаток.
- Не меняются: конструктор `Inventory`, `receive/adjust/on_hand/stock_levels`, `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты; новых зависимостей нет. Формат строки журнала не меняется.

Допущения (там, где задача молчит):
- `transfer` тоже не берёт зарезервированное: его docstring говорит, что для источника это обычный расход с проверками `issue`.
- Порядок проверок в `reserve`: входные данные (`ValidationError`, `InvalidQuantityError`, `UnknownSkuError`) → дубликат → достаточность остатка.
- Порядок проверок в `extend`: `ttl` (`ValidationError`) → наличие резерва → статус.
- Поле `expires` в журнале пишется форматом времени журнала (секундная точность, `Z`); в снимке `Reservation` время хранится без округления.
- Резерв считается истёкшим при `now >= expires_at`.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказы с TTL, подтверждение, отмена, продление, расчёт `available`/`reserved`, защита резервов от `issue`/`transfer`, события журнала.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций; поведение `issue`/`transfer` для кода без резервов не меняется и описано в новой capability)

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов), новый `warehouse/reservations.py`; новые тесты.
- Публичный API `Inventory` расширяется, обратная совместимость сохраняется.
- Журнал получает новые типы событий; отчёты их игнорируют.
- Зависимости не добавляются.
