## Purpose

Резервирование товара под заказы с ограниченным временем жизни: позволяет не продавать один и тот же товар дважды, пока заказ оформляется и оплачивается, и сам освобождает неоплаченный товар по истечении TTL.

## ADDED Requirements

### Requirement: Модели и ошибки резервирования
Система SHALL предоставлять `ReservationStatus` (`ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`, наследник `str` и `Enum`), неизменяемые `ReservationLine(warehouse, sku, qty)` и `Reservation(order_id, lines, created_at, expires_at, status)` (`lines` — `tuple[ReservationLine, ...]`) в `warehouse/models.py`. Система SHALL предоставлять в `warehouse/errors.py` `ReservationError(WarehouseError)` и наследников `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у каждого атрибут `order_id`. Модуль `warehouse/reservations.py` SHALL содержать `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)`. `Reservation` SHALL быть снимком со статусом на момент вызова; последующие изменения состояния снимок не меняют.

#### Scenario: TTL по умолчанию
- **WHEN** вызывается `reserve("SO-1", lines)` без `ttl` в момент T
- **THEN** `expires_at == T + timedelta(minutes=15)` и `created_at == T`

#### Scenario: Ошибки несут order_id
- **WHEN** любая из ошибок резервирования возникает для заказа `SO-9`
- **THEN** у исключения `order_id == "SO-9"` и оно перехватывается как `ReservationError` и как `WarehouseError`

### Requirement: Создание резерва
`Inventory.reserve(order_id, lines, ttl=None)` SHALL создавать резерв сразу по всем строкам (склады могут различаться), не меняя физический остаток, и возвращать `Reservation` со статусом `ACTIVE`, `created_at` = текущее время часов сервиса, `expires_at = created_at + ttl`. `lines` — итерируемое из `(warehouse, sku, qty)` или `ReservationLine`; `Reservation.lines` SHALL содержать строки в том же порядке, в каком переданы, без склейки одинаковых позиций. `order_id`, склады и SKU SHALL проверяться как коды (непустая строка без пробелов и `=`), `qty` — как обычное количество (положительный `int`, иначе `InvalidQuantityError`); незарегистрированный SKU — `UnknownSkuError`. `ttl` SHALL быть `timedelta` больше нуля, иначе `ValidationError`; пустой набор строк — `ValidationError`. Если `order_id` уже имеет резерв в любом статусе — `DuplicateReservationError`. Если для какой-либо позиции (склад + SKU) сумма `qty` всех её строк превышает `available`, SHALL быть выброшена `InsufficientStockError`. При любой ошибке состояние и журнал SHALL остаться неизменными.

#### Scenario: Резерв по нескольким складам
- **WHEN** на складах `MAIN` и `EAST` есть `BOLT-M8` и вызывается `reserve("SO-1", [("MAIN","BOLT-M8",2), ("EAST","BOLT-M8",3)])`
- **THEN** возвращается `ACTIVE`-резерв с двумя строками в том же порядке, `on_hand` не изменился, `reserved` равен 2 и 3 соответственно

#### Scenario: Одна позиция двумя строками
- **WHEN** на `MAIN` доступно 5 `BOLT-M8` и вызывается `reserve` со строками `("MAIN","BOLT-M8",3)` и `("MAIN","BOLT-M8",3)`
- **THEN** выбрасывается `InsufficientStockError` (требуется 6, доступно 5) и ничего не меняется

#### Scenario: Дубли строк в пределах доступного
- **WHEN** на `MAIN` доступно 5 `BOLT-M8` и вызывается `reserve` со строками `("MAIN","BOLT-M8",2)` и `("MAIN","BOLT-M8",3)`
- **THEN** резерв создаётся, `Reservation.lines` содержит обе строки отдельно, `reserved == 5`

#### Scenario: Нехватка на одной из строк
- **WHEN** по первой строке товара хватает, по второй нет
- **THEN** выбрасывается `InsufficientStockError`, резерв не создаётся, журнал не изменился

#### Scenario: Некорректные входные данные
- **WHEN** `lines` пуст, либо `ttl` равен нулю, отрицателен или не является `timedelta`, либо `order_id` содержит пробел
- **THEN** выбрасывается `ValidationError`

#### Scenario: Повторный order_id
- **WHEN** `reserve` вызывается с `order_id`, по которому уже есть резерв (активный, истёкший, подтверждённый или отменённый)
- **THEN** выбрасывается `DuplicateReservationError`

#### Scenario: Резервировать можно только из доступного
- **WHEN** физически 10, активным резервом занято 8, и запрашивается резерв 3
- **THEN** выбрасывается `InsufficientStockError` с `available == 2`

### Requirement: Доступное и зарезервированное количество
`Inventory.reserved(warehouse, sku)` SHALL возвращать сумму `qty` по всем строкам активных (не истёкших на момент вызова) резервов для позиции. `Inventory.available(warehouse, sku)` SHALL возвращать физический остаток минус `reserved`, но не меньше 0. Для незарегистрированного SKU оба метода SHALL бросать `UnknownSkuError`; для зарегистрированного SKU без остатка — возвращать 0. `on_hand` и `stock_levels` SHALL по-прежнему показывать физический остаток.

#### Scenario: Резерв уменьшает доступное, но не физическое
- **WHEN** на складе 10 единиц и создан резерв на 4
- **THEN** `on_hand == 10`, `reserved == 4`, `available == 6`

#### Scenario: Истёкший резерв не учитывается
- **WHEN** резерв создан с TTL 15 минут и часы дошли до `expires_at` или прошли его
- **THEN** `reserved == 0`, `available` равен физическому остатку, `get_reservation(...).status == EXPIRED`, а в журнал ничего не добавилось

#### Scenario: Инвентаризация ниже резервов
- **WHEN** резерв на 4, затем `adjust` фиксирует остаток 3
- **THEN** `available == 0`

### Requirement: Подтверждение резерва
`Inventory.confirm(order_id)` SHALL превращать активный резерв в отгрузку: физический остаток уменьшается по каждой строке, статус становится `CONFIRMED`, возвращается снимок. Нулевой `available` подтверждению не мешает, поскольку товар зарезервирован под этот заказ; подтверждению мешает только нехватка физического остатка: если для какой-либо позиции физический остаток меньше суммы `qty` её строк (строки одной позиции суммируются), SHALL быть выброшена `InsufficientStockError`. Истёкший резерв — `ReservationExpiredError`; `CONFIRMED` или `CANCELLED` — `ReservationStateError`; отсутствующий — `ReservationNotFoundError`. При любой ошибке остатки, статус и журнал SHALL остаться неизменными.

#### Scenario: Успешное подтверждение
- **WHEN** активный резерв на 2 `BOLT-M8` при остатке 2 подтверждается
- **THEN** `on_hand == 0`, `reserved == 0`, статус `CONFIRMED`, хотя `available` перед этим был 0

#### Scenario: Дубли позиции при подтверждении
- **WHEN** резерв содержит две строки одной позиции по 2 и 3, а физический остаток после инвентаризации равен 4
- **THEN** `confirm` бросает `InsufficientStockError`, остатки и журнал не меняются

#### Scenario: Истёкший резерв
- **WHEN** подтверждается истёкший резерв
- **THEN** выбрасывается `ReservationExpiredError`

#### Scenario: Окончательный статус
- **WHEN** `confirm` вызывается повторно для подтверждённого или для отменённого резерва
- **THEN** выбрасывается `ReservationStateError`

### Requirement: Отмена резерва
`Inventory.cancel(order_id)` SHALL освобождать активный резерв (статус `CANCELLED`) и возвращать снимок. Отмена SHALL быть идемпотентной: повторная отмена `CANCELLED` не меняет состояние, не пишет в журнал и возвращает снимок. Отмена `CONFIRMED` — `ReservationStateError`. Отмена истёкшего резерва не является ошибкой: статус остаётся `EXPIRED`, журнал не пишется. Отсутствующий резерв — `ReservationNotFoundError`.

#### Scenario: Отмена возвращает товар в доступное
- **WHEN** активный резерв на 4 отменяется
- **THEN** статус `CANCELLED`, `reserved == 0`, `available` равен физическому остатку

#### Scenario: Повторная отмена
- **WHEN** `cancel` вызывается второй раз для того же заказа
- **THEN** исключения нет, статус `CANCELLED`, число событий в журнале не изменилось

#### Scenario: Отмена подтверждённого
- **WHEN** отменяется `CONFIRMED` резерв
- **THEN** выбрасывается `ReservationStateError`

#### Scenario: Отмена истёкшего
- **WHEN** отменяется истёкший резерв
- **THEN** исключения нет, статус `EXPIRED`, журнал не изменился

### Requirement: Продление резерва
`Inventory.extend(order_id, ttl)` SHALL продлевать активный резерв, устанавливая срок от момента запроса: `новый срок = now + ttl`, и возвращать снимок. Срок SHALL никогда не сокращаться: если `now + ttl` не позже текущего `expires_at`, резерв остаётся без изменений, `RESERVE_EXTEND` не пишется, возвращается снимок как есть. `ttl` проверяется как в `reserve` (положительный `timedelta`, иначе `ValidationError`). Ошибки по статусам такие же, как у `confirm`: истёкший — `ReservationExpiredError`, `CONFIRMED`/`CANCELLED` — `ReservationStateError`, отсутствующий — `ReservationNotFoundError`.

#### Scenario: Успешное продление от момента запроса
- **WHEN** резерв с `expires_at = T+15m` продлевается на 20 минут в момент T+5m
- **THEN** `expires_at == T+25m` (`now + ttl`), статус `ACTIVE`, записан `RESERVE_EXTEND`

#### Scenario: Срок не сокращается
- **WHEN** резерв с `expires_at = T+15m` продлевается на 10 минут в момент T+5m
- **THEN** `expires_at` остаётся `T+15m`, `RESERVE_EXTEND` не пишется, возвращается резерв как есть

#### Scenario: Продление истёкшего
- **WHEN** `extend` вызывается после `expires_at`
- **THEN** выбрасывается `ReservationExpiredError`, резерв остаётся `EXPIRED`

### Requirement: Получение резерва и окончательные статусы
`Inventory.get_reservation(order_id)` SHALL возвращать снимок со статусом на текущий момент по часам сервиса. Активный резерв с `now >= expires_at` SHALL иметь статус `EXPIRED`. Статусы `CONFIRMED` и `CANCELLED` SHALL быть окончательными: истечение времени их не меняет. Для `confirm`, `cancel`, `extend`, `get_reservation` с отсутствующим `order_id` SHALL выбрасываться `ReservationNotFoundError`.

#### Scenario: Подтверждённый заказ после времени резерва
- **WHEN** резерв подтверждён, затем часы уходят за `expires_at`
- **THEN** `get_reservation(...).status == CONFIRMED`

#### Scenario: Неизвестный заказ
- **WHEN** любой из четырёх методов вызван с неизвестным `order_id`
- **THEN** выбрасывается `ReservationNotFoundError` с этим `order_id`

### Requirement: Расход не забирает чужие резервы
`Inventory.issue` SHALL разрешать расход не больше `available`; при большем запросе — `InsufficientStockError`, где `available` отражает доступное (за вычетом активных резервов). Это же ограничение SHALL действовать для склада-источника в `transfer` (его проверки совпадают с `issue`). `adjust` как фиксация факта проверок достаточности не получает. Для кода без активных резервов поведение `receive`, `issue`, `transfer`, `adjust`, `on_hand`, `stock_levels` SHALL остаться прежним. Расход, выполняемый внутри `confirm`, этому ограничению не подчиняется.

#### Scenario: Расход из зарезервированного
- **WHEN** физически 10, резерв 8, и вызывается `issue(..., 3)`
- **THEN** `InsufficientStockError`, остаток 10

#### Scenario: Расход в пределах доступного
- **WHEN** физически 10, резерв 8, и вызывается `issue(..., 2)`
- **THEN** расход проходит

#### Scenario: Расход после истечения резерва
- **WHEN** резерв истёк и вызывается `issue` на весь физический остаток
- **THEN** расход проходит

#### Scenario: Перемещение резерва
- **WHEN** `transfer` просит больше `available` склада-источника
- **THEN** выбрасывается `InsufficientStockError`

### Requirement: События журнала резервирования
Каждая успешная операция SHALL писать события в `EventLog` в существующем формате строки: `reserve` — `RESERVE` на каждую строку в порядке строк с полями `order`, `wh`, `sku`, `qty`, `expires`; `confirm` — `ISSUE` на каждую строку (поля как у обычного расхода, `ref` = номер заказа), затем `RESERVE_CONFIRM` с полем `order`; `cancel` активного резерва — `RESERVE_CANCEL` с `order`; `extend`, реально изменивший срок, — `RESERVE_EXTEND` с `order` и `expires` (новое значение). Значение `expires` SHALL быть записано тем же форматом, что время события. Истечение, повторная отмена, отмена истёкшего, `extend` без изменения срока и любые неуспешные операции SHALL не писать событий.

#### Scenario: События confirm
- **WHEN** резерв из двух строк подтверждается
- **THEN** в журнале появляются два `ISSUE` с `ref=<order_id>` и затем один `RESERVE_CONFIRM order=<order_id>`

#### Scenario: Формат expires
- **WHEN** создан резерв с `expires_at = 2026-03-01T10:15:00Z`
- **THEN** каждое событие `RESERVE` содержит `expires=2026-03-01T10:15:00Z`
