# stock-reservations Specification

## Purpose
Резервирование товара под заказы с ограниченным по времени сроком действия, чтобы один и тот же товар не продавался дважды между оформлением и отгрузкой заказа.

## Requirements

### Requirement: Модель резерва и публичный API
Система SHALL предоставлять в `warehouse/models.py` `ReservationStatus(str, Enum)` со значениями `ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`, а также frozen-датаклассы `ReservationLine(warehouse, sku, qty)` и `Reservation(order_id, lines, created_at, expires_at, status)`, где `lines` — `tuple[ReservationLine, ...]`. В `warehouse/errors.py` SHALL быть `ReservationError(WarehouseError)` и его наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у каждого есть атрибут `order_id`. В `warehouse/reservations.py` SHALL быть `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)`. `Inventory` SHALL получить методы `reserve(order_id, lines, ttl=None)`, `confirm(order_id)`, `cancel(order_id)`, `extend(order_id, ttl)`, `get_reservation(order_id)`, `available(warehouse, sku)`, `reserved(warehouse, sku)`. Методы `reserve`, `confirm`, `cancel`, `extend`, `get_reservation` SHALL возвращать снимок `Reservation` со статусом на текущий момент по часам сервиса.

#### Scenario: Значения статусов
- **WHEN** читаются значения `ReservationStatus`
- **THEN** они равны строкам `"active"`, `"expired"`, `"confirmed"`, `"cancelled"`, и члены enum сравниваются равными этим строкам

#### Scenario: TTL по умолчанию
- **WHEN** читается `DEFAULT_RESERVATION_TTL`
- **THEN** он равен `timedelta(minutes=15)`

#### Scenario: Ошибки несут order_id
- **WHEN** любая из ошибок резервов возникает для заказа `SO-1`
- **THEN** её атрибут `order_id` равен `"SO-1"`, и она является `ReservationError` и `WarehouseError`

### Requirement: Создание резерва
`reserve` SHALL удерживать товар под заказ сразу по всем строкам (строки могут относиться к разным складам и могут быть кортежами `(warehouse, sku, qty)` или `ReservationLine`). Физический остаток SHALL не меняться. `created_at` SHALL быть текущим временем часов сервиса, `expires_at = created_at + ttl`; при `ttl=None` используется `DEFAULT_RESERVATION_TTL`. Строки в снимке SHALL храниться в том порядке и в том виде, как переданы, без склеивания одинаковых позиций. Наличие SHALL проверяться по сумме строк каждой позиции (склад + SKU). Операция SHALL быть атомарной: при любой ошибке ни резервы, ни журнал не меняются.

#### Scenario: Успешное резервирование на нескольких складах
- **WHEN** на складах `A` и `B` есть товар и вызывается `reserve("SO-1", [("A","BOLT",2), ("B","NUT",1)])` в момент `T`
- **THEN** возвращается `Reservation` со статусом `ACTIVE`, `created_at == T`, `expires_at == T + 15 минут`, `lines` в переданном порядке, а `on_hand` обеих позиций не изменился

#### Scenario: Явный TTL и ReservationLine
- **WHEN** вызывается `reserve("SO-1", [ReservationLine("A","BOLT",1)], ttl=timedelta(hours=1))`
- **THEN** `expires_at == created_at + 1 час`

#### Scenario: Повторяющаяся позиция хранится как пришла
- **WHEN** передано две строки `("A","BOLT",2)` и `("A","BOLT",3)`
- **THEN** в снимке остаются две отдельные строки, а `reserved("A","BOLT")` равен 5

#### Scenario: Недостаточно товара
- **WHEN** хотя бы по одной позиции запрошено больше, чем `available` (две строки одной позиции проверяются по их сумме)
- **THEN** бросается `InsufficientStockError`, ни одна строка не резервируется, в журнал ничего не пишется

#### Scenario: Некорректный ttl
- **WHEN** `ttl` равен `timedelta(0)`, отрицательному `timedelta` или не является `timedelta`
- **THEN** бросается `ValidationError`

#### Scenario: Заказ без строк
- **WHEN** вызывается `reserve("SO-1", [])`
- **THEN** бросается `ValidationError`

#### Scenario: Некорректные данные
- **WHEN** `order_id` или склад не являются кодом (пустой, с пробелами или `=`), либо строка не является кортежем из трёх элементов или `ReservationLine`
- **THEN** бросается `ValidationError`; для некорректного количества (не положительный `int`, включая `bool`) — `InvalidQuantityError`; для незарегистрированного SKU — `UnknownSkuError`

### Requirement: Доступное и зарезервированное количество
`reserved(warehouse, sku)` SHALL возвращать сумму количеств по всем строкам активных (не истёкших) резервов для позиции. `available(warehouse, sku)` SHALL возвращать физический остаток минус `reserved`, но не менее 0. Для незарегистрированного SKU оба метода SHALL бросать `UnknownSkuError`; для зарегистрированного SKU без остатка и резервов — возвращать 0. Резервировать SHALL быть можно только из `available`. `on_hand` и `stock_levels` SHALL показывать физический остаток независимо от резервов.

