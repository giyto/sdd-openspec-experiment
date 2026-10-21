## MODIFIED Requirements

### Requirement: Модель резерва и публичный API
Система SHALL предоставлять в `warehouse/models.py` `ReservationStatus(str, Enum)` со значениями `ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`, frozen-датаклассы `ReservationLine(warehouse, sku, qty)` и `Reservation(order_id, lines, created_at, expires_at, status)`, где `lines` — `tuple[ReservationLine, ...]`, а также frozen-датакласс `Availability(warehouse, sku, on_hand, reserved, available)`. В `warehouse/errors.py` SHALL быть `ReservationError(WarehouseError)` и его наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у каждого есть атрибут `order_id`. В `warehouse/reservations.py` SHALL быть `DEFAULT_RESERVATION_TTL = timedelta(minutes=20)` и `MAX_RESERVATION_LIFETIME = timedelta(hours=2)`. `Inventory` SHALL предоставлять методы `reserve(order_id, lines, ttl=None)`, `confirm(order_id)`, `cancel(order_id)`, `extend(order_id, ttl)`, `get_reservation(order_id)`, `available(warehouse, sku)`, `reserved(warehouse, sku)`, `reservations(status=None)`, `availability(warehouse=None)`, `sweep_expired()`. Методы `reserve`, `confirm`, `cancel`, `extend`, `get_reservation` SHALL возвращать снимок `Reservation` со статусом на текущий момент по часам сервиса.

#### Scenario: Значения статусов
- **WHEN** читаются значения `ReservationStatus`
- **THEN** они равны строкам `"active"`, `"expired"`, `"confirmed"`, `"cancelled"`, и члены enum сравниваются равными этим строкам

#### Scenario: TTL по умолчанию
- **WHEN** читается `DEFAULT_RESERVATION_TTL`
- **THEN** он равен `timedelta(minutes=20)`

#### Scenario: Предельный срок
- **WHEN** читается `MAX_RESERVATION_LIFETIME`
- **THEN** он равен `timedelta(hours=2)`

#### Scenario: Availability
- **WHEN** создаётся `Availability("A", "BOLT", 10, 4, 6)`
- **THEN** поля читаются под именами `warehouse`, `sku`, `on_hand`, `reserved`, `available`, а присвоение полю бросает ошибку (датакласс frozen)

#### Scenario: Ошибки несут order_id
- **WHEN** любая из ошибок резервов возникает для заказа `SO-1`
- **THEN** её атрибут `order_id` равен `"SO-1"`, и она является `ReservationError` и `WarehouseError`

### Requirement: Создание резерва
`reserve` SHALL удерживать товар под заказ сразу по всем строкам (строки могут относиться к разным складам и могут быть кортежами `(warehouse, sku, qty)` или `ReservationLine`). Физический остаток SHALL не меняться. `created_at` SHALL быть текущим временем часов сервиса, `expires_at = created_at + ttl`; при `ttl=None` используется `DEFAULT_RESERVATION_TTL`. `ttl` больше `MAX_RESERVATION_LIFETIME` SHALL приводить к `ValidationError`; `ttl`, равный пределу, допустим. Строки в снимке SHALL храниться в том порядке и в том виде, как переданы, без склеивания одинаковых позиций. Наличие SHALL проверяться по сумме строк каждой позиции (склад + SKU). Операция SHALL быть атомарной: при любой ошибке ни резервы, ни журнал не меняются.

#### Scenario: Успешное резервирование на нескольких складах
- **WHEN** на складах `A` и `B` есть товар и вызывается `reserve("SO-1", [("A","BOLT",2), ("B","NUT",1)])` в момент `T`
- **THEN** возвращается `Reservation` со статусом `ACTIVE`, `created_at == T`, `expires_at == T + 20 минут`, `lines` в переданном порядке, а `on_hand` обеих позиций не изменился

#### Scenario: Явный TTL и ReservationLine
- **WHEN** вызывается `reserve("SO-1", [ReservationLine("A","BOLT",1)], ttl=timedelta(hours=1))`
- **THEN** `expires_at == created_at + 1 час`

#### Scenario: TTL ровно на пределе
- **WHEN** вызывается `reserve` с `ttl == MAX_RESERVATION_LIFETIME`
- **THEN** резерв создаётся, `expires_at == created_at + 2 часа`

#### Scenario: TTL больше предела
- **WHEN** вызывается `reserve` с `ttl` больше `MAX_RESERVATION_LIFETIME` (например, `timedelta(hours=2, seconds=1)`)
- **THEN** бросается `ValidationError`, резервы и журнал не меняются (в том числе активный резерв того же заказа остаётся как был)

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

