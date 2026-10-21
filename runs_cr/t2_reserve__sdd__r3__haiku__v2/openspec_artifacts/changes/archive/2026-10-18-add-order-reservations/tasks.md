## 1. Модели, ошибки и константы

- [x] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py` по публичному API из задачи и проверить импорт `python -c "from warehouse.models import Reservation, ReservationLine, ReservationStatus"`
- [x] 1.2 Добавить `ReservationError(WarehouseError)` с атрибутом `order_id` и наследников `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError` в `warehouse/errors.py`; проверить, что все наследуют `WarehouseError` и отдают `order_id`
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` и проверить значение в тесте

## 2. Хранилище резервов

- [x] 2.1 Добавить в `InMemoryStore` (`warehouse/storage.py`) хранение резервов по `order_id`: `get_reservation`, `put_reservation`, `has_reservation`, `active_reservations` (только сохранённые `ACTIVE`) и проверить тестом на чистом хранилище
- [x] 2.2 Проверить, что существующие тесты `tests/test_inventory.py` проходят без изменений (`python -m pytest -q`)

## 3. Расчёт доступного и занятого

- [x] 3.1 Реализовать вычисление статуса на момент (`ACTIVE` с `now >= expires_at` → `EXPIRED`) и `reserved(warehouse, sku)` по действующим `ACTIVE` резервам; проверить тестами границу срока из spec
- [x] 3.2 Реализовать `available(warehouse, sku)` как `max(0, on_hand - reserved)`; проверить сценарий «остаток меньше резерва» из spec

## 4. Резерв, подтверждение, отмена, продление

- [x] 4.1 Реализовать `reserve`: нормализация и валидация строк и `ttl`, проверка дубликата (с учётом истечения), проверка доступного по сумме строк позиции, запись резерва и событий `RESERVE` (`expires` через `format_timestamp`); проверить сценарии создания, дубликата, замены истёкшего и отсутствия изменений при ошибке
- [x] 4.2 Реализовать `confirm`: проверка статуса и срока, проверка физического остатка по сумме строк, списание, события `ISSUE` с `ref` и `RESERVE_CONFIRM`; проверить успешный путь, нехватку физики (ничего не меняется) и нулевой `available` при собственном резерве
- [x] 4.3 Реализовать `cancel` идемпотентно: `RESERVE_CANCEL` только для активного; проверить повторную отмену, отмену истёкшего и отмену подтверждённого
- [x] 4.4 Реализовать `extend` с правилом «срок не сокращается» (без события, если `now + ttl` не позже `expires_at`), события `RESERVE_EXTEND`; проверить продление, отсутствие сокращения и ошибку для истёкшего
- [x] 4.5 Реализовать `get_reservation` с вычисляемым статусом и `ReservationNotFoundError` для неизвестного `order_id` во всех методах, где это требуется; проверить на `confirm`, `cancel`, `extend`, `get_reservation`

## 5. Расход не забирает резерв

- [x] 5.1 Перевести проверку в `issue` и источник `transfer` на `available`, сохранив порядок проверок (позиция, количество, ссылка) и сообщение `InsufficientStockError`; проверить расход сверх доступного и расход без резервов (поведение и события как прежде)

## 6. Журнал и итоговая проверка

- [x] 6.1 Проверить формат событий резервов в тестах: строки `RESERVE`, `ISSUE` с `ref`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND` и отсутствие событий при истечении срока
- [x] 6.2 Проверить атомарность: при любой ошибке валидации или нехватке состояние и журнал не меняются (отдельные тесты на `reserve`, `confirm`, `extend`)
- [x] 6.3 Запустить полный набор `python -m pytest -q` и убедиться, что существующие тесты `cli` и `reports` проходят без изменения их файлов (`git diff --stat -- tests/test_cli.py tests/test_reports.py tests/test_inventory.py tests/test_events.py` пуст, `warehouse/cli.py` и `warehouse/reports.py` не меняются)