#### Scenario: Расчёт по позиции
- **WHEN** на складе 10 единиц и активный резерв на 4
- **THEN** `reserved == 4`, `available == 6`, `on_hand == 10`

#### Scenario: Резерв не больше доступного
- **WHEN** на складе 10 единиц, активно 4 в резерве, и запрашивается резерв на 7
- **THEN** бросается `InsufficientStockError` (запрошено 7, доступно 6)

#### Scenario: Инвентаризация меньше резервов
- **WHEN** после резерва на 8 единиц `adjust` фиксирует остаток 5
- **THEN** `available` равен 0 (не отрицательный), `reserved` равен 8

#### Scenario: Неизвестный SKU
- **WHEN** вызывается `available("A","NOPE")` или `reserved("A","NOPE")` для незарегистрированного SKU
- **THEN** бросается `UnknownSkuError`

### Requirement: Истечение резерва по часам сервиса
Резерв SHALL считаться истёкшим, как только текущее время часов сервиса достигает `expires_at` (`now >= expires_at`). Истёкший резерв SHALL иметь статус `EXPIRED` и не учитываться в `available` и `reserved`. Истечение определяется в момент обращения, без фоновых задач, и SHALL не порождать событий журнала. Статусы `CONFIRMED` и `CANCELLED` окончательные: истечение времени их не меняет.

#### Scenario: Граница срока
- **WHEN** часы стоят ровно на `expires_at`
- **THEN** `get_reservation` возвращает статус `EXPIRED`, а товар снова входит в `available`

#### Scenario: Незадолго до срока
- **WHEN** до `expires_at` осталась меньше секунды
- **THEN** статус `ACTIVE`, товар остаётся зарезервированным

#### Scenario: Истечение не пишется в журнал
- **WHEN** срок резерва прошёл и вызывается `get_reservation`
- **THEN** число событий журнала не изменилось

#### Scenario: Подтверждённый и отменённый не истекают
- **WHEN** время проходит `expires_at` у подтверждённого или отменённого резерва
- **THEN** статус остаётся `CONFIRMED` или `CANCELLED` соответственно

### Requirement: Повторный reserve по тому же заказу
`reserve` на `order_id`, у которого есть активный или подтверждённый резерв, SHALL бросать `DuplicateReservationError`. Если прежний резерв истёк или отменён, новый `reserve` SHALL быть разрешён и полностью заменять прежний (строки, сроки, статус).

#### Scenario: Дубликат активного
- **WHEN** повторно вызывается `reserve` для заказа с активным резервом
- **THEN** бросается `DuplicateReservationError`, прежний резерв не меняется

#### Scenario: Дубликат подтверждённого
- **WHEN** повторно вызывается `reserve` для подтверждённого заказа
- **THEN** бросается `DuplicateReservationError`

#### Scenario: Замена истёкшего или отменённого
- **WHEN** прежний резерв заказа истёк или отменён и вызывается `reserve` с другими строками
- **THEN** `get_reservation` возвращает новый резерв со статусом `ACTIVE` и новыми строками

#### Scenario: Замена не проходит проверку остатка
- **WHEN** замещающий `reserve` падает с `InsufficientStockError`
- **THEN** прежний (истёкший или отменённый) резерв остаётся без изменений

### Requirement: Подтверждение резерва
`confirm` SHALL превращать активный резерв в отгрузку: физический остаток уменьшается по каждой строке, статус становится `CONFIRMED`. Достаточность SHALL проверяться по физическому остатку на сумму строк каждой позиции, а нулевой `available` подтверждению не мешает. Если физического остатка не хватает хотя бы по одной позиции, SHALL бросаться `InsufficientStockError`, ничего не списываться и не записываться в журнал, резерв остаётся активным. Для истёкшего резерва SHALL бросаться `ReservationExpiredError`, для подтверждённого или отменённого — `ReservationStateError`.

#### Scenario: Успешное подтверждение
- **WHEN** подтверждается активный резерв на 3 единицы при остатке 3 (и `available == 0` из-за этого же резерва)
- **THEN** остаток становится 0, статус `CONFIRMED`, `reserved` не включает этот резерв

#### Scenario: Две строки одной позиции
- **WHEN** резерв содержит строки `("A","BOLT",2)` и `("A","BOLT",3)`, а физический остаток 4
- **THEN** `confirm` бросает `InsufficientStockError` (требуется 5), остаток 4, резерв `ACTIVE`, журнал без новых событий

#### Scenario: Остаток уменьшился по одной из позиций
- **WHEN** после `adjust` физического остатка не хватает по одной из нескольких позиций
- **THEN** `InsufficientStockError`, остальные позиции не списаны

#### Scenario: Истёкший резерв
- **WHEN** подтверждается истёкший резерв
- **THEN** бросается `ReservationExpiredError`

#### Scenario: Повторное подтверждение и подтверждение отменённого
- **WHEN** подтверждается уже подтверждённый или отменённый резерв
- **THEN** бросается `ReservationStateError`

