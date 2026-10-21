## Purpose

Резервирование товара под заказы с ограниченным по времени сроком действия, чтобы один и тот же физический остаток не продавался дважды между оформлением и отгрузкой заказа.

## ADDED Requirements

### Requirement: Создание резерва
`Inventory.reserve(order_id, lines, ttl=None)` SHALL атомарно зарезервировать товар под заказ сразу по всем строкам (строки могут относиться к разным складам) и вернуть снимок `Reservation` со статусом `ACTIVE`. Физический остаток (`on_hand`, `stock_levels`) MUST NOT меняться. `created_at` MUST быть текущим временем часов сервиса, `expires_at = created_at + ttl`. При `ttl=None` MUST использоваться `DEFAULT_RESERVATION_TTL` (15 минут). Строки принимаются как кортежи `(warehouse, sku, qty)` или `ReservationLine`; `Reservation.lines` MUST хранить их в том же порядке, как переданы, без склейки одинаковых позиций.

#### Scenario: Успешное резервирование по нескольким складам
- **WHEN** на складах A и B есть достаточный остаток и вызывается `reserve("SO-1", [("A","X",2), ("B","Y",3)])`
- **THEN** возвращается `Reservation` со статусом `ACTIVE`, двумя строками в исходном порядке, `expires_at == created_at + DEFAULT_RESERVATION_TTL`, а `on_hand` на обоих складах не изменился

#### Scenario: TTL по умолчанию — 15 минут
- **WHEN** `reserve` вызван без `ttl`
- **THEN** `expires_at - created_at == timedelta(minutes=15)` и `DEFAULT_RESERVATION_TTL == timedelta(minutes=15)`

#### Scenario: Явный TTL
- **WHEN** `reserve("SO-1", lines, ttl=timedelta(hours=1))`
- **THEN** `expires_at == created_at + timedelta(hours=1)`

#### Scenario: Одинаковая позиция двумя строками
- **WHEN** вызывается `reserve("SO-1", [("A","X",2), ("A","X",3)])` при `available("A","X") == 5`
- **THEN** резерв создаётся, `lines` содержит обе строки как переданы, `reserved("A","X") == 5`

#### Scenario: Сумма дублирующихся строк превышает доступное
- **WHEN** `available("A","X") == 4` и вызывается `reserve("SO-1", [("A","X",2), ("A","X",3)])`
- **THEN** бросается `InsufficientStockError` (requested=5, available=4), ничего не создаётся и в журнал ничего не пишется

### Requirement: Валидация входных данных резерва
`reserve` MUST проверить все входные данные до любых изменений. `ttl` MUST быть положительным `timedelta`, иначе `ValidationError`; пустой список строк — `ValidationError`; `order_id` MUST быть кодом по тем же правилам, что SKU и склады (непустая строка без пробелов и `=`), иначе `ValidationError`. Количество в строке MUST быть целым положительным `int` (иначе `InvalidQuantityError`), склад — корректным кодом, SKU — зарегистрированным (иначе `UnknownSkuError`). Строка, не являющаяся ни трёхэлементным кортежем, ни `ReservationLine`, — `ValidationError`. Те же правила `ttl` MUST действовать в `extend`.

#### Scenario: Нулевой или отрицательный TTL
- **WHEN** `reserve("SO-1", lines, ttl=timedelta(0))` или с отрицательным `ttl`
- **THEN** бросается `ValidationError`, состояние и журнал не меняются

#### Scenario: Заказ без строк
- **WHEN** `reserve("SO-1", [])`
- **THEN** бросается `ValidationError`

#### Scenario: Некорректный номер заказа
- **WHEN** `order_id` содержит пробел или пуст
- **THEN** бросается `ValidationError`

#### Scenario: Некорректное количество
- **WHEN** в строке `qty` равно `0`, `True`, `1.5` или `"2"`
- **THEN** бросается `InvalidQuantityError`

#### Scenario: Неизвестный SKU
- **WHEN** строка ссылается на незарегистрированный SKU
- **THEN** бросается `UnknownSkuError`

### Requirement: Уникальность номера заказа
Для одного `order_id` в каждый момент MUST существовать не более одного действующего или подтверждённого резерва. Если на заказ уже есть резерв со статусом `ACTIVE` или `CONFIRMED`, повторный `reserve` MUST бросать `DuplicateReservationError` («на заказ уже есть резерв», атрибут `order_id`), не меняя состояние. Если прежний резерв имеет статус `EXPIRED` или `CANCELLED`, новый `reserve` MUST быть разрешён и полностью заменять старый резерв (строки, `created_at`, `expires_at`, статус `ACTIVE`).

