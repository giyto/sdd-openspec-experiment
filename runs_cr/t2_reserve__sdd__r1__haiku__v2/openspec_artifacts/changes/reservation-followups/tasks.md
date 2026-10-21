## 1. Модели и константы

- [x] 1.1 В `warehouse/reservations.py` сменить `DEFAULT_RESERVATION_TTL` на 20 минут и добавить `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`
- [x] 1.2 В `warehouse/models.py` добавить frozen-датакласс `Availability(warehouse, sku, on_hand, reserved, available)`

## 2. Хранилище

- [x] 2.1 В `warehouse/storage.py` добавить историю логических резервов по ключу `(order_id, created_at)`; `put_reservation` обновляет и текущий слот заказа, и запись истории
- [x] 2.2 Добавить в `warehouse/storage.py` множество отчитанных ключей и методы чтения истории и отметки отчёта

## 3. Правила резервов

- [x] 3.1 В `warehouse/reservations.py` добавить проверку предела для `reserve` (`ttl > MAX_RESERVATION_LIFETIME` → `ValidationError`), отдельно от `validate_ttl`
- [x] 3.2 Добавить функцию ограничения срока для `extend`: `min(now + ttl, created_at + MAX_RESERVATION_LIFETIME)`

## 4. Inventory: замена и возврат

- [x] 4.1 `_available_at` и `_reserved_at` получают необязательный `exclude_order`, по умолчанию без исключений
- [x] 4.2 `reserve`: валидация, исключение заменяемого `ACTIVE`-резерва из проверки наличия, отказ при `CONFIRMED` (`DuplicateReservationError` сохраняется), запись `RESERVE_CANCEL` и затем `RESERVE` по строкам только после успешной проверки
- [x] 4.3 `cancel`: для `CONFIRMED` вернуть товар по строкам (`RECEIVE` с `ref`=заказ), затем статус `CANCELLED` и `RESERVE_CANCEL`
- [x] 4.4 `extend`: применить ограничение срока из 3.2; значение по умолчанию берётся из `DEFAULT_RESERVATION_TTL`

## 5. Inventory: новые методы

- [x] 5.1 `reservations(status=None)`: снимки текущих резервов с эффективным статусом, фильтр по статусу, сортировка по `created_at`, затем `order_id`
- [x] 5.2 `availability(warehouse=None)`: позиции из физических остатков и активных резервов, сортировка и фильтр как у `stock_levels`, значения через `_reserved_at` и `_available_at`
- [x] 5.3 `sweep_expired()`: перебор истории, `RESERVE_EXPIRE` (`order`, `expires`) по каждому неотчитанному истёкшему резерву, отметка отчёта, возврат `order_id` по `expires_at`, затем `order_id`

## 6. Тесты

- [x] 6.1 Новый файл `tests/test_reservations_followups.py` (существующие тесты не меняем): замена активного резерва, замена с нехваткой (старый резерв цел), замена в тот же момент времени, замена `CONFIRMED` запрещена
- [x] 6.2 Тесты возврата: `RECEIVE` по строкам с `ref`, порядок событий, повторная отмена без событий
- [x] 6.3 Тесты TTL 20 минут по умолчанию, предела 2 часа (`ttl` равный пределу — ok, больше — `ValidationError`), `extend` с ограничением и без события на пределе
- [x] 6.4 Тесты `reservations()`: статус-фильтр по эффективному статусу, порядок, один снимок на заказ после замены
- [x] 6.5 Тесты `availability()`: позиция с остатком и резервом, резерв без остатка, фильтр по складу, совпадение значений с `reserved`/`available`
- [x] 6.6 Тесты `sweep_expired()`: однократная отметка, порядок, истёкший резерв, заменённый до sweep, повторно истёкший резерв того же заказа, отсутствие изменений статусов и остатков

## 7. Проверка

- [x] 7.1 Запустить `pytest` и убедиться, что новые тесты проходят
- [ ] 7.2 Запустить весь набор: ожидаемо падают только пять существующих тестов из раздела «Риски» в `design.md` (`test_default_ttl_is_fifteen_minutes`, `test_default_ttl_sets_expires_at`, `test_active_reservation_cannot_be_duplicated`, `test_cancel_confirmed_raises`, `test_extend_default_ttl_is_fifteen_minutes`); любое другое падение — ошибка реализации
- [x] 7.3 Проверить, что `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты и `pytest.ini` не изменены (`git diff --stat`)
