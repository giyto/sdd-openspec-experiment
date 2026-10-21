## 1. Модели и константы

- [x] 1.1 Добавить `Availability` (frozen dataclass: `warehouse`, `sku`, `on_hand`, `reserved`, `available`) в `warehouse/models.py`
- [x] 1.2 В `warehouse/reservations.py` поставить `DEFAULT_RESERVATION_TTL = timedelta(minutes=20)`, добавить `MAX_RESERVATION_LIFETIME = timedelta(hours=2)` и поле `expire_logged: bool = False` в `ReservationRecord`

## 2. Создание, замена и продление

- [x] 2.1 В `reserve` бросать `ValidationError` при `ttl > MAX_RESERVATION_LIFETIME` до любых изменений
- [x] 2.2 В `reserve` реализовать замену активного резерва: освобождаемое количество считается свободным; при успехе `RESERVE_CANCEL` старого, затем `RESERVE` нового; подтверждённый даёт `DuplicateReservationError`; ошибка не меняет резервы и журнал
- [x] 2.3 В `extend` ограничить срок значением `created_at + MAX_RESERVATION_LIFETIME` без ошибки; событие только при реальном изменении

## 3. Возврат

- [x] 3.1 В `cancel` подтверждённого заказа вернуть товар по строкам (`RECEIVE` с `ref` = order_id), статус `CANCELLED`, затем `RESERVE_CANCEL`; повторный `cancel` — no-op

## 4. Новые методы Inventory

- [x] 4.1 `reservations(status=None)`: снимки, сортировка по `created_at`, `order_id`, фильтр по текущему статусу
- [x] 4.2 `availability(warehouse=None)`: позиции с остатком или активным резервом, порядок и фильтр как у `stock_levels`, значения как у `on_hand`, `reserved`, `available`
- [x] 4.3 `sweep_expired()`: `RESERVE_EXPIRE` (`order`, `expires`) один раз на резерв, порядок `expires_at`, `order_id`, статусы и остатки не меняются

## 5. Тесты

- [x] 5.1 Добавить новые тесты по сценариям спецификации (замена, возврат, TTL и предел, `reservations`, `availability`, `sweep_expired` включая повторный резерв заказа); существующие тесты не менять
- [x] 5.2 Запустить весь набор тестов и отдельно перечислить существующие тесты, расходящиеся с новым поведением (15 минут, дубликат активного, отмена подтверждённого)

## 6. Сверка публичного API

- [x] 6.1 Сверить публичный API реализации с proposal и specs: `Availability` и её поля, `MAX_RESERVATION_LIFETIME`, `DEFAULT_RESERVATION_TTL`, сигнатуры `reservations`, `availability`, `sweep_expired`, имена событий и поля журнала; `cli.py` и `reports.py` не изменены
