## Purpose

Резервирование товара под заказы с ограниченным временем жизни, чтобы один и тот же товар не продавался дважды, пока заказ оформляется и оплачивается.

## ADDED Requirements

### Requirement: Модель резерва и статусы
Сервис SHALL отдавать резерв как неизменяемый снимок `Reservation(order_id, lines, created_at, expires_at, status)`, где `lines` — кортеж `ReservationLine(warehouse, sku, qty)` в том порядке и в том составе, как они были переданы (одинаковые позиции не склеиваются). `ReservationStatus` SHALL иметь значения `ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`. Статус снимка SHALL соответствовать текущему моменту по часам сервиса. `DEFAULT_RESERVATION_TTL` (модуль `warehouse/reservations.py`) SHALL равняться 15 минутам.

#### Scenario: Снимок хранит строки как переданы
- **WHEN** вызван `reserve("SO-1", [("MAIN","BOLT",2), ("MAIN","BOLT",3)])`
- **THEN** `lines` содержит две отдельные `ReservationLine` в этом порядке, статус `ACTIVE`

#### Scenario: TTL по умолчанию
- **WHEN** `reserve` вызван без `ttl` в момент T
- **THEN** `created_at == T` и `expires_at == T + timedelta(minutes=15)`

### Requirement: Создание резерва
`reserve(order_id, lines, ttl=None)` SHALL атомарно зарезервировать товар сразу по всем строкам (склады могут различаться), не меняя физический остаток. `created_at` SHALL быть текущим временем сервиса, `expires_at = created_at + ttl`. Строки SHALL приниматься как кортежи `(warehouse, sku, qty)` или `ReservationLine`. `order_id`, склады и SKU SHALL проверяться как коды (непустая строка без пробелов и `=`); количества — как обычные количества (`InvalidQuantityError`); незарегистрированный SKU — `UnknownSkuError`. Пустой набор строк и `ttl`, не являющийся положительным `timedelta`, SHALL давать `ValidationError`. Если у `order_id` есть действующий (`ACTIVE`) или подтверждённый (`CONFIRMED`) резерв, SHALL быть `DuplicateReservationError` (на заказ уже есть резерв), состояние не меняется. Если прежний резерв истёк или отменён, новый резерв SHALL быть разрешён и полностью заменять старый. Достаточность SHALL проверяться по сумме количеств строк одной позиции (склад + SKU) относительно `available`; при нехватке — `InsufficientStockError` (`requested` — сумма по позиции). При любой ошибке состояние и журнал SHALL остаться без изменений.

#### Scenario: Успешное резервирование на нескольких складах
- **WHEN** на складах A и B достаточно товара и вызван `reserve` со строками для обоих
- **THEN** возвращён резерв `ACTIVE`, `on_hand` не изменился, `reserved` по каждой позиции вырос на qty

#### Scenario: Дубли позиции проверяются по сумме
- **WHEN** доступно 4, а резервируются две строки одной позиции по 3
- **THEN** `InsufficientStockError` с `requested=6`, и ничего не зарезервировано

#### Scenario: Нехватка по одной из строк не оставляет частичного резерва
- **WHEN** первая строка укладывается в доступное, вторая — нет
- **THEN** `InsufficientStockError`, `reserved` по первой позиции не изменился, журнал не дополнен

#### Scenario: Некорректные входные данные
- **WHEN** `lines` пуст, либо `ttl` равен нулю, отрицателен или не является `timedelta`
- **THEN** `ValidationError`

#### Scenario: Повторный order_id при действующем или подтверждённом резерве
- **WHEN** у `order_id` есть резерв `ACTIVE` или `CONFIRMED`
- **THEN** `DuplicateReservationError` с атрибутом `order_id`, состояние и журнал не изменены

#### Scenario: Повторный order_id после истечения или отмены
- **WHEN** прежний резерв `order_id` истёк или отменён и вызван `reserve` с тем же `order_id`
- **THEN** создан новый резерв `ACTIVE`, `get_reservation` возвращает его (новые строки и сроки), старый полностью заменён

