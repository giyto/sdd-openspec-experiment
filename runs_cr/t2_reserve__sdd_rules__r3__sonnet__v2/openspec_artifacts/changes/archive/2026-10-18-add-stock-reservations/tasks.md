## 1. Модели, ошибки, константы

- [x] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py` (значения enum и поля как в тикете); проверить тестом на значения статусов и неизменяемость
- [x] 1.2 Добавить `ReservationError` и четыре наследника в `warehouse/errors.py` с атрибутом `order_id`; тест: все наследуются от `WarehouseError`, `order_id` доступен
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` и помощниками (нормализация строк, проверка `ttl`, вычисление статуса); тест на значение константы и на проверку `ttl`
- [x] 1.4 Добавить в `InMemoryStore` аддитивные методы хранения резервов; существующие тесты `python -m pytest -q` остаются зелёными

## 2. Запросы и резервирование

- [x] 2.1 Реализовать `reserved` и `available` (с `max(0, ...)`, `UnknownSkuError`); тесты: активный, истёкший, подтверждённый, отменённый резерв, `adjust` ниже резерва
- [x] 2.2 Реализовать `reserve` (валидация, проверка по суммам дублей позиций, атомарность, события `RESERVE`, TTL по умолчанию); тесты: несколько складов, дубли строк, ошибки валидации, `InsufficientStockError`, журнал не меняется при ошибке
- [x] 2.3 Реализовать правила повторного `reserve` (`DuplicateReservationError` для активного и подтверждённого, замена истёкшего и отменённого, неудачная замена не затирает старый); тесты на все ветки
- [x] 2.4 Реализовать `get_reservation` с вычисляемым `EXPIRED` на границе `now >= expires_at` и окончательными `CONFIRMED`/`CANCELLED`; тесты с `ManualClock`: граница, подтверждённый после срока, журнал не пишется

## 3. Жизненный цикл

- [x] 3.1 Реализовать `confirm` (проверка физического остатка по суммам, события `ISSUE` с `ref`, затем `RESERVE_CONFIRM`, ошибки статусов, ничего не меняется при нехватке); тесты: нулевой `available`, нехватка после `adjust`, дубли позиции, истёкший/подтверждённый/отменённый
- [x] 3.2 Реализовать `cancel` (идемпотентность, истёкший остаётся `EXPIRED`, подтверждённый -> `ReservationStateError`, `RESERVE_CANCEL` только при реальной отмене); тесты на журнал
- [x] 3.3 Реализовать `extend` (`now + ttl`, без сокращения, `ValidationError`, ошибки статусов как у `confirm`, `RESERVE_EXTEND` только при изменении); тесты: продление, непродление без события, ошибки
- [x] 3.4 Проверить `ReservationNotFoundError` для `confirm/cancel/extend/get_reservation` и неизменность выданных снимков; тесты

## 4. Расход и совместимость

- [x] 4.1 Ограничить `issue` и `transfer` (источник) значением `available`, не затрагивая `confirm`; тесты: расход из чужого резерва, в пределах `available`, после истечения, без резервов
- [x] 4.2 Проверить формат строк журнала для `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND` (поле `expires` в формате журнала); тест через `EventLog.lines()` и `parse_line`
- [x] 4.3 Добавить новые публичные имена в `warehouse/__init__.py`; убедиться, что `cli.py`, `reports.py` и существующие тесты не изменены (`git diff --stat`) и `python -m pytest -q` проходит

## 5. Финальная сверка

- [x] 5.1 Сверить публичный API реализации с proposal и specs: имена модулей, классов, полей, значений enum, сигнатур (`reserve(self, order_id, lines, ttl=None)`, `confirm`, `cancel`, `extend(self, order_id, ttl)`, `get_reservation`, `available`, `reserved`), атрибута `order_id` у ошибок и `DEFAULT_RESERVATION_TTL` (например, скриптом с `inspect.signature`); расхождений нет