### Requirement: Отмена резерва
`cancel` SHALL освобождать активный резерв и переводить его в `CANCELLED`. Отмена SHALL быть идемпотентной: повторная отмена и отмена истёкшего резерва ничего не меняют и ничего не пишут в журнал, истёкший резерв остаётся `EXPIRED`, и `cancel` возвращает его снимок. Подтверждённый резерв отменить SHALL быть нельзя — `ReservationStateError`.

#### Scenario: Отмена активного
- **WHEN** отменяется активный резерв
- **THEN** статус `CANCELLED`, товар возвращается в `available`

#### Scenario: Повторная отмена
- **WHEN** отменяется уже отменённый резерв
- **THEN** возвращается снимок `CANCELLED`, журнал не изменился

#### Scenario: Отмена истёкшего
- **WHEN** отменяется истёкший резерв
- **THEN** возвращается снимок со статусом `EXPIRED`, журнал не изменился

#### Scenario: Отмена подтверждённого
- **WHEN** отменяется подтверждённый резерв
- **THEN** бросается `ReservationStateError`

### Requirement: Продление резерва
`extend(order_id, ttl)` SHALL проверять `ttl` так же, как `reserve` (положительный `timedelta`, иначе `ValidationError`), а ошибки статусов SHALL быть такими же, как у `confirm` (истёкший — `ReservationExpiredError`, подтверждённый или отменённый — `ReservationStateError`). Для активного резерва новый срок равен `now + ttl`, где `now` — текущее время часов сервиса (а не старый `expires_at`). Срок SHALL никогда не сокращаться: если `now + ttl` не позже текущего `expires_at`, резерв и журнал не меняются.

#### Scenario: Продление
- **WHEN** резерв активен с `expires_at = T+15м`, часы на `T+5м`, вызывается `extend(order, 30 минут)`
- **THEN** `expires_at == T+35м`, пишется `RESERVE_EXTEND`

#### Scenario: Попытка сократить срок
- **WHEN** `now + ttl` не позже текущего `expires_at`
- **THEN** `expires_at` не меняется, событие не пишется, возвращается актуальный снимок

#### Scenario: Некорректный ttl
- **WHEN** `ttl` не положительный `timedelta`
- **THEN** бросается `ValidationError`

#### Scenario: Недопустимый статус
- **WHEN** продлевается истёкший, подтверждённый или отменённый резерв
- **THEN** бросается `ReservationExpiredError` для истёкшего и `ReservationStateError` для остальных

### Requirement: Отсутствующий резерв
Если резерва по `order_id` нет, `confirm`, `cancel`, `extend` и `get_reservation` SHALL бросать `ReservationNotFoundError`.

#### Scenario: Неизвестный заказ
- **WHEN** любой из четырёх методов вызван для заказа без резерва
- **THEN** бросается `ReservationNotFoundError` с этим `order_id`

### Requirement: Защита резервов от расхода
`issue` SHALL не забирать товар из активных резервов: если запрошено больше `available`, SHALL бросаться `InsufficientStockError` (с `available` в качестве доступного количества). `transfer` как расход со склада-источника SHALL подчиняться тому же ограничению. Для кода без резервов `receive`, `issue`, `transfer`, `adjust`, `on_hand`, `stock_levels` и конструктор `Inventory` SHALL работать как раньше.

#### Scenario: Issue чужого резерва
- **WHEN** остаток 10, активно в резерве 8, и вызывается `issue` на 3
- **THEN** бросается `InsufficientStockError`, остаток 10

#### Scenario: Issue в пределах доступного
- **WHEN** остаток 10, в резерве 8, `issue` на 2
- **THEN** остаток 8, резерв не затронут

#### Scenario: Issue после истечения резерва
- **WHEN** резерв истёк
- **THEN** `issue` может забрать и ранее зарезервированное количество

#### Scenario: Transfer из резерва
- **WHEN** `transfer` просит больше `available` на складе-источнике
- **THEN** бросается `InsufficientStockError`

### Requirement: События журнала
Операции с резервами SHALL писать в журнал события в существующем формате: `RESERVE` на каждую строку с полями `order`, `wh`, `sku`, `qty`, `expires`; при `confirm` — обычный `ISSUE` на каждую строку (с `ref` = номер заказа) в порядке строк, затем `RESERVE_CONFIRM` с полем `order`; `RESERVE_CANCEL` с полем `order` при фактической отмене; `RESERVE_EXTEND` с полями `order`, `expires` при фактическом продлении. Поле `expires` SHALL записываться форматом времени журнала. Неуспешные операции, идемпотентные повторы и истечение событий не пишут.

#### Scenario: Журнал reserve
- **WHEN** выполняется `reserve` с двумя строками
- **THEN** в журнал добавляются два события `RESERVE` в порядке строк, каждое с `order`, `wh`, `sku`, `qty`, `expires`

#### Scenario: Журнал confirm
- **WHEN** подтверждается резерв с двумя строками
- **THEN** добавляются два `ISSUE` с `ref` = номеру заказа, затем `RESERVE_CONFIRM` с `order`

#### Scenario: Журнал cancel и extend
- **WHEN** фактически отменяется или продлевается резерв
- **THEN** пишется `RESERVE_CANCEL` (`order`) или `RESERVE_EXTEND` (`order`, `expires`)
