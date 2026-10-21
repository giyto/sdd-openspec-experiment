## Purpose

Резервирование товара под заказы с ограниченным сроком действия (TTL), чтобы один и тот же физический товар не продавался дважды, пока заказ оформляется и оплачивается.

## ADDED Requirements

### Requirement: Создание резерва
`Inventory.reserve(order_id, lines, ttl=None)` SHALL держать товар под заказ сразу по всем строкам (строки могут относиться к разным складам) и возвращать снимок `Reservation` со статусом `ACTIVE`. Физический остаток при этом MUST NOT меняться. `created_at` — текущее время по часам сервиса, `expires_at = created_at + ttl`; при `ttl=None` используется `DEFAULT_RESERVATION_TTL` (15 минут). Строки принимаются как `tuple[str, str, int]` (склад, SKU, количество) или `ReservationLine`; `Reservation.lines` содержит их как `ReservationLine` в том же порядке, без склейки одинаковых позиций.

#### Scenario: Успешный резерв по нескольким складам
- **WHEN** есть остатки A/BOLT=5 и B/NUT=3 и вызван `reserve("SO-1", [("A","BOLT",2), ("B","NUT",3)])`
- **THEN** возвращается `Reservation` со статусом `ACTIVE`, `lines` из двух `ReservationLine` в переданном порядке, `expires_at == created_at + timedelta(minutes=15)`, а `on_hand` обеих позиций не изменился

#### Scenario: Явный TTL
- **WHEN** вызван `reserve("SO-1", lines, ttl=timedelta(minutes=5))`
- **THEN** `expires_at == created_at + timedelta(minutes=5)`

#### Scenario: Одна позиция двумя строками
- **WHEN** на позиции A/BOLT остаток 5 и вызван `reserve("SO-1", [("A","BOLT",3), ("A","BOLT",2)])`
- **THEN** резерв создаётся, `lines` содержит обе строки раздельно, `reserved("A","BOLT") == 5`

#### Scenario: Сумма строк превышает доступное
- **WHEN** на позиции A/BOLT остаток 5 и вызван `reserve("SO-1", [("A","BOLT",3), ("A","BOLT",3)])`
- **THEN** бросается `InsufficientStockError` (requested=6, available=5), резерв не создан, журнал не изменён

### Requirement: Валидация входных данных резерва
`reserve` SHALL бросать `ValidationError`, если `ttl` не является положительным `timedelta` (ноль, отрицательный, не `timedelta`) или если заказ не содержит строк. `order_id` MUST быть кодом так же, как SKU и склады (непустая строка без пробелов и `=`), иначе `ValidationError`. Количество в строке проверяется как обычно (`InvalidQuantityError`), неизвестный SKU — `UnknownSkuError`, некорректный код склада — `ValidationError`. Если не хватает товара — `InsufficientStockError`. При любой ошибке состояние сервиса и журнал MUST NOT меняться.

#### Scenario: Нулевой TTL
- **WHEN** вызван `reserve("SO-1", lines, ttl=timedelta(0))`
- **THEN** бросается `ValidationError`

#### Scenario: Пустой заказ
- **WHEN** вызван `reserve("SO-1", [])`
- **THEN** бросается `ValidationError`

#### Scenario: Некорректный номер заказа
- **WHEN** вызван `reserve("SO 1", lines)`
- **THEN** бросается `ValidationError`

#### Scenario: Одна из строк невалидна
- **WHEN** первая строка корректна, а вторая имеет `qty=0`
- **THEN** бросается `InvalidQuantityError` и первая строка не резервируется

#### Scenario: Атомарность при нехватке
- **WHEN** первая строка доступна, а по второй товара не хватает
- **THEN** бросается `InsufficientStockError`, `reserved` по первой позиции не изменился, события `RESERVE` не записаны

### Requirement: Доступный и зарезервированный остаток
`Inventory.reserved(warehouse, sku)` SHALL возвращать сумму количеств по всем строкам активных (не истёкших) резервов для позиции. `Inventory.available(warehouse, sku)` SHALL возвращать `max(0, физический остаток − reserved)`, то есть никогда не отрицательное значение. Резервировать можно только из доступного. Для незарегистрированного SKU оба метода бросают `UnknownSkuError`, для зарегистрированного без остатка возвращают 0. `on_hand` и `stock_levels` продолжают показывать физический остаток.

#### Scenario: Резерв уменьшает доступное
- **WHEN** остаток A/BOLT=5 и активный резерв на 2
- **THEN** `reserved == 2`, `available == 3`, `on_hand == 5`

#### Scenario: Инвентаризация меньше резерва
- **WHEN** активно зарезервировано 4, затем `adjust` устанавливает остаток 1
- **THEN** `available == 0` (не отрицательное), `reserved == 4`

#### Scenario: Нельзя резервировать сверх доступного
- **WHEN** остаток 5, активно зарезервировано 4, вызван `reserve` на 2 единицы
- **THEN** бросается `InsufficientStockError`

