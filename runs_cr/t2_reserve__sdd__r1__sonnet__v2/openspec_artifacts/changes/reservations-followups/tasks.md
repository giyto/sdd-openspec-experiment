## 1. Константы и модели

- [x] 1.1 В `warehouse/reservations.py` изменить `DEFAULT_RESERVATION_TTL` на 20 минут и добавить `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`
- [x] 1.2 В `warehouse/models.py` добавить frozen-датакласс `Availability(warehouse, sku, on_hand, reserved, available)`
- [x] 1.3 Экспортировать `Availability` и `MAX_RESERVATION_LIFETIME` из `warehouse/__init__.py` (импорт и `__all__`)

## 2. Хранилище

- [x] 2.1 В `ReservationRecord` добавить `expire_logged: bool = False`
- [x] 2.2 В `InMemoryStore` добавить перебор резервов `(order_id, record)` и расчёт `reserved_qty` с возможностью исключить запись заказа

## 3. Создание, замена, продление

- [x] 3.1 `reserve`: `ttl` больше `MAX_RESERVATION_LIFETIME` → `ValidationError` до любых изменений
- [x] 3.2 `reserve`: `CONFIRMED` → `DuplicateReservationError`; `ACTIVE` → замена с проверкой наличия без заменяемого резерва; события `RESERVE_CANCEL`, затем `RESERVE` по строкам; новый резерв со своими `created_at` и сроком
- [x] 3.3 `extend`: новый срок `min(now + ttl, created_at + MAX_RESERVATION_LIFETIME)`; без изменений и события, если не позже текущего `expires_at`

## 4. Возврат

- [x] 4.1 `cancel` подтверждённого: вернуть остаток по строкам на те же склады, статус `CANCELLED`, события `RECEIVE` (`ref` = заказ) по строкам, затем `RESERVE_CANCEL`; повторная отмена без изменений

## 5. Новые запросы и sweep

- [x] 5.1 `Inventory.reservations(status=None)` с сортировкой `(created_at, order_id)`
- [x] 5.2 `Inventory.availability(warehouse=None)`: позиции с остатком или активным резервом, порядок и фильтр как у `stock_levels`
- [x] 5.3 `Inventory.sweep_expired()`: `RESERVE_EXPIRE` один раз на резерв, порядок `(expires_at, order_id)`, без изменения статусов и остатков

## 6. Тесты и проверка

- [x] 6.1 Новые тесты (в новых файлах, существующие не менять) по сценариям спецификации: замена, возврат, TTL и предел (граница ровно 2 часа и +1 секунда), `extend` на пределе, `reservations`, `availability`, `sweep_expired` (повтор, заново зарезервированный заказ, порядок)
- [x] 6.2 Запустить весь набор тестов; перечислить в отчёте падающие существующие тесты, кодирующие отменённые правила (не править их)
- [x] 6.3 Убедиться, что `warehouse/cli.py`, `warehouse/reports.py` и формат строки журнала не изменены
