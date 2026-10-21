## 1. Модели и ошибки

- [x] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py`; проверить тестом, что датаклассы неизменяемы, а `lines` — кортеж
- [x] 1.2 Добавить `ReservationError` и наследники (`NotFound`, `Expired`, `State`, `Duplicate`) с атрибутом `order_id` в `warehouse/errors.py`; проверить, что все наследуются от `WarehouseError`
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)`, проверкой `ttl` и нормализацией строк; проверить юнит-тестами (ttl ≤ 0, не timedelta, кортеж и `ReservationLine`, некорректная строка)
- [x] 1.4 Добавить хранение резервов в `InMemoryStore` и экспорт новых имён в `warehouse/__init__.py`; проверить, что существующие тесты проходят

## 2. Запросы и ограничение расхода

- [x] 2.1 Реализовать `reserved`, `available`, `get_reservation` с ленивым определением `EXPIRED` (граница `now == expires_at`, окончательность `CONFIRMED`/`CANCELLED`); проверить тестами с `ManualClock`, включая `adjust` ниже резерва (available = 0)
- [x] 2.2 Ограничить `issue` и `transfer` значением `available`; проверить тестами: расход из чужого резерва отклоняется, после истечения разрешён, поведение без резервов не изменилось (прогон существующих тестов)

## 3. Операции с резервами

- [x] 3.1 Реализовать `reserve`: валидации, проверка по сумме дублирующихся позиций, `DuplicateReservationError`, замена истёкшего/отменённого, события `RESERVE`; проверить тестами атомарности (ошибка не меняет состояние и журнал)
- [x] 3.2 Реализовать `confirm`: проверка физического остатка по сумме, события `ISSUE` (`ref` = заказ) и `RESERVE_CONFIRM`, ошибки статусов; проверить тестами, включая available = 0 и урезанный `adjust` (ничего не списано, резерв активен)
- [x] 3.3 Реализовать `cancel` (идемпотентность, истёкший остаётся `EXPIRED`, подтверждённый → `ReservationStateError`) и `extend` (от `now`, без сокращения, без события при отсутствии изменений); проверить тестами и содержимым журнала
- [x] 3.4 Проверить `ReservationNotFoundError` для `confirm/cancel/extend/get_reservation`; по тесту на каждый метод

## 4. Итоговая проверка

- [x] 4.1 Прогнать `python -m pytest -q`: существующие тесты не изменены и проходят; сверить строки журнала новых событий с форматом в `events.py`
- [x] 4.2 Выполнить `openspec validate add-order-reservations --strict` без ошибок
