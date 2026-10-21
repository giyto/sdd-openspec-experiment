## 1. Константы и модели

- [x] 1.1 В `warehouse/reservations.py` заменить `DEFAULT_RESERVATION_TTL` на 20 минут и добавить `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`; проверить значения тестом
- [x] 1.2 Добавить `Availability` (`@dataclass(frozen=True)`: `warehouse`, `sku`, `on_hand`, `reserved`, `available`) в `warehouse/models.py`; проверить импорт `python -c "from warehouse.models import Availability"`

## 2. Хранилище

- [x] 2.1 В `InMemoryStore` (`warehouse/storage.py`) добавить `all_reservations()` (без фильтра по статусу), `mark_expiry_reported(reservation)` и `expiry_reported(reservation)` по ключу `(order_id, created_at)`; проверить тестом на чистом хранилище, что отметки пусты и `all_reservations()` возвращает все резервы

## 3. Замена резерва в `reserve`

- [x] 3.1 Добавить проверку `ttl > MAX_RESERVATION_LIFETIME` в `_validate_ttl` (или рядом с `reserve`) до любых изменений; проверить: `ttl` равный 2 часам допустим, 2 часа + 1 секунда дают `ValidationError`, журнал и активный резерв не меняются
- [x] 3.2 Изменить `reserve`: `CONFIRMED` действующий — по-прежнему `DuplicateReservationError`; действующий `ACTIVE` — замена: проверка доступности исключает строки старого резерва, при успехе пишется `RESERVE_CANCEL` старого, затем `RESERVE` по строкам нового; при нехватке старый резерв остаётся прежним; проверить сценарии «замена считает свои строки свободными», «замена не проходит по доступному», порядок событий замены
- [x] 3.3 Проверить, что замена истёкшего `ACTIVE` резерва не пишет `RESERVE_CANCEL` (только `RESERVE` по строкам нового)

## 4. Возврат подтверждённого в `cancel`

- [x] 4.1 Изменить `cancel` для `CONFIRMED`: приход по каждой строке в порядке строк (`RECEIVE` с `ref=<order_id>`, без повторной валидации), затем `RESERVE_CANCEL`, статус `CANCELLED`, все записи после проверок; проверить сценарий «возврат подтверждённого» (остатки по складам выросли, два `RECEIVE`, затем `RESERVE_CANCEL`)
- [x] 4.2 Проверить, что отмена `CANCELLED` и `EXPIRED` остаётся no-op без событий (существующие сценарии покрывают, дополнить при необходимости)

## 5. Предел срока в `extend`

- [x] 5.1 Изменить `extend`: новый срок `min(now + ttl, created_at + MAX_RESERVATION_LIFETIME)`, без ошибки при превышении предела; если результат не позже `expires_at`, резерв не меняется и событие не пишется; проверить сценарий «продление сверх предельного срока» (создан в 10:00, продлён в 10:10 на 3 часа → `expires_at` 12:00, `RESERVE_EXTEND` с `expires` 12:00) и `ttl` ≤ 0 → `ValidationError`

## 6. Чтение резервов и доступности

- [x] 6.1 Реализовать `Inventory.reservations(status=None)`: снимки через `_snapshot`, фильтр по статусу на текущий момент, сортировка по `(created_at, order_id)`, без событий; проверить сценарии «все резервы в порядке создания» и «фильтр по статусу на текущий момент»
- [x] 6.2 Реализовать `Inventory.availability(warehouse=None)`: строки по позициям с `on_hand > 0` или `reserved > 0` (`reserved` только по действующим `ACTIVE`), значения как у `on_hand`/`reserved`/`available`, сортировка по складу и SKU, фильтр точным совпадением склада; проверить сценарии «позиция только с резервом», «фильтр по складу», «позиция без остатка и резерва не попадает»

## 7. Сигнал истечения `sweep_expired`

- [x] 7.1 Реализовать `Inventory.sweep_expired()` в два прохода: сначала собрать `EXPIRED` на `now` без отметки, отсортировать по `(expires_at, order_id)`; затем для каждого записать `RESERVE_EXPIRE` (`order`, `expires` через `format_timestamp`) и отметку в хранилище; статусы и остатки не менять; проверить сценарии «первый вызов», «повторный вызов возвращает пусто», «порядок по времени истечения», «повторно истёкший заказ даёт новое событие»

## 8. Тесты

- [x] 8.1 В `tests/test_reservations.py` привести четыре проверки, которые фиксируют отменённые правила, к новому поведению: `test_default_ttl_is_fifteen_minutes` и `test_reserve_default_ttl_sets_expiry` — 20 минут; `test_reserve_duplicate_active_rejected` — замена вместо ошибки; `test_cancel_confirmed_raises` — возврат вместо ошибки. Проверить: `python -m pytest -q tests/test_reservations.py` зелёный (см. design.md, раздел про существующие тесты)
- [x] 8.2 Добавить новый файл `tests/test_reservations_rework.py` с тестами сценариев из spec-дельты, которые не покрыты существующими тестами (замена, возврат, предел срока, `reservations`, `availability`, `sweep_expired`, отсутствие записей при ошибках); проверить `python -m pytest -q tests/test_reservations_rework.py`

## 9. Итоговая проверка

- [x] 9.1 Запустить `python -m pytest -q` и убедиться, что весь набор зелёный
- [x] 9.2 Проверить границы: `git diff --stat -- warehouse/cli.py warehouse/reports.py warehouse/events.py tests/test_cli.py tests/test_reports.py tests/test_inventory.py tests/test_events.py` пуст; новых зависимостей в проекте нет
- [x] 9.3 Проверить, что формат строки журнала не менялся: `tests/test_events.py` проходит без изменений, `warehouse/events.py` не меняется