### Requirement: Истечение резерва по часам сервиса
Резерв SHALL считаться истёкшим, как только текущее время часов сервиса достигает `expires_at` (`now >= expires_at`). Истёкший резерв SHALL иметь статус `EXPIRED` и не учитываться в `available` и `reserved`. Истечение определяется в момент обращения, без фоновых задач; само по себе истечение и обычные обращения (`get_reservation`, `reservations`, `available`, `reserved` и др.) SHALL не порождать событий журнала. Единственный способ записать истечение в журнал — явный вызов `sweep_expired`. Статусы `CONFIRMED` и `CANCELLED` окончательные: истечение времени их не меняет.

#### Scenario: Граница срока
- **WHEN** часы стоят ровно на `expires_at`
- **THEN** `get_reservation` возвращает статус `EXPIRED`, а товар снова входит в `available`

#### Scenario: Незадолго до срока
- **WHEN** до `expires_at` осталась меньше секунды
- **THEN** статус `ACTIVE`, товар остаётся зарезервированным

#### Scenario: Истечение не пишется в журнал
- **WHEN** срок резерва прошёл и вызывается `get_reservation` (или `reservations`, `available`)
- **THEN** число событий журнала не изменилось

#### Scenario: Подтверждённый и отменённый не истекают
- **WHEN** время проходит `expires_at` у подтверждённого или отменённого резерва
- **THEN** статус остаётся `CONFIRMED` или `CANCELLED` соответственно

### Requirement: Повторный reserve по тому же заказу
`reserve` на `order_id`, у которого есть подтверждённый резерв, SHALL бросать `DuplicateReservationError`. `reserve` на `order_id` с активным резервом SHALL заменять его: новый резерв считается новым целиком (свои строки, `created_at` = момент замены, `expires_at` от момента замены, статус `ACTIVE`), а при проверке наличия количества заменяемого резерва считаются свободными (для каждой позиции доступно `max(0, остаток − резервы других заказов)`). Замена SHALL быть атомарной: если проверка не проходит или аргументы некорректны, активный резерв остаётся без изменений, а журнал без новых событий. При успешной замене журнал получает сначала `RESERVE_CANCEL` по заменяемому резерву, затем `RESERVE` по строкам нового. Если прежний резерв истёк или отменён, новый `reserve` SHALL быть разрешён и полностью заменять прежний (строки, сроки, статус); `RESERVE_CANCEL` в этом случае не пишется.

#### Scenario: Дубликат активного
- **WHEN** у заказа активный резерв на `("A","BOLT",2)` и вызывается `reserve` со строками `("A","NUT",1)` в момент `T2`
- **THEN** ошибки нет (повторный `reserve` активного резерва больше не `DuplicateReservationError`), `get_reservation` возвращает новый резерв со статусом `ACTIVE`, строками `("A","NUT",1)`, `created_at == T2`, `expires_at == T2 + ttl`; `reserved("A","BOLT")` равен 0

#### Scenario: Товар заменяемого резерва считается свободным
- **WHEN** на складе 10 единиц, активный резерв заказа `SO-1` на 8, и `SO-1` повторно резервирует 10 той же позиции
- **THEN** замена проходит, `reserved` равен 10; а `reserve` на 10 от другого заказа `SO-2` в тех же условиях бросает `InsufficientStockError`

#### Scenario: Замена не проходит проверку остатка
- **WHEN** замещающий `reserve` активного резерва падает с `InsufficientStockError` (с учётом освобождённого количества), `ValidationError` или `UnknownSkuError`
- **THEN** прежний активный резерв остаётся без изменений (строки, `created_at`, `expires_at`, статус `ACTIVE`), журнал не меняется

#### Scenario: Журнал замены
- **WHEN** активный резерв заменяется новым с двумя строками
- **THEN** в журнал добавляются `RESERVE_CANCEL` (`order`) по старому резерву, затем два `RESERVE` по строкам нового в порядке строк

#### Scenario: Дубликат подтверждённого
- **WHEN** повторно вызывается `reserve` для подтверждённого заказа
- **THEN** бросается `DuplicateReservationError`, резерв и журнал не меняются

#### Scenario: Замена истёкшего или отменённого
- **WHEN** прежний резерв заказа истёк или отменён и вызывается `reserve` с другими строками
- **THEN** `get_reservation` возвращает новый резерв со статусом `ACTIVE` и новыми строками, `RESERVE_CANCEL` не пишется

