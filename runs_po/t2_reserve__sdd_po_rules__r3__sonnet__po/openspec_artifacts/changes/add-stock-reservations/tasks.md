## 1. Модели и ошибки

- [x] 1.1 Добавить в `warehouse/models.py` `ReservationStatus`, `ReservationLine`, `Reservation` (frozen, поля как в задаче); проверить тестом на неизменяемость и значения enum
- [x] 1.2 Добавить в `warehouse/errors.py` `ReservationError` и четыре наследника с атрибутом `order_id`; проверить тестом `isinstance(..., WarehouseError)` и `exc.order_id`
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` и внутренней записью резерва; проверить тестом значения константы

## 2. Хранение и запросы

- [x] 2.1 Добавить в `InMemoryStore` методы хранения резервов, не меняя существующие; существующие тесты проходят
- [x] 2.2 Реализовать вычисление эффективного статуса по часам сервиса, `get_reservation`, `reserved`, `available` (`max(0, on_hand - reserved)`); тесты: `available` равен 0 при физическом остатке меньше резерва, истечение на границе, `CONFIRMED`/`CANCELLED` не истекают, `ReservationNotFoundError`, `UnknownSkuError`

## 3. Операции

- [x] 3.1 Реализовать `reserve` с валидацией, дублями строк, `DuplicateReservationError` (только для `ACTIVE`/`CONFIRMED`; истёкший или отменённый резерв полностью заменяется новым), атомарностью и событиями `RESERVE`; тесты по сценариям spec (разные склады, TTL, дубли позиций, повторный reserve для активного/подтверждённого/отменённого/истёкшего, ошибки, журнал не меняется при ошибке)
- [x] 3.2 Реализовать `confirm` (проверка по сумме позиции против физического остатка, `ISSUE` с `ref`, затем `RESERVE_CONFIRM`); тесты: нулевой `available`, дубли строк, истёкший, повторный, отменённый
- [x] 3.3 Реализовать `cancel` (идемпотентность, истёкший no-op, подтверждённый — ошибка) и `RESERVE_CANCEL`; тесты: повторная отмена не пишет в журнал
- [x] 3.4 Реализовать `extend` (новый срок `now + ttl`, не сокращается; без роста срока — без изменений и без события) и `RESERVE_EXTEND`; тесты: успех от `now`, отсутствие сокращения и события, истёкший, финальные статусы, невалидный `ttl`
- [x] 3.5 Учесть активные резервы в `issue` и `transfer` (по `available`); тесты: расход сверх доступного, в пределах доступного, истёкший резерв не блокирует, поведение без резервов прежнее

## 4. Завершение

- [x] 4.1 Экспортировать новые имена в `warehouse/__init__.py` и проверить импорт `from warehouse import Reservation, ReservationError, ...`
- [x] 4.2 Запустить `python -m pytest -q` целиком: существующие тесты проходят без правок, а `git diff` не затрагивает `cli.py`, `reports.py`, существующие тесты и зависимости
- [x] 4.3 Сверить публичный API реализации с proposal и specs: имена, сигнатуры и порядок параметров `reserve/confirm/cancel/extend/get_reservation/available/reserved`, поля моделей, значения enum, атрибут `order_id` у ошибок, `DEFAULT_RESERVATION_TTL == timedelta(minutes=15)`, поля событий
