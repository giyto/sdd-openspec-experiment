## 1. Модели, ошибки, константа

- [x] 1.1 Добавить в `warehouse/models.py` `ReservationStatus`, `ReservationLine`, `Reservation` (frozen, как в ТЗ); проверить импортом и тестом на неизменяемость и значения статусов
- [x] 1.2 Добавить в `warehouse/errors.py` `ReservationError` и четыре наследника с атрибутом `order_id`; проверить тестом `isinstance(..., WarehouseError)` и наличие `order_id`
- [x] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)`; проверить тестом на значение

## 2. Хранение и чистая логика

- [x] 2.1 Добавить в `InMemoryStore` методы хранения записей резервов (добавить, получить, перечислить); проверить, что существующие тесты хранилища/инвентаря проходят без изменений
- [x] 2.2 В `reservations.py` реализовать внутреннюю запись резерва, нормализацию строк (кортеж или `ReservationLine`, порядок сохраняется), вычисление статуса (`ACTIVE` при `now >= expires_at` → `EXPIRED`; `CONFIRMED`/`CANCELLED` не меняются), построение снимка и суммирование по позициям; проверить unit-тестами, включая границу `now == expires_at` и дублирующиеся строки

## 3. Запросы и расход

- [x] 3.1 Реализовать `Inventory.reserved` и `Inventory.available` (активные резервы, `max(0, …)`, `UnknownSkuError` для незарегистрированного SKU); проверить тестами из сценариев «Доступный и зарезервированный остаток» и «Истечение резерва»
- [x] 3.2 Перевести проверку достаточности в `issue` и `transfer` (источник) на `available`; проверить сценариями «Расход не забирает резервы» и тем, что весь существующий набор тестов проходит без изменений

## 4. Операции с резервами

- [x] 4.1 Реализовать `reserve` с порядком проверок из design, атомарностью и событиями `RESERVE` по строкам; проверить тестами: два склада, TTL по умолчанию и явный, `ValidationError` (ttl ≤ 0, не `timedelta`, пустой список, плохие коды), `InvalidQuantityError`, `UnknownSkuError`, `DuplicateReservationError` (для `ACTIVE`/`CONFIRMED`, без изменений) и замену истёкшего/отменённого резерва новым, `InsufficientStockError` по сумме дубликатов и по второй строке без следов в журнале
- [x] 4.2 Реализовать `get_reservation` и общий поиск с `ReservationNotFoundError`; проверить NotFound для всех четырёх методов и неизменность ранее полученного снимка
- [x] 4.3 Реализовать `confirm` (проверка физического остатка по суммам позиций, `ISSUE` с `ref=order_id` по строкам, затем `RESERVE_CONFIRM`); проверить: нулевой `available` не мешает, дубликаты строк, порядок событий, `ReservationExpiredError`, `ReservationStateError`, `InsufficientStockError` после `adjust` вниз без изменений состояния и журнала
- [x] 4.4 Реализовать `cancel` (идемпотентность, `ReservationStateError` для подтверждённого, no-op для истёкшего, `RESERVE_CANCEL` только при реальной отмене); проверить, что число событий не растёт при повторной отмене и отмене истёкшего
- [x] 4.5 Реализовать `extend` (`now + ttl`, срок не сокращается: при `now + ttl <= expires_at` без изменений и без события; валидация ttl как в `reserve`, статусные ошибки как у `confirm`, событие `RESERVE_EXTEND` с новым `expires`); проверить тестами из сценариев продления

## 5. Журнал, экспорт, документация

- [x] 5.1 Проверить форматы событий: поля `order/wh/sku/qty/expires`, формат времени `expires` совпадает с временем события, строки проходят `parse_line`; тест-характеристика, что `movement_summary` не искажает `received/issued/adjusted` из-за `RESERVE*` (запись с нулями допустима)
- [x] 5.2 Экспортировать новые модели и ошибки из `warehouse/__init__.py`, добавить `reservations.py` в схему модулей README; проверить `from warehouse import Reservation, ReservationNotFoundError`
- [x] 5.3 Все новые тесты вынести в новый файл `tests/test_reservations.py` на `ManualClock` (существующие тесты не менять); финально выполнить `python -m pytest -q` — всё зелёное, `git diff --stat` не затрагивает `cli.py`, `reports.py` и существующие тесты
