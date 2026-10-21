## 1. Модели и константы

- [x] 1.1 Добавить `Availability(warehouse, sku, on_hand, reserved, available)` (frozen) в `warehouse/models.py` и проверить новым тестом: имена полей, неизменяемость
- [x] 1.2 В `warehouse/reservations.py` поставить `DEFAULT_RESERVATION_TTL = timedelta(minutes=20)`, добавить `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`, поле `expiry_reported` в `ReservationRecord` и помощник обрезки срока; проверить юнит-тестами значения констант и обрезки (в т.ч. граница ровно на пределе)

## 2. Хранилище

- [x] 2.1 В `InMemoryStore` добавить хранение вытесненных, но неотмеченных истёкших записей (добавить, выдать, удалить); проверить юнит-тестом

## 3. Изменения существующих операций

- [x] 3.1 `reserve`: `ttl > MAX_RESERVATION_LIFETIME` → `ValidationError`; проверить тестами сценариев «TTL ровно на пределе» и «TTL больше предела» (журнал и прежний резерв не меняются)
- [x] 3.2 `reserve`: замена активного резерва (свободное количество заменяемого, атомарность, `RESERVE_CANCEL` затем `RESERVE`, новый `created_at`/`expires_at`), `DuplicateReservationError` только для подтверждённого; проверить тестами всех сценариев требования «Повторный reserve по тому же заказу»
- [x] 3.3 `cancel` подтверждённого — возврат (`RECEIVE` с `ref` по строкам, затем `RESERVE_CANCEL`, статус `CANCELLED`, повтор — no-op); проверить тестами сценариев требования «Отмена резерва», включая строки одной позиции и точный состав журнала
- [x] 3.4 `extend`: обрезка срока по `created_at + MAX_RESERVATION_LIFETIME`, событие с обрезанным значением, no-op на пределе; проверить тестами сценариев требования «Продление резерва»

## 4. Новые методы

- [x] 4.1 `reservations(status=None)`: фильтр по статусу на текущий момент, сортировка `created_at`, `order_id`, один снимок на заказ, `ValidationError` для некорректного `status`; проверить тестами сценариев «Список резервов»
- [x] 4.2 `availability(warehouse=None)`: позиции с остатком или активным резервом, порядок и фильтр как у `stock_levels`, значения совпадают с `on_hand`/`reserved`/`available`; проверить тестами сценариев «Сводка наличия»
- [x] 4.3 `sweep_expired()`: кандидаты, порядок `expires_at`/`order_id`, `RESERVE_EXPIRE` (`order`, `expires`), один раз на резерв, новый резерв того же заказа, вытесненный неотмеченный; статусы и остатки не меняются; проверить тестами сценариев «Фиксация истечения резервов»

## 5. Проверки

- [x] 5.1 Запустить `python -m pytest -q`; убедиться, что новые тесты проходят, а падения старых тестов ограничены ожидаемыми (дубликат активного, TTL 15 минут, отмена подтверждённого) и перечислены в отчёте; выполнить `git diff --stat` и убедиться, что `warehouse/cli.py`, `warehouse/reports.py` и существующие тесты не изменены, зависимости не добавлены
- [x] 5.2 Сверить публичный API реализации с proposal и specs (скриптом через `inspect.signature` и `dataclasses.fields`): `Availability`, `MAX_RESERVATION_LIFETIME`, `DEFAULT_RESERVATION_TTL`, сигнатуры `reservations(status=None)`, `availability(warehouse=None)`, `sweep_expired()`, `reserve/confirm/cancel/extend/get_reservation/available/reserved`; устранить расхождения
