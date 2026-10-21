## Why

Резервы под заказы работают месяц, и поддержка со складом собрали список проблем: покупатели меняют корзину, оформляют возвраты, а поддержке не видно, какие резервы истекли. Часть прежних договорённостей меняется, часть дополняется (WH-231).

## What Changes

- **BREAKING** Повторный `reserve` на заказ с активным резервом больше не ошибка, а замена: новый резерв (со своими `created_at` и сроком от момента замены) заменяет активный; товар заменяемого резерва при проверке наличия считается свободным. В журнале: `RESERVE_CANCEL` по старому, затем `RESERVE` по строкам нового. Подтверждённый заказ по-прежнему заменить нельзя (`DuplicateReservationError`).
- **BREAKING** `cancel` подтверждённого заказа — возврат: товар по всем строкам возвращается на те же склады, статус `CANCELLED`. В журнале: `RECEIVE` по каждой строке с `ref` = номер заказа, затем `RESERVE_CANCEL`. Раньше было `ReservationStateError`.
- `DEFAULT_RESERVATION_TTL` — 20 минут вместо 15.
- Предельный срок: `MAX_RESERVATION_LIFETIME = timedelta(hours=2)` (значение уточнено в обсуждении задачи: два часа, а не один из текста). `expires_at <= created_at + MAX_RESERVATION_LIFETIME`. `reserve` с `ttl` больше предела — `ValidationError`; `extend` сверх предела не ошибка, срок ставится ровно на предел.
- Новая модель `Availability` (`warehouse`, `sku`, `on_hand`, `reserved`, `available`) в `warehouse/models.py`.
- Новые методы `Inventory`: `reservations(status=None)`, `availability(warehouse=None)`, `sweep_expired()`. `sweep_expired` пишет по каждому истёкшему резерву один раз событие `RESERVE_EXPIRE` (`order`, `expires`) и возвращает `order_id`; статусы и остатки не меняет. Вызывает его внешний планировщик, фоновых процессов в сервисе нет.
- Вне рамок: `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты, новые зависимости.

## Capabilities

### New Capabilities

### Modified Capabilities
- `stock-reservations`: TTL по умолчанию и предельный срок (создание, валидация, продление); замена активного резерва и повторный `reserve`; возврат при `cancel` подтверждённого; события журнала (замена, возврат, `RESERVE_EXPIRE`); запись истечения только через `sweep_expired`; новые запросы `reservations`, `availability`, `sweep_expired`.

## Impact

- Код: `warehouse/inventory.py`, `warehouse/reservations.py` (константы, флаг «об истечении записано» в записи резерва), `warehouse/models.py` (`Availability`), возможно экспорт в `warehouse/__init__.py`.
- API: сигнатуры из задачи переносятся дословно; старый API без изменений сигнатур, но меняется поведение `reserve`, `cancel`, `extend` (см. BREAKING).
- Потребители журнала увидят новый тип события `RESERVE_EXPIRE` и `RECEIVE` с `ref` заказа при возвратах.
- Зависимости не добавляются.