#### Scenario: Неизвестный SKU
- **WHEN** вызван `available("A", "NOPE")`
- **THEN** бросается `UnknownSkuError`

### Requirement: Истечение резерва по часам сервиса
Резерв SHALL считаться истёкшим, начиная с момента `expires_at` включительно (`now >= expires_at`): снимок имеет статус `EXPIRED`, резерв не учитывается в `available` и `reserved`. Статус вычисляется по часам сервиса в момент обращения; фоновых задач нет, само истечение в журнал MUST NOT записываться. Статусы `CONFIRMED` и `CANCELLED` окончательные и истечением не меняются.

#### Scenario: Резерв истекает ровно в expires_at
- **WHEN** резерв создан с TTL 15 минут и часы продвинуты на 15 минут
- **THEN** `get_reservation(...).status == EXPIRED`, `reserved == 0`, `available` равен физическому остатку

#### Scenario: Перед истечением резерв действует
- **WHEN** часы продвинуты на 14 минут 59 секунд
- **THEN** статус `ACTIVE`, резерв учитывается в `reserved`

#### Scenario: Истечение не пишется в журнал
- **WHEN** резерв истёк и к нему обращаются через `get_reservation`
- **THEN** количество событий журнала не изменилось

#### Scenario: Подтверждённый резерв не становится истёкшим
- **WHEN** резерв подтверждён, затем время `expires_at` прошло
- **THEN** `get_reservation(...).status == CONFIRMED`

### Requirement: Подтверждение резерва
`Inventory.confirm(order_id)` SHALL превращать активный резерв в отгрузку: физический остаток уменьшается по каждой строке, статус становится `CONFIRMED`, возвращается снимок. Нулевой `available` подтверждению не мешает, так как товар зарезервирован под этот заказ. Проверка достаточности выполняется по физическому остатку по сумме строк каждой позиции; если не хватает хотя бы по одной позиции — `InsufficientStockError`, ничего не списывается и не пишется в журнал, резерв остаётся активным. Истёкший резерв — `ReservationExpiredError`; уже подтверждённый или отменённый — `ReservationStateError`; отсутствующий — `ReservationNotFoundError`.

#### Scenario: Успешное подтверждение
- **WHEN** остаток A/BOLT=5, активный резерв на 5 (`available == 0`), вызван `confirm`
- **THEN** `on_hand == 0`, статус `CONFIRMED`

#### Scenario: Нехватка физического остатка
- **WHEN** после инвентаризации физический остаток по одной из позиций меньше суммы строк резерва
- **THEN** `confirm` бросает `InsufficientStockError`, остатки по всем строкам не изменились, статус `ACTIVE`, журнал не изменён

#### Scenario: Дублирующиеся строки при подтверждении
- **WHEN** резерв содержит A/BOLT двумя строками по 3 и 2, физический остаток 4
- **THEN** `confirm` бросает `InsufficientStockError` (requested=5, available=4) и ничего не списывается

#### Scenario: Подтверждение истёкшего
- **WHEN** резерв истёк
- **THEN** `confirm` бросает `ReservationExpiredError`

#### Scenario: Повторное подтверждение
- **WHEN** резерв уже подтверждён или отменён
- **THEN** `confirm` бросает `ReservationStateError`

### Requirement: Отмена резерва
`Inventory.cancel(order_id)` SHALL освобождать активный резерв (статус `CANCELLED`) и возвращать снимок. Отмена идемпотентна: повторная отмена и отмена истёкшего резерва ничего не меняют и ничего не пишут в журнал; истёкший резерв остаётся `EXPIRED`, отменённый — `CANCELLED`. Отмена подтверждённого резерва — `ReservationStateError`.

#### Scenario: Отмена активного
- **WHEN** отменяется активный резерв на 2 единицы
- **THEN** статус `CANCELLED`, `reserved == 0`, записано одно событие `RESERVE_CANCEL`

#### Scenario: Повторная отмена
- **WHEN** `cancel` вызывается второй раз
- **THEN** возвращается снимок со статусом `CANCELLED`, журнал не изменился

#### Scenario: Отмена истёкшего
- **WHEN** резерв истёк и вызван `cancel`
- **THEN** возвращается снимок со статусом `EXPIRED`, журнал не изменился

#### Scenario: Отмена подтверждённого
- **WHEN** резерв подтверждён и вызван `cancel`
- **THEN** бросается `ReservationStateError`

### Requirement: Продление резерва
`Inventory.extend(order_id, ttl)` SHALL продлевать активный резерв: новый срок равен `now + ttl`, где `now` — текущее время по часам сервиса (не от старого `expires_at`). Срок никогда не сокращается: если `now + ttl` не позже текущего `expires_at`, резерв не меняется и событие не пишется (возвращается текущий снимок). `ttl` проверяется как в `reserve` (положительный `timedelta`, иначе `ValidationError`); ошибки статусов те же, что у `confirm` (истёкший — `ReservationExpiredError`, подтверждённый или отменённый — `ReservationStateError`).