#### Scenario: Замена истёкшего не проходит проверку остатка
- **WHEN** замещающий `reserve` истёкшего или отменённого резерва падает с `InsufficientStockError`
- **THEN** прежний (истёкший или отменённый) резерв остаётся без изменений

### Requirement: Отмена резерва
`cancel` SHALL освобождать активный резерв и переводить его в `CANCELLED`. Отмена SHALL быть идемпотентной: повторная отмена и отмена истёкшего резерва ничего не меняют и ничего не пишут в журнал, истёкший резерв остаётся `EXPIRED`, и `cancel` возвращает его снимок. `cancel` подтверждённого заказа SHALL быть возвратом: физический остаток увеличивается по каждой строке на её количество на том же складе, статус становится `CANCELLED`, возвращается снимок `CANCELLED`. Возврат SHALL выполняться один раз: повторный `cancel` уже возвращённого заказа — обычная идемпотентная отмена отменённого. Возврат SHALL не зависеть от `expires_at` и от резервов других заказов.

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
- **WHEN** подтверждён резерв `("A","BOLT",2)`, `("B","NUT",1)` (остатки списаны), затем вызывается `cancel` этого заказа
- **THEN** `on_hand("A","BOLT")` и `on_hand("B","NUT")` вернулись к значениям до `confirm`, статус `CANCELLED`

#### Scenario: Возврат со строками одной позиции
- **WHEN** подтверждённый резерв содержит строки `("A","BOLT",2)` и `("A","BOLT",3)` и вызывается `cancel`
- **THEN** остаток `("A","BOLT")` вырос на 5

#### Scenario: Возврат после срока резерва
- **WHEN** время давно прошло `expires_at` подтверждённого резерва и вызывается `cancel`
- **THEN** возврат выполняется так же, статус `CANCELLED`

#### Scenario: Повторный возврат
- **WHEN** `cancel` вызывается второй раз для уже возвращённого заказа
- **THEN** возвращается снимок `CANCELLED`, остатки и журнал не меняются

### Requirement: Продление резерва
`extend(order_id, ttl)` SHALL проверять `ttl` так же, как `reserve` в части типа и знака (положительный `timedelta`, иначе `ValidationError`), но `ttl` больше `MAX_RESERVATION_LIFETIME` для `extend` допустим. Ошибки статусов SHALL быть такими же, как у `confirm` (истёкший — `ReservationExpiredError`, подтверждённый или отменённый — `ReservationStateError`). Для активного резерва целевой срок равен `now + ttl`, где `now` — текущее время часов сервиса (а не старый `expires_at`), но не позже `created_at + MAX_RESERVATION_LIFETIME`: если `now + ttl` превышает предел, срок ставится ровно на предел, и это не ошибка. Срок SHALL никогда не сокращаться: если целевой срок не позже текущего `expires_at`, резерв и журнал не меняются.

#### Scenario: Продление
- **WHEN** резерв активен с `expires_at = T+20м`, часы на `T+5м`, вызывается `extend(order, 30 минут)`
- **THEN** `expires_at == T+35м`, пишется `RESERVE_EXTEND` с этим сроком

#### Scenario: Продление сверх предела
- **WHEN** резерв создан в `T`, часы на `T+1ч`, вызывается `extend(order, 90 минут)`
- **THEN** ошибки нет, `expires_at == T+2ч`, пишется `RESERVE_EXTEND` с `expires`, равным `T+2ч`

#### Scenario: Срок уже на пределе
- **WHEN** `expires_at == created_at + 2 часа` и вызывается `extend` с любым `ttl`
- **THEN** `expires_at` не меняется, событие не пишется, возвращается актуальный снимок

#### Scenario: Огромный ttl
- **WHEN** вызывается `extend(order, timedelta(days=365))`
- **THEN** ошибки нет, срок ставится на предел (или остаётся, если уже на пределе)

#### Scenario: Попытка сократить срок
- **WHEN** целевой срок не позже текущего `expires_at`
- **THEN** `expires_at` не меняется, событие не пишется, возвращается актуальный снимок

#### Scenario: Некорректный ttl
- **WHEN** `ttl` не положительный `timedelta`
- **THEN** бросается `ValidationError`

#### Scenario: Недопустимый статус
- **WHEN** продлевается истёкший, подтверждённый или отменённый резерв
- **THEN** бросается `ReservationExpiredError` для истёкшего и `ReservationStateError` для остальных

