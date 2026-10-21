## Why

Резервы работают месяц, и поддержка со складом собрали список проблем (WH-231): покупатели меняют корзину и оформляют возвраты, а поддержке не видно, какие резервы истекли. Часть прежних правил меняем, часть добавляем.

## What Changes

- **BREAKING** Повторный `reserve` на заказ с активным резервом больше не ошибка, а замена: новый резерв целиком заменяет активный (свой `created_at` и срок от момента замены). Товар заменяемого резерва при проверке наличия считается свободным. Журнал: `RESERVE_CANCEL` по старому, затем `RESERVE` по строкам нового. Подтверждённый заказ заменить по-прежнему нельзя (`DuplicateReservationError`).
- **BREAKING** `cancel` подтверждённого заказа — возврат: товар по всем строкам возвращается на те же склады, статус `CANCELLED`. Журнал: `RECEIVE` по каждой строке (`ref` = номер заказа), затем `RESERVE_CANCEL`. Раньше было `ReservationStateError`.
- **BREAKING** `DEFAULT_RESERVATION_TTL` — 20 минут вместо 15.
- Новая константа `MAX_RESERVATION_LIFETIME = timedelta(hours=2)` в `warehouse/reservations.py` (по уточнению Ольги Смирновой от 10.11 — два часа, а не час из текста задачи). `expires_at` не позже `created_at + MAX_RESERVATION_LIFETIME`; `reserve` с большим `ttl` — `ValidationError`; `extend` сверх предела ставит срок ровно на предел без ошибки.
- Новая модель `Availability(warehouse, sku, on_hand, reserved, available)` в `warehouse/models.py` (frozen dataclass).
- Новые методы `Inventory`: `reservations(status=None) -> list[Reservation]`, `availability(warehouse=None) -> list[Availability]`, `sweep_expired() -> list[str]` (пишет `RESERVE_EXPIRE` с полями `order`, `expires` один раз на каждый резерв).

Вне рамок: `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты, новые зависимости, фоновые процессы (`sweep_expired` вызывает внешний планировщик).

## Capabilities

### New Capabilities

Нет.

### Modified Capabilities

- `stock-reservations`: меняются создание резерва (TTL, предел), повторный резерв (замена), отмена (возврат), продление (предел), события журнала; добавляются обзор резервов, доступность по позициям и учёт истёкших резервов.

## Impact

- Код: `warehouse/models.py`, `warehouse/reservations.py`, `warehouse/inventory.py`.
- Существующие тесты, закрепляющие старое поведение (15 минут, `DuplicateReservationError` для активного резерва, `ReservationStateError` при отмене подтверждённого), перестанут совпадать с новым поведением; по условию задачи их не меняем, расхождение фиксируется в отчёте при реализации.
- Формат журнала не меняется; появляется новый тип события `RESERVE_EXPIRE`, а возврат пишет `RECEIVE` и `RESERVE_CANCEL`.
