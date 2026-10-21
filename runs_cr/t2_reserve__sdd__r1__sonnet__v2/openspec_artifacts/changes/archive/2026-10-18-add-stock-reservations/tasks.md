## 1. Модели, ошибки, константы

- [x] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py`; тест проверяет frozen-датаклассы и значения статусов
- [x] 1.2 Добавить `ReservationError` и четыре наследника с атрибутом `order_id` в `warehouse/errors.py`; тест проверяет иерархию от `WarehouseError` и атрибут
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)`, валидацией ttl и строк, агрегацией по позициям; юнит-тесты на ttl (ноль, отрицательный, не timedelta, bool), пустые строки, кортеж и `ReservationLine`

## 2. Хранилище и запросы

- [x] 2.1 Добавить в `InMemoryStore` хранение резервов и вычисление эффективного статуса на момент `now`; тест границы `now == expires_at` и неизменности `CONFIRMED`/`CANCELLED`
- [x] 2.2 Реализовать `reserved`, `available` (не меньше 0), `get_reservation`; тесты: после `adjust` ниже резерва `available == 0`, `ReservationNotFoundError`, `UnknownSkuError`

## 3. Операции

- [x] 3.1 Реализовать `reserve` (атомарно, суммы по позиции, `RESERVE` на строку, замена истёкшего/отменённого, `DuplicateReservationError` для активного/подтверждённого); тесты: разные склады, дубли строк, откат при нехватке, журнал не меняется при ошибке
- [x] 3.2 Реализовать `confirm` (физический остаток по суммам, `ISSUE` с `ref` на строку, затем `RESERVE_CONFIRM`); тесты: нулевой `available`, нехватка по одной позиции ничего не списывает, истёкший/подтверждённый/отменённый
- [x] 3.3 Реализовать `cancel` (идемпотентность, истёкший остаётся `EXPIRED`, подтверждённый → `ReservationStateError`) и `extend` (от `now`, без сокращения, без события при отсутствии изменений); тесты на журнал
- [x] 3.4 Ограничить `issue` и источник `transfer` значением `available`; тесты: `issue` против активного резерва даёт `InsufficientStockError` с верным `available`, после истечения проходит

## 4. Завершение

- [x] 4.1 Экспортировать новые публичные имена в `warehouse/__init__.py`; тест проверяет импорт из пакета
- [x] 4.2 Запустить `python -m pytest -q`: все старые тесты проходят без изменений; `git diff` не затрагивает `cli.py`, `reports.py`, существующие тесты и зависимости