#### Scenario: Повторный reserve для активного заказа
- **WHEN** `reserve("SO-1", ...)` вызван второй раз при активном резерве `SO-1`
- **THEN** бросается `DuplicateReservationError` и первый резерв не изменён

#### Scenario: Повторный reserve для подтверждённого заказа
- **WHEN** резерв `SO-1` подтверждён, и снова вызывается `reserve("SO-1", ...)`
- **THEN** бросается `DuplicateReservationError`, состояние и журнал не меняются

#### Scenario: Повторный reserve для отменённого или истёкшего заказа
- **WHEN** резерв `SO-1` отменён или истёк, и снова вызывается `reserve("SO-1", other_lines)`
- **THEN** создаётся новый резерв `ACTIVE`, который полностью заменяет старый: `get_reservation("SO-1")` возвращает новые строки и сроки, `reserved` считает только новые строки

### Requirement: Доступное и зарезервированное количество
`reserved(warehouse, sku)` SHALL возвращать сумму количеств по всем строкам активных (не истёкших) резервов для этой позиции. `available(warehouse, sku)` SHALL возвращать физический остаток минус `reserved`, но не меньше нуля: `max(0, on_hand - reserved)`; если физически меньше, чем зарезервировано (например, после `adjust`), `available` равен 0, а не отрицательному числу. Для незарегистрированного SKU оба метода MUST бросать `UnknownSkuError`; для зарегистрированного без остатка — возвращать 0. Резервировать MUST быть можно только из доступного количества. Резервы со статусами `EXPIRED`, `CONFIRMED`, `CANCELLED` MUST NOT учитываться в `reserved`.

#### Scenario: Резерв уменьшает доступное, но не физическое
- **WHEN** `on_hand("A","X") == 10` и создан резерв на 4
- **THEN** `reserved == 4`, `available == 6`, `on_hand == 10`

#### Scenario: Нельзя резервировать больше доступного
- **WHEN** `available("A","X") == 6` и вызывается `reserve` на 7
- **THEN** бросается `InsufficientStockError`

#### Scenario: Второй заказ видит только остаток после первого резерва
- **WHEN** физически 10, резерв `SO-1` на 8, затем `reserve("SO-2", [("A","X",3)])`
- **THEN** бросается `InsufficientStockError`

#### Scenario: Физически меньше, чем зарезервировано
- **WHEN** физически 10, резерв на 8, затем `adjust` до 5
- **THEN** `reserved == 8`, `available == 0`, `on_hand == 5`, а `reserve` на 1 бросает `InsufficientStockError` с `available == 0`

#### Scenario: Неизвестный SKU в запросах
- **WHEN** `available` или `reserved` вызван для незарегистрированного SKU
- **THEN** бросается `UnknownSkuError`

### Requirement: Истечение резерва по часам сервиса
Резерв со статусом `ACTIVE`, у которого текущее время часов сервиса не меньше `expires_at`, MUST считаться истёкшим: его снимок MUST иметь статус `EXPIRED`, он MUST NOT учитываться в `available` и `reserved`. Статус вычисляется в момент обращения; фоновых задач быть не должно, истечение MUST NOT записываться в журнал. Статусы `CONFIRMED` и `CANCELLED` окончательные: истечение времени их не меняет. Чтение (`get_reservation`, `available`, `reserved`) MUST NOT менять журнал.

#### Scenario: Резерв истёк
- **WHEN** после `reserve` часы продвинуты на TTL или больше
- **THEN** `get_reservation(...).status == EXPIRED`, `reserved == 0`, `available == on_hand`, количество событий в журнале не изменилось

#### Scenario: Резерв ещё действует прямо перед границей
- **WHEN** часы на 1 секунду раньше `expires_at`
- **THEN** статус `ACTIVE`

#### Scenario: Освободившийся товар можно зарезервировать снова
- **WHEN** резерв истёк, и другой заказ резервирует тот же товар
- **THEN** `reserve` успешен

#### Scenario: Подтверждённый резерв не становится истёкшим
- **WHEN** резерв подтверждён, затем время `expires_at` прошло
- **THEN** статус остаётся `CONFIRMED`

#### Scenario: Отменённый резерв не становится истёкшим
- **WHEN** резерв отменён, затем время `expires_at` прошло
- **THEN** статус остаётся `CANCELLED`