#### Scenario: Продление от текущего момента
- **WHEN** резерв создан в T с TTL 15 минут, в T+10 мин вызван `extend(ttl=20 минут)`
- **THEN** `expires_at == T+30 мин`, записано событие `RESERVE_EXTEND`

#### Scenario: Срок не сокращается
- **WHEN** в T+1 мин вызван `extend(ttl=5 минут)` при `expires_at == T+15 мин`
- **THEN** `expires_at` не изменился, событие не записано

#### Scenario: Новый срок равен текущему
- **WHEN** `now + ttl == expires_at`
- **THEN** резерв и журнал не изменяются

#### Scenario: Невалидный TTL
- **WHEN** вызван `extend(order_id, timedelta(0))`
- **THEN** бросается `ValidationError`

#### Scenario: Продление истёкшего
- **WHEN** резерв истёк
- **THEN** бросается `ReservationExpiredError`

### Requirement: Поиск резерва и повторный резерв по заказу
`Inventory.get_reservation(order_id)` SHALL возвращать снимок со статусом на текущий момент. Если резерва по `order_id` нет, `confirm`, `cancel`, `extend` и `get_reservation` бросают `ReservationNotFoundError`. Повторный `reserve` на тот же `order_id` SHALL бросать `DuplicateReservationError`, если существующий резерв активен или подтверждён; если прежний резерв истёк или отменён, новый `reserve` разрешён и полностью заменяет старый. Все ошибки резервов (`ReservationError` и наследники) имеют атрибут `order_id`.

#### Scenario: Неизвестный заказ
- **WHEN** вызван `get_reservation("SO-404")`
- **THEN** бросается `ReservationNotFoundError` с `order_id == "SO-404"`

#### Scenario: Дубликат активного
- **WHEN** повторно вызван `reserve` для заказа с активным резервом
- **THEN** бросается `DuplicateReservationError`, прежний резерв не изменён

#### Scenario: Дубликат подтверждённого
- **WHEN** повторно вызван `reserve` для подтверждённого заказа
- **THEN** бросается `DuplicateReservationError`

#### Scenario: Замена истёкшего или отменённого
- **WHEN** резерв заказа истёк (или отменён) и вызван `reserve` с другими строками
- **THEN** создаётся новый резерв, `get_reservation` возвращает только новые строки и новые `created_at`/`expires_at`

### Requirement: Расход не забирает чужие резервы
`issue` SHALL учитывать активные резервы: если запрошенное количество больше `available`, бросается `InsufficientStockError` (в поле `available` — доступное количество), остатки и журнал не меняются. Это же ограничение действует для источника в `transfer`. Для кода без резервов поведение `receive/issue/transfer/adjust/on_hand/stock_levels` и конструктора не меняется; `adjust` — факт инвентаризации и резервами не ограничивается. Подтверждение резерва списывает товар в обход этого ограничения для собственного резерва.

#### Scenario: Расход больше доступного
- **WHEN** остаток 5, активно зарезервировано 4, вызван `issue(..., 2)`
- **THEN** бросается `InsufficientStockError`, `on_hand == 5`

#### Scenario: Расход в пределах доступного
- **WHEN** остаток 5, активно зарезервировано 4, вызван `issue(..., 1)`
- **THEN** расход проходит, `on_hand == 4`

#### Scenario: Истёкший резерв не мешает расходу
- **WHEN** резерв истёк и вызван `issue` на весь физический остаток
- **THEN** расход проходит

#### Scenario: Старое поведение без резервов
- **WHEN** резервов нет
- **THEN** `issue` бросает `InsufficientStockError` только если qty больше физического остатка

### Requirement: События журнала резервов
Операции с резервами SHALL писать события в существующем формате журнала. `reserve` — по одному `RESERVE` на каждую строку (в порядке строк) с полями `order`, `wh`, `sku`, `qty`, `expires`. `confirm` — обычный `ISSUE` на каждую строку с `ref` = номер заказа (в порядке строк), затем `RESERVE_CONFIRM` с `order`. `cancel` активного резерва — `RESERVE_CANCEL` с `order`. `extend` при реальном продлении — `RESERVE_EXTEND` с `order` и `expires`. Значение `expires` пишется тем же форматом времени, что и время события. Операции, которые ничего не меняют (идемпотентная отмена, продление без увеличения срока, истечение), событий не пишут; неуспешные операции не пишут ничего.

#### Scenario: События reserve
- **WHEN** резерв создан на две строки
- **THEN** в журнал добавлены два `RESERVE` с `order`, `wh`, `sku`, `qty` и `expires` в формате `YYYY-MM-DDTHH:MM:SSZ`

#### Scenario: События confirm
- **WHEN** подтверждён резерв из двух строк
- **THEN** добавлены два `ISSUE` с `ref=<order_id>`, затем один `RESERVE_CONFIRM`

#### Scenario: События extend
- **WHEN** срок реально увеличен
- **THEN** добавлено одно `RESERVE_EXTEND` с `order` и новым `expires`
