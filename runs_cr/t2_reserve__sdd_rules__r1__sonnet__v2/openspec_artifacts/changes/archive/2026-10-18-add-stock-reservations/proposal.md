## Why

Сейчас товар списывается только при отгрузке: пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз (WH-214). Нужно резервировать товар под заказ в момент оформления, а неоплаченный резерв должен сам перестать действовать через TTL. Фоновых задач нет, поэтому истечение определяется по часам сервиса в момент обращения.

## What Changes

- В `Inventory` добавляются резервы: методы `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved` (сигнатуры — дословно из задачи, см. ниже).
- `warehouse/models.py`: `ReservationStatus(str, Enum)` со значениями `ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`; `@dataclass(frozen=True) ReservationLine(warehouse: str, sku: str, qty: int)`; `@dataclass(frozen=True) Reservation(order_id, lines: tuple[ReservationLine, ...], created_at, expires_at, status)` — снимок со статусом на текущий момент.
- `warehouse/errors.py`: `ReservationError(WarehouseError)` и наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у всех атрибут `order_id`.
- `warehouse/reservations.py`: `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (по обсуждению; в исходном тексте было 30 минут, заменено по просьбе маркетинга).
- Публичные сигнатуры `Inventory`:
  - `reserve(self, order_id: str, lines: Iterable[tuple[str, str, int] | ReservationLine], ttl: timedelta | None = None) -> Reservation`
  - `confirm(self, order_id: str) -> Reservation`
  - `cancel(self, order_id: str) -> Reservation`
  - `extend(self, order_id: str, ttl: timedelta) -> Reservation`
  - `get_reservation(self, order_id: str) -> Reservation`
  - `available(self, warehouse: str, sku: str) -> int`
  - `reserved(self, warehouse: str, sku: str) -> int`
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; при `confirm` — обычные `ISSUE` с `ref` = номер заказа.
- Поведение `issue` меняется для кода с резервами: нельзя забрать товар из чужих активных резервов. Без резервов поведение прежнее. По docstring `transfer` («для источника это обычный расход, проверки те же, что у `issue`») то же ограничение действует и на `transfer` (допущение, см. design).
- Не меняются: конструктор `Inventory`, `receive/adjust/on_hand/stock_levels`, формат строки журнала, `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты; новых зависимостей нет.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказы с TTL, подтверждение/отмена/продление, доступный остаток и влияние резервов на расход.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций; ограничение `issue` описано в новой capability)

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, новый `warehouse/reservations.py`, `warehouse/inventory.py`, `warehouse/storage.py` и экспорты в `warehouse/__init__.py`.
- Журнал: новые типы событий в существующем формате; внешняя выгрузка получит новые `kind`.
- Тесты: добавляются новые, существующие не меняются.
