## 1. Модели, ошибки и константы

- [x] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py` (frozen dataclass) и проверить импорт модуля и отсутствие изменений в существующих моделях
- [x] 1.2 Добавить `ReservationError` (наследник `WarehouseError`) и наследников `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError` с атрибутом `order_id` в `warehouse/errors.py`; проверить, что все они ловятся `except WarehouseError`
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` и внутренней записью резерва; проверить значение константы тестом

## 2. Хранилище

- [x] 2.1 Добавить в `InMemoryStore` (`warehouse/storage.py`) хранение записей резервов по `order_id`: получить, сохранить, перечислить активные по позиции; проверить unit-тестом хранилища

## 3. Сервис: резервирование и учёт

- [x] 3.1 Реализовать расчёт статуса с учётом времени (`ACTIVE` → `EXPIRED` при `now >= expires_at`) и функции `reserved`/`available` в `warehouse/inventory.py`; проверить тестами на границе истечения и на отсутствие изменений `on_hand`
- [x] 3.2 Реализовать `reserve` (валидация TTL и строк, неизвестный SKU, `DuplicateReservationError` с заменой истёкших/отменённых, проверка по сумме строк позиции, события `RESERVE`); проверить тестами сценарии `specs/reservations/spec.md` для резервирования и повтора
- [x] 3.3 Реализовать `get_reservation` (снимок с вычисленным статусом и строками в исходном порядке) и `ReservationNotFoundError`; проверить тестом неизменяемости снимка

## 4. Сервис: подтверждение, отмена, продление

- [x] 4.1 Реализовать `confirm` (проверка физического остатка по сумме строк, атомарное списание, `ISSUE` с `ref`, `RESERVE_CONFIRM`, ошибки по статусу); проверить сценарии подтверждения из spec, включая «ничего не меняется при нехватке»
- [x] 4.2 Реализовать `cancel` (идемпотентность, `RESERVE_CANCEL`, ошибка для `CONFIRMED`); проверить, что повторная отмена и отмена истёкшего не пишут журнал
- [x] 4.3 Реализовать `extend` (только продление, без сокращения, `RESERVE_EXTEND`, проверка TTL, ошибки по статусу); проверить сценарии продления из spec

## 5. Расход и обратная совместимость

- [x] 5.1 Перевести проверку `issue` и источника `transfer` на `available`; проверить новыми тестами, что расход не забирает активный резерв, и что без резервов поведение прежнее
- [x] 5.2 Запустить существующий набор тестов `python -m pytest -q` и убедиться, что все существующие тесты проходят без изменений файлов тестов

## 6. Проверка целиком

- [x] 6.1 Проверить сценарий на нескольких складах и с дублирующимися строками одной позиции (сумма при `reserve` и `confirm`), а также формат событий журнала по строкам `format()` из `warehouse/events.py`
- [x] 6.2 Прогнать `openspec validate add-inventory-reservations --strict` и `python -m pytest -q`; убедиться, что `warehouse/cli.py`, `warehouse/reports.py` и существующие тесты не изменены (`git diff --stat`)
