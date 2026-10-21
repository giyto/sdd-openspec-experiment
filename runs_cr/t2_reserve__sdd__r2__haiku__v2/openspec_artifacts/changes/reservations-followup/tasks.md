## 1. Модели и константы

- [x] 1.1 `warehouse/models.py`: добавить frozen dataclass `Availability` (`warehouse`, `sku`, `on_hand`, `reserved`, `available`)
- [x] 1.2 `warehouse/reservations.py`: `DEFAULT_RESERVATION_TTL` = 20 минут; добавить `MAX_RESERVATION_LIFETIME` = 2 часа
- [x] 1.3 `warehouse/reservations.py`: в `ReservationRecord` добавить поле `expire_reported: bool = False`
- [x] 1.4 `warehouse/storage.py`: метод перечисления всех записей резервов (для `reservations()`, `availability()`, `sweep_expired()`)
- [x] 1.5 `warehouse/__init__.py`: экспорт `Availability` и `MAX_RESERVATION_LIFETIME`

## 2. Замена резерва и TTL в `reserve`

- [x] 2.1 Проверка `ttl > MAX_RESERVATION_LIFETIME` → `ValidationError` (после существующей проверки TTL)
- [x] 2.2 `_available_at` с необязательным исключением прежней записи для проверки наличия
- [x] 2.3 `reserve`: `DuplicateReservationError` только для `CONFIRMED`; для `ACTIVE` (живого) — замена
- [x] 2.4 Порядок записи: `RESERVE_CANCEL` по прежнему живому резерву (если был), затем `RESERVE` по строкам новой записи; все события после проверок

## 3. Возврат в `cancel` и предел в `extend`

- [x] 3.1 `cancel` для `CONFIRMED`: `RECEIVE` по каждой строке (`ref` = `order_id`) с увеличением остатков, затем `RESERVE_CANCEL`, статус `CANCELLED`
- [x] 3.2 `extend`: срок ограничивается `created_at + MAX_RESERVATION_LIFETIME`; событие только при росте `expires_at`

## 4. Новые методы выборки

- [x] 4.1 `Inventory.reservations(status=None)`: снимки всех записей, фильтр по вычисленному статусу, сортировка по `(created_at, order_id)`
- [x] 4.2 `Inventory.availability(warehouse=None)`: позиции из ненулевых остатков и живых активных резервов; сортировка и фильтр как у `stock_levels`

## 5. Отметка истечения

- [x] 5.1 `Inventory.sweep_expired()`: выбрать записи со статусом `EXPIRED` и `expire_reported = False`, отсортировать по `(expires_at, order_id)`
- [x] 5.2 По каждой записи написать `RESERVE_EXPIRE` (`order`, `expires` через `format_timestamp`), выставить `expire_reported = True`, вернуть `order_id` в том же порядке

## 6. Тесты

- [x] 6.1 Новые тесты в `tests/test_reservations.py` (или в отдельном файле `tests/test_reservations_followup.py`) для сценариев спецификации: замена, нехватка при замене, возврат, предел TTL и `extend`, `reservations()`, `availability()`, `sweep_expired()`
- [x] 6.2 Проверить журнал по каждому сценарию (порядок и поля событий)
- [ ] 6.3 Прогнать `python -m pytest -q`; все существующие тесты, кроме перечисленных в 6.4, проходят без изменений

## 7. Устаревшие ожидания в существующих тестах (требует подтверждения)

- [ ] 7.1 Подтвердить у пользователя обновление четырёх тестов, закрепляющих отменённые правила: `test_default_ttl_is_fifteen_minutes`, `test_reserve_multiple_warehouses_keeps_lines_and_on_hand` (15 минут), `test_duplicate_while_active`, `test_cancel_confirmed_raises`
- [x] 7.2 После подтверждения обновить ожидаемые значения и названия этих четырёх тестов; остальные тесты не трогать

## 8. Проверка границ

- [x] 8.1 `warehouse/cli.py` и `warehouse/reports.py` не изменены (`git diff --stat`)
- [x] 8.2 Новых зависимостей нет (`pytest.ini`, `README.md` без изменений зависимостей)