### Requirement: События журнала
Операции с резервами SHALL писать в журнал события в существующем формате: `RESERVE` на каждую строку с полями `order`, `wh`, `sku`, `qty`, `expires`; при замене активного резерва — сначала `RESERVE_CANCEL` с полем `order` по старому резерву, затем `RESERVE` по строкам нового; при `confirm` — обычный `ISSUE` на каждую строку (с `ref` = номер заказа) в порядке строк, затем `RESERVE_CONFIRM` с полем `order`; `RESERVE_CANCEL` с полем `order` при фактической отмене; при возврате подтверждённого заказа — обычный `RECEIVE` (`wh`, `sku`, `qty`, `ref` = номер заказа) на каждую строку в порядке строк, затем `RESERVE_CANCEL` с полем `order`; `RESERVE_EXTEND` с полями `order`, `expires` при фактическом продлении; `RESERVE_EXPIRE` с полями `order`, `expires` из `sweep_expired`. Поле `expires` SHALL записываться форматом времени журнала. Неуспешные операции, идемпотентные повторы и само истечение времени событий не пишут.

#### Scenario: Журнал reserve
- **WHEN** выполняется `reserve` с двумя строками
- **THEN** в журнал добавляются два события `RESERVE` в порядке строк, каждое с `order`, `wh`, `sku`, `qty`, `expires`

#### Scenario: Журнал confirm
- **WHEN** подтверждается резерв с двумя строками
- **THEN** добавляются два `ISSUE` с `ref` = номеру заказа, затем `RESERVE_CONFIRM` с `order`

#### Scenario: Журнал cancel и extend
- **WHEN** фактически отменяется активный резерв или продлевается резерв
- **THEN** пишется `RESERVE_CANCEL` (`order`) или `RESERVE_EXTEND` (`order`, `expires`)

#### Scenario: Журнал возврата
- **WHEN** отменяется подтверждённый заказ `SO-1` с двумя строками
- **THEN** добавляются два `RECEIVE` с `ref=SO-1` в порядке строк, затем `RESERVE_CANCEL` с `order=SO-1`, и больше ничего

## ADDED Requirements

### Requirement: Предельный срок резерва
`expires_at` резерва SHALL никогда не быть позже `created_at + MAX_RESERVATION_LIFETIME` (два часа). `reserve` с `ttl` больше предела SHALL бросать `ValidationError`; `extend` сверх предела SHALL ставить срок ровно на предел без ошибки. `DEFAULT_RESERVATION_TTL` SHALL не превышать предел.

#### Scenario: Инвариант срока
- **WHEN** резерв создан и многократно продлевается с разными `ttl`
- **THEN** `expires_at - created_at` ни в какой момент не превышает 2 часа

### Requirement: Список резервов
`reservations(status=None)` SHALL возвращать список снимков `Reservation` текущих резервов, по одному на заказ (для заказа — последний резерв), со статусом на текущий момент по часам сервиса. Список SHALL быть отсортирован по `created_at`, затем по `order_id`. С `status` в результат попадают только резервы, чей статус на текущий момент равен `status` (истёкший по времени резерв — `EXPIRED`, а не `ACTIVE`). Если подходящих резервов нет, SHALL возвращаться пустой список. Метод SHALL не менять состояние и не писать в журнал. Значение `status`, не являющееся `ReservationStatus` и не `None`, SHALL приводить к `ValidationError`.

#### Scenario: Без фильтра
- **WHEN** есть резервы разных заказов в статусах `ACTIVE`, `EXPIRED`, `CONFIRMED`, `CANCELLED`
- **THEN** возвращаются снимки всех, по одному на заказ

#### Scenario: Порядок
- **WHEN** два резерва созданы в один момент для заказов `SO-2` и `SO-1`, третий создан позже
- **THEN** порядок: `SO-1`, `SO-2`, затем третий

#### Scenario: Фильтр по статусу на текущий момент
- **WHEN** срок одного из резервов уже прошёл и вызывается `reservations(ReservationStatus.ACTIVE)`
- **THEN** истёкший резерв в результат не входит, а `reservations(ReservationStatus.EXPIRED)` его возвращает

#### Scenario: Заказ с заменой
- **WHEN** резерв заказа заменён новым
- **THEN** в списке один снимок этого заказа — новый резерв

#### Scenario: Пустой результат
- **WHEN** резервов с запрошенным статусом нет
- **THEN** возвращается `[]`, журнал не изменился

