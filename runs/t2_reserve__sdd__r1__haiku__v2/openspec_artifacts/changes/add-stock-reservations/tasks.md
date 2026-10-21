## 1. Модели, ошибки и константы

- [x] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py` (frozen, поля по ТЗ) и проверить импорт `python -c "from warehouse.models import Reservation, ReservationLine, ReservationStatus"`
- [x] 1.2 Добавить `ReservationError` и четыре наследника в `warehouse/errors.py`, у всех атрибут `order_id`; проверить, что все наследуются от `WarehouseError`, тестом в новом файле тестов
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)`, функцией `effective_status(reservation, now)` и проверкой TTL (`ValidationError` для не-`timedelta` и неположительных значений); покрыть тестами граница `now == expires_at` → `EXPIRED`

## 2. Хранилище резервов

- [x] 2.1 Добавить в `InMemoryStore` хранение резервов по `order_id` (`get_reservation`, `put_reservation`, `list_reservations`) и проверить тестом, что записи возвращаются в исходном виде
- [x] 2.2 Проверить, что существующие тесты хранилища и остатков проходят без изменений: `python -m pytest -q`

## 3. Сервис: резервы и расчёты

- [x] 3.1 Реализовать `reserved` и `available` (сумма строк активных резервов по эффективному статусу; `available` не ниже 0; `UnknownSkuError` для незарегистрированного SKU), проверить тестами сценарии из спецификации «Reserved and available quantities»
- [x] 3.2 Реализовать `reserve`: валидация аргументов, дубликат (только `ACTIVE`/`CONFIRMED`), проверка по сумме строк одной позиции, запись резерва с `created_at`/`expires_at`, события `RESERVE` по строкам; проверить сценарии «Reserve holds stock», «Duplicate reservations», «Reserve input validation»
- [x] 3.3 Реализовать `get_reservation` (снимок с эффективным статусом, `ReservationNotFoundError`); проверить, что снимок не меняется после последующих операций

## 4. Сервис: жизненный цикл

- [x] 4.1 Реализовать `confirm`: порядок проверок из design.md (решение 4), проверка физического остатка по сумме строк, события `ISSUE` с `ref` и `RESERVE_CONFIRM`; проверить сценарии «Confirm turns a reservation into a shipment», включая нулевой `available` и отказ при нехватке без изменений
- [x] 4.2 Реализовать `cancel` с идемпотентностью (повтор и `EXPIRED` — без событий), `RESERVE_CANCEL` только при переходе из `ACTIVE`; проверить сценарии «Cancel releases a reservation»
- [x] 4.3 Реализовать `extend`: валидация `ttl`, `now + ttl`, отсутствие сокращения срока (без события), `RESERVE_EXTEND` с `order` и `expires`; проверить сценарии «Extend an active reservation»

## 5. Выход со склада и совместимость

- [x] 5.1 Добавить проверку `available` в `issue` (ошибка `InsufficientStockError` с `available` в поле) и проверить сценарии «Issue beyond available» и «Issue without reservations»
- [x] 5.2 Добавить ту же проверку источника в `transfer`; проверить тестом, что без резервов перемещение работает как раньше и что резерв не даёт переместить зарезервированный товар
- [x] 5.3 Проверить, что `adjust`, `receive`, `on_hand`, `stock_levels` не изменились: существующие тесты проходят без правок, `git diff` по `tests/` пуст

## 6. Журнал, документация и итоговая проверка

- [x] 6.1 Проверить, что все новые события проходят `events.parse_line(event.format())` (round-trip) и что поле `expires` записывается через `format_timestamp`
- [x] 6.2 Обновить дерево модулей в `README.md` (добавить `reservations.py`) — единственное изменение документации
- [x] 6.3 Прогнать `python -m pytest -q` целиком и добавить тесты на истечение (переход через `expires_at` в каждой операции, событие не пишется); всё зелёное
- [x] 6.4 Проверить, что `warehouse/cli.py` и `warehouse/reports.py` не изменены (`git diff --stat`)