### Requirement: Доступный и зарезервированный остаток
`reserved(warehouse, sku)` SHALL возвращать сумму количеств по всем строкам активных (неистёкших на текущий момент) резервов для позиции. `available(warehouse, sku)` SHALL возвращать `max(0, физический остаток − reserved)`: отрицательным не бывает; это относится ко всем местам, где показывается или используется доступный остаток (в том числе `available` в `InsufficientStockError`). Запросы для незарегистрированного SKU SHALL давать `UnknownSkuError`, для зарегистрированного без остатка — 0. `on_hand` и `stock_levels` SHALL по-прежнему показывать физический остаток.

#### Scenario: Резерв уменьшает доступное, но не физическое
- **WHEN** на складе 10, зарезервировано 4
- **THEN** `on_hand == 10`, `reserved == 4`, `available == 6`

#### Scenario: Физического товара меньше резерва
- **WHEN** после резервирования инвентаризацией физический остаток стал меньше зарезервированного
- **THEN** `available == 0`, а не отрицательное число

#### Scenario: Истёкший резерв не учитывается
- **WHEN** часы сервиса достигли или перешли `expires_at` резерва
- **THEN** `reserved` не включает его, `available` его не вычитает, `get_reservation` возвращает статус `EXPIRED`, в журнал ничего не пишется

### Requirement: Подтверждение резерва
`confirm(order_id)` SHALL для активного резерва уменьшить физический остаток по каждой строке (достаточность проверяется по сумме строк одной позиции относительно физического остатка, `available` не учитывается), установить статус `CONFIRMED` и вернуть снимок. Для истёкшего резерва SHALL быть `ReservationExpiredError`; для подтверждённого или отменённого — `ReservationStateError`. Операция SHALL быть атомарной.

#### Scenario: Подтверждение при нулевом available
- **WHEN** весь остаток позиции зарезервирован под этот заказ и вызван `confirm`
- **THEN** физический остаток уменьшен, статус `CONFIRMED`, `reserved` по позиции равен 0

#### Scenario: Подтверждение резерва с дублями позиции
- **WHEN** резерв содержит две строки одной позиции
- **THEN** физический остаток уменьшается на их сумму, в журнале два `ISSUE`

#### Scenario: Подтверждение истёкшего
- **WHEN** `confirm` вызван для резерва в статусе `EXPIRED`
- **THEN** `ReservationExpiredError`, остатки и журнал не изменены

#### Scenario: Подтверждение подтверждённого или отменённого
- **WHEN** `confirm` вызван для `CONFIRMED` или `CANCELLED`
- **THEN** `ReservationStateError`

#### Scenario: Физического остатка стало меньше резерва
- **WHEN** после резервирования инвентаризацией (`adjust`) физический остаток опустился ниже суммы строк
- **THEN** `InsufficientStockError`, резерв остаётся `ACTIVE`, остатки и журнал не изменены

### Requirement: Отмена резерва
`cancel(order_id)` SHALL перевести активный резерв в `CANCELLED`, освободив товар, и вернуть снимок. Повторная отмена отменённого резерва SHALL быть идемпотентной: возвращает снимок, ничего не меняет и ничего не пишет в журнал. Отмена подтверждённого резерва SHALL давать `ReservationStateError`. Отмена истёкшего резерва SHALL ничего не менять и не писать в журнал (статус остаётся `EXPIRED`).

#### Scenario: Отмена освобождает товар
- **WHEN** отменён активный резерв
- **THEN** статус `CANCELLED`, `available` восстановлен, записан один `RESERVE_CANCEL`

#### Scenario: Повторная отмена
- **WHEN** `cancel` вызван второй раз
- **THEN** возвращён снимок `CANCELLED`, журнал не дополнен

#### Scenario: Отмена подтверждённого
- **WHEN** `cancel` вызван для `CONFIRMED`
- **THEN** `ReservationStateError`

#### Scenario: Отмена истёкшего
- **WHEN** `cancel` вызван для истёкшего резерва
- **THEN** возвращён снимок со статусом `EXPIRED`, журнал не дополнен

### Requirement: Продление резерва
`extend(order_id, ttl)` SHALL продлить активный резерв: новый срок = `now + ttl` (от текущего момента). Срок никогда не сокращается: если `now + ttl` не позже текущего `expires_at`, SHALL ничего не меняться, `RESERVE_EXTEND` не пишется, возвращается резерв как есть. `ttl` проверяется как в `reserve` (`ValidationError`), ошибки статусов — как у `confirm`. Операция SHALL вернуть снимок.