### Requirement: Подтверждение резерва
`confirm(order_id)` SHALL превратить активный резерв в отгрузку атомарно: физический остаток MUST уменьшиться по каждой строке, статус MUST стать `CONFIRMED`, возвращается снимок. Нулевой `available` подтверждению MUST NOT мешать, так как товар зарезервирован под этот заказ. Достаточность физического остатка MUST проверяться по сумме количеств всех строк одной позиции (склад + SKU); при нехватке — `InsufficientStockError` без изменений состояния и журнала. Истёкший резерв — `ReservationExpiredError`; `CONFIRMED` или `CANCELLED` — `ReservationStateError`.

#### Scenario: Успешное подтверждение
- **WHEN** физически 10, резерв на 4, `confirm`
- **THEN** `on_hand == 6`, `reserved == 0`, статус `CONFIRMED`

#### Scenario: Подтверждение при нулевом available
- **WHEN** весь физический остаток зарезервирован под этот заказ
- **THEN** `confirm` успешен и `on_hand` становится 0

#### Scenario: Дублирующиеся строки при подтверждении
- **WHEN** резерв содержит строки `("A","X",2)` и `("A","X",3)`, а физический остаток стал 4 (например, после `adjust`)
- **THEN** `confirm` бросает `InsufficientStockError` (requested=5), остаток, статус и журнал не меняются

#### Scenario: Подтверждение истёкшего резерва
- **WHEN** резерв истёк
- **THEN** `confirm` бросает `ReservationExpiredError`, остаток не меняется

#### Scenario: Повторное подтверждение или подтверждение отменённого
- **WHEN** `confirm` вызван для `CONFIRMED` или `CANCELLED` резерва
- **THEN** бросается `ReservationStateError`

### Requirement: Отмена резерва
`cancel(order_id)` SHALL освободить активный резерв и перевести его в `CANCELLED`, вернув снимок. Отмена MUST быть идемпотентной: повторная отмена уже отменённого резерва ничего не меняет и ничего не пишет в журнал, возвращает снимок `CANCELLED`. Отмена `CONFIRMED` резерва — `ReservationStateError`. Отмена истёкшего резерва ничего не меняет и не пишет в журнал, снимок остаётся `EXPIRED`.

#### Scenario: Отмена освобождает товар
- **WHEN** активный резерв на 4 отменён
- **THEN** статус `CANCELLED`, `reserved == 0`, `on_hand` не изменился

#### Scenario: Повторная отмена
- **WHEN** `cancel` вызван второй раз
- **THEN** возвращается снимок `CANCELLED`, журнал не пополнился

#### Scenario: Отмена подтверждённого
- **WHEN** `cancel` вызван для `CONFIRMED` резерва
- **THEN** бросается `ReservationStateError`

#### Scenario: Отмена истёкшего
- **WHEN** `cancel` вызван для истёкшего резерва
- **THEN** ошибка не бросается, журнал не пополняется, статус снимка `EXPIRED`

### Requirement: Продление резерва
`extend(order_id, ttl)` SHALL продлить активный резерв: новый срок равен `now + ttl`, где `now` — текущее время часов сервиса в момент запроса. Срок никогда не сокращается: если `now + ttl` не позже текущего `expires_at`, `extend` ничего не меняет, MUST NOT писать `RESERVE_EXTEND` в журнал и возвращает резерв как есть. Возвращается снимок. `ttl` MUST проверяться как в `reserve` (положительный `timedelta`, иначе `ValidationError`). Ошибки по статусам такие же, как у `confirm`: истёкший — `ReservationExpiredError`, `CONFIRMED`/`CANCELLED` — `ReservationStateError`. Истёкший резерв продлить нельзя.

#### Scenario: Успешное продление
- **WHEN** активный резерв с `expires_at = T` и текущим временем `now`, при этом `now + 10 минут` позже `T`, продлён на 10 минут
- **THEN** `expires_at == now + 10 минут`, статус `ACTIVE`, записан `RESERVE_EXTEND`

#### Scenario: Продление не сокращает срок
- **WHEN** `now + ttl` не позже текущего `expires_at` (например, резерв на 15 минут сразу продлевается на 10)
- **THEN** `expires_at` не меняется, `RESERVE_EXTEND` в журнал не пишется, возвращается резерв как есть

#### Scenario: Продление истёкшего
- **WHEN** резерв истёк
- **THEN** бросается `ReservationExpiredError`

#### Scenario: Продление подтверждённого или отменённого
- **WHEN** резерв `CONFIRMED` или `CANCELLED`
- **THEN** бросается `ReservationStateError`

#### Scenario: Некорректный TTL при продлении
- **WHEN** `extend("SO-1", timedelta(0))`
- **THEN** бросается `ValidationError`, `expires_at` не меняется

