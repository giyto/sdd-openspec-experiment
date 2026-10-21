## Why

Резервы работают месяц (WH-231). Покупатели меняют корзину и оформляют возвраты, а поддержка не видит, какие резервы истекли. Часть прежних договорённостей меняем, часть добавляем.

## What Changes

- **BREAKING** Повторный `reserve` на заказ с активным резервом больше не ошибка, а замена: старый резерв отменяется (`RESERVE_CANCEL`), новый создаётся как новый резерв целиком (свой `created_at` и срок от момента замены, `RESERVE` по новым строкам). Товар заменяемого резерва при проверке наличия свободен. Для подтверждённого заказа по-прежнему `DuplicateReservationError`.
- **BREAKING** `cancel` подтверждённого заказа — возврат: `RECEIVE` по каждой строке (`ref` = номер заказа) на те же склады, затем `RESERVE_CANCEL`, статус `CANCELLED`. Раньше — `ReservationStateError`.
- **BREAKING** `DEFAULT_RESERVATION_TTL` = 20 минут (было 15).
- Предельный срок резерва: `MAX_RESERVATION_LIFETIME = timedelta(hours=2)` (по обсуждению в задаче; в тексте тикета был 1 час, он заменён). `reserve` с `ttl` больше предела — `ValidationError`; `extend` сверх предела ставит срок ровно `created_at + MAX_RESERVATION_LIFETIME`.
- Новые методы `Inventory`: `reservations(status=None)`, `availability(warehouse=None)`, `sweep_expired()`; новый тип `Availability` (`warehouse/models.py`); событие журнала `RESERVE_EXPIRE`.
- `cli.py`, `reports.py`, существующие тесты и зависимости не трогаем.

## Capabilities

### New Capabilities

(нет)

### Modified Capabilities

- `order-reservations`: меняются создание, валидация, повторный резерв, отмена, продление, истечение и журнал; добавляются запросы списка резервов и остатков и фиксация истёкших резервов.

## Impact

- Код: `warehouse/inventory.py`, `warehouse/reservations.py`, `warehouse/models.py`, `warehouse/storage.py` (признак «о резерве уже писали»), `warehouse/__init__.py` (экспорт `Availability`, `MAX_RESERVATION_LIFETIME`).
- Существующие тесты в `tests/test_reservations.py` фиксируют отменяемое поведение (15 минут, `DuplicateReservationError` на активный, ошибка при отмене подтверждённого, отсутствие записей об истечении) и после изменения будут падать. Тикет запрещает их менять; см. «Risks / Open Questions» в design.md.
- Внешняя выгрузка журнала получает тип `RESERVE_EXPIRE`; формат строки не меняется.
