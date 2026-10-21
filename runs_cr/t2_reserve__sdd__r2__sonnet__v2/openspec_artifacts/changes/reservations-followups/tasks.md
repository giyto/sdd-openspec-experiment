## 1. Модель и правила

- [x] 1.1 Добавить `Availability` в `warehouse/models.py` и экспорт в `warehouse/__init__.py`
- [x] 1.2 В `warehouse/reservations.py`: `DEFAULT_RESERVATION_TTL` = 20 минут, `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`, проверка предела для `reserve`; экспорт константы
- [x] 1.3 Добавить в `ReservationRecord` (`warehouse/storage.py`) признак «истечение зафиксировано» (по умолчанию ложь)

## 2. Изменение операций

- [x] 2.1 `reserve`: замена активного резерва (атомарно, товар заменяемого свободен, `RESERVE_CANCEL` затем `RESERVE`); подтверждённый — `DuplicateReservationError`
- [x] 2.2 `cancel`: возврат подтверждённого (`RECEIVE` по строкам с `ref`, затем `RESERVE_CANCEL`, `CANCELLED`); идемпотентность повтора
- [x] 2.3 `extend`: ограничение срока `created_at + MAX_RESERVATION_LIFETIME` без ошибки и без переполнения

## 3. Новые методы

- [x] 3.1 `reservations(status=None)` с сортировкой `(created_at, order_id)`
- [x] 3.2 `availability(warehouse=None)` по правилам `stock_levels`
- [x] 3.3 `sweep_expired()` с `RESERVE_EXPIRE`, единоразовой фиксацией на резерв и порядком `(expires_at, order_id)`

## 4. Тесты

- [x] 4.1 Новые тесты в отдельном файле по сценариям спеки (замена, неудачная замена, возврат, предел, повторная фиксация после нового резерва)
- [x] 4.2 Запустить весь набор; перечислить существующие тесты, упавшие из-за отменённых договорённостей, не изменяя их, и сообщить об этом
