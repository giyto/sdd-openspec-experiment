## 1. Модели и константы

- [x] 1.1 Добавить `Availability` (frozen dataclass: `warehouse`, `sku`, `on_hand`, `reserved`, `available`) в `warehouse/models.py` и экспорт по образцу `StockLevel`; проверить импортом `from warehouse.models import Availability`
- [x] 1.2 В `warehouse/reservations.py` поставить `DEFAULT_RESERVATION_TTL = 20 минут`, добавить `MAX_RESERVATION_LIFETIME = timedelta(hours=2)` и флаг однократной записи истечения в `ReservationRecord`; проверить тестом значений констант

## 2. Создание, замена и продление

- [x] 2.1 В `reserve` отклонять `ttl > MAX_RESERVATION_LIFETIME` через `ValidationError` до изменения состояния; проверить тестами границы (равно пределу — успех, больше — ошибка, журнал не изменён)
- [x] 2.2 Реализовать замену активного резерва в `reserve` (свободный товар заменяемого резерва, новые `created_at`/`expires_at`, `RESERVE_CANCEL` затем `RESERVE`, `DuplicateReservationError` для подтверждённого, атомарность при ошибке); проверить сценариями замены и неудачной замены
- [x] 2.3 В `extend` ограничить срок значением `created_at + MAX_RESERVATION_LIFETIME` без ошибки и без события, если срок не растёт; проверить сценариями «сверх предела» и «уже на пределе»

## 3. Возврат

- [x] 3.1 Реализовать `cancel` подтверждённого резерва: `RECEIVE` с `ref=order_id` по строкам, затем `RESERVE_CANCEL`, статус `CANCELLED`, идемпотентность повторного вызова; проверить остатки и порядок событий в тестах

## 4. Новые запросы и фиксация истечения

- [x] 4.1 Реализовать `Inventory.reservations(status=None)` с порядком `created_at`, `order_id`; проверить тестами порядка и фильтра по текущему статусу
- [x] 4.2 Реализовать `Inventory.availability(warehouse=None)` с составом позиций, порядком и фильтром как у `stock_levels`; проверить сценариями (резерв без остатка, истёкший резерв, фильтр) и совпадением значений с `on_hand`/`reserved`/`available`
- [x] 4.3 Реализовать `Inventory.sweep_expired()` (однократность на резерв, порядок `expires_at`, `order_id`, повторный резерв того же заказа, статусы и остатки не меняются); проверить сценариями из спецификации

## 5. Проверка

- [x] 5.1 Прогнать весь набор тестов; убедиться, что `cli.py`, `reports.py` и существующие тесты не изменены (`git diff --stat`), зависимости не добавлены; зафиксировать устаревшие поведения старых тестов, если есть
- [x] 5.2 Сверить публичный API реализации с proposal и specs: `Availability`, `MAX_RESERVATION_LIFETIME`, `reservations(status=None)`, `availability(warehouse=None)`, `sweep_expired()` — имена, параметры, типы возврата дословно как в задаче