### Requirement: Получение резерва и отсутствующий заказ
`get_reservation(order_id)` SHALL возвращать неизменяемый снимок с актуальным на момент вызова статусом. Если резерва с таким `order_id` нет, `confirm`, `cancel`, `extend` и `get_reservation` MUST бросать `ReservationNotFoundError` с атрибутом `order_id`. Все ошибки резервов (`ReservationError` и наследники) MUST наследоваться от `WarehouseError` и иметь атрибут `order_id`.

#### Scenario: Неизвестный заказ
- **WHEN** любой из `confirm`, `cancel`, `extend`, `get_reservation` вызван для несуществующего `order_id`
- **THEN** бросается `ReservationNotFoundError`, `exc.order_id` равен переданному значению

#### Scenario: Снимок не изменяется последующими операциями
- **WHEN** получен снимок активного резерва, затем резерв отменён
- **THEN** ранее полученный снимок сохраняет статус `ACTIVE`

### Requirement: Расход не забирает чужие резервы
`issue` MUST NOT уменьшать остаток ниже суммы активных резервов по позиции: если `qty` больше `available`, MUST бросаться `InsufficientStockError`, состояние и журнал не меняются. То же MUST действовать для `transfer` со склада-источника, так как это расход. `adjust` фиксирует факт и проверок достаточности не делает. Для кода без резервов поведение `issue`/`transfer` MUST остаться прежним.

#### Scenario: issue больше доступного
- **WHEN** физически 10, резерв на 8, `issue(..., 3)`
- **THEN** бросается `InsufficientStockError`, `on_hand == 10`

#### Scenario: issue в пределах доступного
- **WHEN** физически 10, резерв на 8, `issue(..., 2)`
- **THEN** успешно, `on_hand == 8`, `available == 0`

#### Scenario: transfer не забирает резерв
- **WHEN** физически 10, резерв на 8, `transfer` 3 единиц на другой склад
- **THEN** бросается `InsufficientStockError`

#### Scenario: Истёкший резерв не блокирует расход
- **WHEN** резерв истёк и вызывается `issue` на весь физический остаток
- **THEN** расход успешен

#### Scenario: Без резервов поведение прежнее
- **WHEN** резервов нет
- **THEN** `issue`, `transfer`, `on_hand`, `stock_levels` работают как до изменения

### Requirement: События журнала резервов
Операции MUST писать события в журнал существующим форматом и только при успешном выполнении. `reserve` пишет по одному `RESERVE` на каждую строку в порядке строк с полями `order`, `wh`, `sku`, `qty`, `expires` (время в формате журнала). `confirm` пишет по одному обычному `ISSUE` на каждую строку в порядке строк с `ref` = номер заказа, затем `RESERVE_CONFIRM` с полем `order`. `cancel` пишет `RESERVE_CANCEL` (`order`) только при реальной отмене. `extend` пишет `RESERVE_EXTEND` с полями `order` и `expires` (новое значение) только если срок действительно увеличился. Истечение и операции чтения MUST NOT писать в журнал. Неуспешная операция MUST NOT оставлять событий.

#### Scenario: События reserve
- **WHEN** `reserve("SO-1", [("A","X",2), ("B","Y",3)])`
- **THEN** в журнале два события `RESERVE` с `order=SO-1` в порядке строк, каждое с `wh`, `sku`, `qty`, `expires`

#### Scenario: События confirm
- **WHEN** подтверждается резерв из двух строк
- **THEN** в журнале два `ISSUE` с `ref=SO-1` в порядке строк, затем один `RESERVE_CONFIRM` с `order=SO-1`

#### Scenario: События cancel и extend
- **WHEN** выполняются `extend` и затем `cancel`
- **THEN** записаны `RESERVE_EXTEND` (`order`, `expires`) и `RESERVE_CANCEL` (`order`)

#### Scenario: Ошибка не оставляет событий
- **WHEN** `reserve` завершается `InsufficientStockError`
- **THEN** журнал не изменился

### Requirement: Обратная совместимость
Конструктор `Inventory`, методы `receive`, `issue`, `transfer`, `adjust`, `on_hand`, `stock_levels`, формат строки журнала, `warehouse/cli.py`, `warehouse/reports.py` и существующие тесты MUST остаться без изменений поведения для кода без резервов. `on_hand` и `stock_levels` MUST показывать физический остаток без учёта резервов. Новые зависимости MUST NOT добавляться.

#### Scenario: Физический остаток в запросах
- **WHEN** есть активный резерв
- **THEN** `on_hand` и `stock_levels` показывают полный физический остаток

#### Scenario: Существующие тесты
- **WHEN** запускается `python -m pytest -q`
- **THEN** все ранее существовавшие тесты проходят без правок