#### Scenario: Успешное продление
- **WHEN** в момент `now` активный резерв с `expires_at = E < now + 10 минут` продлён на 10 минут
- **THEN** `expires_at == now + 10 минут`, записан `RESERVE_EXTEND`

#### Scenario: Продление не сокращает срок
- **WHEN** `now + ttl` не позже текущего `expires_at`
- **THEN** `expires_at` не изменился, `RESERVE_EXTEND` не записан, возвращён тот же резерв

#### Scenario: Продление истёкшего
- **WHEN** резерв уже истёк
- **THEN** `ReservationExpiredError`, срок не меняется

#### Scenario: Некорректный ttl
- **WHEN** `ttl` не положителен
- **THEN** `ValidationError`

### Requirement: Окончательность статусов и ленивое истечение
`CONFIRMED` и `CANCELLED` SHALL быть окончательными: истечение времени их не меняет. Истечение `ACTIVE` SHALL определяться по часам сервиса в момент обращения (резерв истёк, если текущее время не меньше `expires_at`), без фоновых задач и без записи в журнал.

#### Scenario: Подтверждённый резерв после срока
- **WHEN** резерв подтверждён и затем время прошло за `expires_at`
- **THEN** `get_reservation` возвращает `CONFIRMED`

#### Scenario: Отменённый резерв после срока
- **WHEN** резерв отменён и затем время прошло за `expires_at`
- **THEN** `get_reservation` возвращает `CANCELLED`

### Requirement: Отсутствующий резерв
`confirm`, `cancel`, `extend` и `get_reservation` для неизвестного `order_id` SHALL бросать `ReservationNotFoundError`. Все ошибки резервов SHALL наследоваться от `ReservationError` (а значит, от `WarehouseError`) и иметь атрибут `order_id`.

#### Scenario: Неизвестный заказ
- **WHEN** вызван `get_reservation("NOPE")`
- **THEN** `ReservationNotFoundError` с `order_id == "NOPE"`

### Requirement: Расход не трогает чужие резервы
`issue` SHALL разрешать расход не более `available` позиции; при большем запросе — `InsufficientStockError` (`available` в ошибке — доступное, не меньше 0). То же ограничение SHALL действовать для списания со склада-источника в `transfer`. Для кода без резервов поведение остаётся прежним.

#### Scenario: Расход больше доступного
- **WHEN** на складе 10, зарезервировано 8, вызван `issue` на 3
- **THEN** `InsufficientStockError`, остаток не изменён

#### Scenario: Расход после истечения резерва
- **WHEN** резерв истёк и вызван `issue` на весь физический остаток
- **THEN** расход выполнен

### Requirement: События журнала резервов
Сервис SHALL писать в журнал: `RESERVE` на каждую строку резерва (поля `order`, `wh`, `sku`, `qty`, `expires`); при `confirm` — обычный `ISSUE` на каждую строку с `ref` = номер заказа, затем `RESERVE_CONFIRM` (`order`); `RESERVE_CANCEL` (`order`) при фактической отмене; `RESERVE_EXTEND` (`order`, `expires`) только при фактическом изменении срока. Время в `expires` SHALL записываться тем же форматом, что и время события. Операции, завершившиеся ошибкой, истечение и идемпотентная повторная отмена SHALL не писать событий.

#### Scenario: События confirm
- **WHEN** подтверждён резерв из двух строк
- **THEN** журнал дополнен двумя `ISSUE` (`ref` = order_id) в порядке строк, затем `RESERVE_CONFIRM`

#### Scenario: События reserve
- **WHEN** создан резерв из трёх строк
- **THEN** записано три `RESERVE` с одинаковыми `order` и `expires`

### Requirement: Обратная совместимость
Конструктор `Inventory` и операции `receive/issue/transfer/adjust/on_hand/stock_levels` SHALL работать как раньше для кода без резервов; формат журнала, `cli.py` и `reports.py` SHALL не изменяться.

#### Scenario: Существующие тесты
- **WHEN** запущен существующий набор тестов
- **THEN** он проходит без изменений
