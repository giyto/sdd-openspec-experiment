## Why

Резервы работают месяц, и поддержка со складом собрали список проблем (WH-231): покупатели меняют корзину и оформляют возвраты, а поддержке не видно, какие резервы истекли. Часть прежних договорённостей меняется, часть добавляется.

## What Changes

- **BREAKING** Повторный `reserve` на заказ с активным резервом больше не ошибка, а замена: старый резерв отменяется, создаётся новый целиком (свои `created_at` и срок от момента замены). Товар заменяемого резерва при проверке наличия считается свободным. Журнал: `RESERVE_CANCEL` по старому, затем `RESERVE` по строкам нового. Подтверждённый заказ по-прежнему заменить нельзя (`DuplicateReservationError`).
- **BREAKING** `cancel` подтверждённого заказа — возврат: товар по всем строкам возвращается на те же склады, статус `CANCELLED`. Журнал: `RECEIVE` по каждой строке (`ref` = номер заказа), затем `RESERVE_CANCEL`.
- **BREAKING** TTL по умолчанию 20 минут вместо 15 (`DEFAULT_RESERVATION_TTL`).
- Предельный срок резерва: `expires_at <= created_at + MAX_RESERVATION_LIFETIME`. Значение — **2 часа** (уточнение Ольги Смирновой от 10.11 отменяет «один час» из описания). `reserve` с `ttl` больше предела — `ValidationError`; `extend` сверх предела не ошибка, срок ставится ровно на предел.
- Новая модель `Availability` и методы `Inventory.reservations()`, `Inventory.availability()`, `Inventory.sweep_expired()`.
- `sweep_expired()` для дашборда поддержки пишет по каждому истёкшему резерву одно событие `RESERVE_EXPIRE` (`order`, `expires`) и возвращает `order_id`; статусы и остатки не меняет. Вызывает внешний планировщик, фоновых процессов в сервисе нет.
- Не меняется: `cli.py`, `reports.py`, существующие тесты, зависимости; остальные правила резервов и старый API.

## Capabilities

### New Capabilities

### Modified Capabilities
- `order-reservations`: замена активного резерва, возврат подтверждённого заказа, TTL по умолчанию, предельный срок, запросы `reservations`/`availability`, событие `RESERVE_EXPIRE` и `sweep_expired`.

## Impact

- Код: `warehouse/inventory.py`, `warehouse/reservations.py` (константы), `warehouse/models.py` (`Availability`), `warehouse/storage.py` (учёт уже записанных истечений), `warehouse/__init__.py` (экспорт), новые тесты.
- Существующие тесты в `tests/test_reservations.py`, фиксирующие прежнее поведение (TTL 15 минут, `DuplicateReservationError` для активного резерва, `ReservationStateError` при отмене подтверждённого), станут красными — см. design.md. Их не правим, согласно рамкам тикета.
- `movement_summary` увидит `RECEIVE` от возврата как обычный приход; `cli.py` и `reports.py` не меняются.