### Requirement: Сводка наличия
`availability(warehouse=None)` SHALL возвращать список `Availability` по одной строке на каждую позицию (склад + SKU), у которой есть физический остаток (больше 0) или активный (не истёкший) резерв. `on_hand`, `reserved`, `available` SHALL быть теми же значениями, что возвращают одноимённые методы для этой позиции. Порядок строк и фильтр по складу SHALL быть такими же, как у `stock_levels` (по складу, затем по SKU; при заданном `warehouse` — только этот склад, для склада без позиций — пустой список). Метод SHALL не писать в журнал.

#### Scenario: Позиция с остатком и резервом
- **WHEN** на складе `A` 10 единиц `BOLT` и активный резерв на 4
- **THEN** строка `Availability("A","BOLT",10,4,6)`

#### Scenario: Только резерв без остатка
- **WHEN** после резерва `adjust` обнулил остаток позиции, а резерв ещё активен
- **THEN** позиция в списке: `on_hand == 0`, `reserved` равен резервированному, `available == 0`

#### Scenario: Только остаток
- **WHEN** у позиции остаток 5 и нет активных резервов
- **THEN** строка `Availability(wh, sku, 5, 0, 5)`

#### Scenario: Истёкший резерв и нулевой остаток
- **WHEN** остаток позиции 0, а единственный резерв истёк
- **THEN** позиции в списке нет

#### Scenario: Порядок и фильтр
- **WHEN** есть позиции на складах `B` и `A`, вызывается `availability()` и `availability("A")`
- **THEN** первый вызов отсортирован по складу, затем SKU, как `stock_levels()`; второй содержит только склад `A`

### Requirement: Фиксация истечения резервов
`sweep_expired()` SHALL находить резервы, чей статус на текущий момент `EXPIRED` и о которых `sweep_expired` ещё не писал, для каждого записывать событие `RESERVE_EXPIRE` (`order`, `expires` — формат времени журнала) и возвращать список их `order_id`, отсортированный по `expires_at`, затем по `order_id`. События SHALL писаться в том же порядке. О каждом резерве SHALL записываться не более одного события: повторный вызов не возвращает и не пишет уже отмеченные резервы. Резерв, созданный заново для того же `order_id` (после истечения, отмены или замены), SHALL считаться другим резервом: если он тоже истёк, о нём пишется своё событие. Резерв, истёкший к моменту замены новым `reserve`, но не отмеченный, SHALL остаться кандидатом на отметку (допущение, см. design.md). Метод SHALL не менять статусы резервов, остатки, `available` и `reserved`; при отсутствии кандидатов он возвращает `[]` без событий. Резервы в статусах `ACTIVE` (не истёкшие), `CONFIRMED` и `CANCELLED` метод игнорирует. Внутри сервиса фоновых процессов нет: метод вызывает внешний планировщик.

#### Scenario: Отметка истёкших
- **WHEN** истекли резервы заказов `SO-2` и `SO-1` с одинаковым `expires_at`, и вызывается `sweep_expired()`
- **THEN** возвращается `["SO-1", "SO-2"]`, в журнал добавлены два `RESERVE_EXPIRE` с `order` и `expires` в этом порядке

#### Scenario: Порядок по сроку
- **WHEN** у `SO-9` срок истечения раньше, чем у `SO-1`
- **THEN** `SO-9` идёт первым

#### Scenario: Один раз на резерв
- **WHEN** `sweep_expired()` вызывается дважды подряд без новых истечений
- **THEN** второй вызов возвращает `[]` и не пишет событий

#### Scenario: Неистёкшие не затрагиваются
- **WHEN** есть активные неистёкшие, подтверждённые и отменённые резервы
- **THEN** они не возвращаются и события не пишутся

#### Scenario: Статусы и остатки не меняются
- **WHEN** вызывается `sweep_expired()`
- **THEN** `get_reservation` по отмеченному заказу по-прежнему даёт `EXPIRED`, `on_hand`, `reserved` и `available` не изменились, а `cancel` отмеченного резерва остаётся идемпотентным no-op

#### Scenario: Новый резерв того же заказа
- **WHEN** резерв `SO-1` истёк и отмечен, затем `SO-1` зарезервирован заново, и новый резерв тоже истёк
- **THEN** следующий `sweep_expired()` возвращает `["SO-1"]` и пишет ещё одно `RESERVE_EXPIRE`

#### Scenario: Заменён до отметки
- **WHEN** резерв `SO-1` истёк, `sweep_expired` по нему не вызывался, `SO-1` зарезервирован заново, и позже истёк и второй резерв
- **THEN** `sweep_expired()` возвращает `["SO-1", "SO-1"]` в порядке `expires_at` резервов и пишет два события `RESERVE_EXPIRE`
