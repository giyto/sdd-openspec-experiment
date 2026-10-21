## MODIFIED Requirements

### Requirement: Резерв держит товар под заказ без изменения физического остатка
Система SHALL позволять зарезервировать товар под заказ (`order_id`) одним вызовом `reserve` по
всем его строкам `(warehouse, sku, qty)`. Строки MAY относиться к разным складам. Резерв SHALL
сохранять строки в том порядке и в том виде, в котором они переданы, без склеивания строк одной
позиции. Резерв SHALL NOT менять физический остаток, который возвращают `on_hand` и `stock_levels`.

Временные метки: `created_at` SHALL быть текущим временем часов сервиса, `expires_at` SHALL быть
`created_at + ttl`. Если `ttl` не передан, SHALL использоваться `DEFAULT_RESERVATION_TTL`, равный
20 минутам. `ttl` больше `MAX_RESERVATION_LIFETIME` (2 часа) SHALL отклоняться `ValidationError`;
`ttl`, равный `MAX_RESERVATION_LIFETIME`, допустим.

#### Scenario: Успешное резервирование нескольких строк на разных складах
- **WHEN** на складе `MAIN` есть 5 шт `BOLT-M8`, на `EAST` есть 3 шт `BOLT-M8`, и вызывается
  `reserve("ORD-1", [("MAIN", "BOLT-M8", 2), ("EAST", "BOLT-M8", 1)])`
- **THEN** возвращается снимок резерва со статусом `ACTIVE`, строки в том же порядке, `expires_at`
  равен `created_at` плюс 20 минут, `on_hand("MAIN", "BOLT-M8")` по-прежнему равен 5

#### Scenario: Явный TTL
- **WHEN** вызывается `reserve("ORD-2", [("MAIN", "BOLT-M8", 1)], ttl=timedelta(minutes=5))`
- **THEN** `expires_at` равен `created_at` плюс 5 минут

#### Scenario: TTL равен пределу
- **WHEN** вызывается `reserve("ORD-2A", [("MAIN", "BOLT-M8", 1)], ttl=timedelta(hours=2))`
- **THEN** резерв создаётся, `expires_at` равен `created_at` плюс 2 часа

#### Scenario: TTL больше предела
- **WHEN** вызывается `reserve("ORD-2B", [("MAIN", "BOLT-M8", 1)], ttl=timedelta(hours=2, seconds=1))`
- **THEN** бросается `ValidationError`, резерв не создаётся, журнал не меняется

#### Scenario: Некорректный TTL
- **WHEN** `ttl` равен нулю, отрицательный или не является `timedelta`
- **THEN** бросается `ValidationError`, резерв не создаётся, журнал не меняется

#### Scenario: Заказ без строк
- **WHEN** вызывается `reserve("ORD-3", [])`
- **THEN** бросается `ValidationError`, резерв не создаётся, журнал не меняется

#### Scenario: Недостаточно доступного товара
- **WHEN** по позиции `(MAIN, BOLT-M8)` доступно 2 шт и вызывается `reserve` на 3 шт
- **THEN** бросается `InsufficientStockError`, резерв не создаётся, журнал не меняется

### Requirement: Повторный резерв по заказу
Система SHALL отклонять `reserve` с `DuplicateReservationError`, если по `order_id` уже есть резерв
в статусе `CONFIRMED`. Если прежний резерв по заказу `ACTIVE` (с учётом истечения по времени), `EXPIRED`
или `CANCELLED`, `reserve` SHALL разрешаться и полностью заменять прежний резерв новым.

При замене `ACTIVE`-резерва в журнал SHALL сначала писаться `RESERVE_CANCEL` с `order` по прежнему
резерву, затем `RESERVE` по каждой строке нового резерва. Новый резерв SHALL получать собственные
`created_at` и `expires_at` от момента замены, как будто заказ оформлен заново. При замене `EXPIRED`- или
`CANCELLED`-резерва `RESERVE_CANCEL` не пишется.

При проверке наличия для замены товар прежнего `ACTIVE`-резерва SHALL считаться свободным. Если новых
строк не хватает даже с учётом освобождённого товара, бросается `InsufficientStockError`, прежний резерв
остаётся `ACTIVE`, журнал не меняется.

#### Scenario: Повтор при активном резерве
- **WHEN** по `ORD-7` резерв `ACTIVE` на `(MAIN, BOLT-M8, 2)`, на `MAIN` есть 3 шт `BOLT-M8`, и вызывается
  `reserve("ORD-7", [("MAIN", "BOLT-M8", 3)])`
- **THEN** прежний резерв заменяется новым со статусом `ACTIVE`, `reserved("MAIN", "BOLT-M8")` равен 3,
  в журнале идут `RESERVE_CANCEL` с `order=ORD-7`, затем `RESERVE` с `order=ORD-7`, `qty=3`

#### Scenario: Замена с нехваткой товара
- **WHEN** по `ORD-7A` резерв `ACTIVE` на `(MAIN, BOLT-M8, 2)`, на `MAIN` всего 3 шт `BOLT-M8`, и вызывается
  `reserve("ORD-7A", [("MAIN", "BOLT-M8", 4)])`
- **THEN** бросается `InsufficientStockError`, прежний резерв остаётся `ACTIVE` с прежним `expires_at`,
  журнал не меняется

#### Scenario: Новый срок при замене
- **WHEN** резерв `ORD-7B` создан в момент T и заменён в момент T + 10 минут с TTL по умолчанию
- **THEN** `created_at` нового резерва равен T + 10 минут, `expires_at` равен T + 30 минут

#### Scenario: Повтор после истечения
- **WHEN** резерв `ORD-8` истёк по времени и вызывается `reserve("ORD-8", ...)` с новыми строками
- **THEN** создаётся новый резерв со статусом `ACTIVE`, он заменяет прежний, событие `RESERVE` пишется
  по каждой новой строке, `RESERVE_CANCEL` не пишется

#### Scenario: Повтор после отмены
- **WHEN** резерв `ORD-9` отменён и вызывается `reserve("ORD-9", ...)`
- **THEN** создаётся новый резерв со статусом `ACTIVE`, он заменяет отменённый

#### Scenario: Повтор после подтверждения
- **WHEN** резерв `ORD-10` подтверждён и вызывается `reserve("ORD-10", ...)`
- **THEN** бросается `DuplicateReservationError`, журнал не меняется

### Requirement: Истечение резерва вычисляется по часам сервиса
Система SHALL считать резерв в статусе `ACTIVE` истёкшим в момент `now >= expires_at` и показывать
статус `EXPIRED` в снимке, возвращаемом любым методом. Истекший резерв SHALL NOT учитываться в
`reserved` и `available`. Истечение само по себе SHALL NOT записываться в журнал, и фоновых задач не
требуется; событие `RESERVE_EXPIRE` пишется только методом `sweep_expired`. Статусы `CONFIRMED` и
`CANCELLED` окончательные: истечение времени их не меняет.

#### Scenario: Ровно в момент истечения
- **WHEN** резерв на 2 шт создан с `expires_at` = T, и запрошено `available` в момент T
- **THEN** резерв не учитывается, `available` включает эти 2 шт, `get_reservation` возвращает `EXPIRED`

#### Scenario: Непосредственно до истечения
- **WHEN** запрошены `reserved` и `get_reservation` в момент `expires_at - 1 секунда`
- **THEN** резерв учитывается в `reserved` и возвращается со статусом `ACTIVE`

#### Scenario: Подтверждённый заказ после времени резерва
- **WHEN** резерв подтверждён, и прошло время `expires_at`
- **THEN** `get_reservation` возвращает статус `CONFIRMED`

### Requirement: Отмена резерва
Система SHALL по `cancel(order_id)` переводить активный резерв в `CANCELLED` и писать событие
`RESERVE_CANCEL` с `order`. Отмена SHALL быть идемпотентной: повторная отмена `CANCELLED`-резерва и
отмена истёкшего резерва SHALL ничего не менять и ничего не писать в журнал; истёкший резерв
остаётся `EXPIRED`.

Отмена `CONFIRMED`-резерва (возврат) SHALL вернуть товар по всем строкам на те же склады, с которых он был
списан: по каждой строке в порядке строк пишется `RECEIVE` с `ref` = `order_id` и количеством строки,
затем пишется `RESERVE_CANCEL` с `order`. Статус SHALL стать `CANCELLED`. Возврат SHALL NOT проверять
остатки. Повторная отмена такого резерва ничего не меняет.

#### Scenario: Отмена активного резерва
- **WHEN** активный резерв `ORD-15` на 3 шт и вызывается `cancel("ORD-15")`
- **THEN** статус становится `CANCELLED`, `available` увеличивается на 3, пишется `RESERVE_CANCEL`
  с `order=ORD-15`

#### Scenario: Повторная отмена
- **WHEN** резерв `ORD-16` уже `CANCELLED` и вызывается `cancel("ORD-16")`
- **THEN** возвращается снимок со статусом `CANCELLED`, журнал не меняется

#### Scenario: Отмена истёкшего резерва
- **WHEN** резерв `ORD-17` истёк по времени и вызывается `cancel("ORD-17")`
- **THEN** возвращается снимок со статусом `EXPIRED`, журнал не меняется

#### Scenario: Отмена подтверждённого резерва
- **WHEN** резерв `ORD-18` подтверждён строками `(MAIN, BOLT-M8, 2)` и `(EAST, BOLT-M8, 1)` и вызывается
  `cancel("ORD-18")`
- **THEN** физические остатки `MAIN` и `EAST` увеличиваются на 2 и 1, в журнале идут `RECEIVE` с `ref=ORD-18`
  для `MAIN` (qty=2), `RECEIVE` с `ref=ORD-18` для `EAST` (qty=1), затем `RESERVE_CANCEL` с `order=ORD-18`,
  статус становится `CANCELLED`

#### Scenario: Повторная отмена после возврата
- **WHEN** резерв `ORD-18A` уже возвращён (`CANCELLED`) и вызывается `cancel("ORD-18A")`
- **THEN** остатки и журнал не меняются

### Requirement: Продление резерва
Система SHALL по `extend(order_id, ttl)` устанавливать `expires_at` в `now + ttl` для активного
резерва, но не позже `created_at + MAX_RESERVATION_LIFETIME`: если `now + ttl` позже предела, срок
SHALL ставиться ровно на предел. Срок SHALL NOT сокращаться: если новое значение не позже текущего
`expires_at`, ничего не меняется и событие не пишется. При продлении пишется `RESERVE_EXTEND` с `order`
и `expires` (новое значение `expires_at`). `ttl` проверяется так же, как в `reserve`, но превышение
предела для `extend` ошибкой не является. Ошибки по статусу: `CONFIRMED` и `CANCELLED` дают
`ReservationStateError`, `EXPIRED` даёт `ReservationExpiredError`.

#### Scenario: Продление активного резерва
- **WHEN** резерв `ORD-19` с `expires_at` через 10 минут, и вызывается `extend("ORD-19", timedelta(minutes=30))`
- **THEN** `expires_at` становится `now + 30 минут`, пишется `RESERVE_EXTEND` с `order=ORD-19` и `expires`

#### Scenario: Продление не сокращает срок
- **WHEN** резерв `ORD-20` с `expires_at` через 20 минут, и вызывается `extend("ORD-20", timedelta(minutes=5))`
- **THEN** `expires_at` не меняется, событие не пишется

#### Scenario: Продление сверх предела
- **WHEN** резерв `ORD-20A` создан в момент T с `expires_at` T + 20 минут, и в момент T + 10 минут вызывается
  `extend("ORD-20A", timedelta(hours=5))`
- **THEN** `expires_at` становится T + 2 часа (ровно предел), не ошибка, пишется `RESERVE_EXTEND`
  с `expires` = T + 2 часа

#### Scenario: Продление истёкшего резерва
- **WHEN** резерв `ORD-21` истёк и вызывается `extend("ORD-21", ttl)`
- **THEN** бросается `ReservationExpiredError`, журнал не меняется

#### Scenario: Некорректный TTL при продлении
- **WHEN** вызывается `extend("ORD-22", timedelta(0))`
- **THEN** бросается `ValidationError`, журнал не меняется

### Requirement: События журнала по резервам
Система SHALL писать события журнала только в перечисленных случаях и в формате существующего журнала:
`RESERVE` — по одному на каждую строку резерва с полями `order`, `wh`, `sku`, `qty`, `expires`;
при `confirm` — `ISSUE` на каждую строку с `ref` = `order_id`, затем `RESERVE_CONFIRM` с `order`;
при `cancel` активного резерва — `RESERVE_CANCEL` с `order`; при `cancel` подтверждённого резерва —
`RECEIVE` на каждую строку с `ref` = `order_id`, затем `RESERVE_CANCEL` с `order`; при замене активного
резерва — `RESERVE_CANCEL` с `order` по прежнему резерву, затем `RESERVE` по строкам нового;
`RESERVE_EXTEND` с `order` и `expires`; `RESERVE_EXPIRE` с `order` и `expires` — только из
`sweep_expired`. Истечение само по себе событий не порождает.

#### Scenario: События при резервировании двух строк
- **WHEN** вызывается `reserve("ORD-25", [("MAIN", "BOLT-M8", 2), ("EAST", "BOLT-M8", 1)])`
- **THEN** в журнале два события `RESERVE`, каждое с полями `order=ORD-25`, `wh`, `sku`, `qty`, `expires`

### Requirement: Предельный срок резерва
Система SHALL ограничивать срок резерва `MAX_RESERVATION_LIFETIME` (2 часа) от момента его создания:
`expires_at` резерва SHALL NOT быть позже `created_at + MAX_RESERVATION_LIFETIME`. Предел SHALL
проверяться в `reserve` (через `ValidationError`) и в `extend` (через ограничение срока, без ошибки).

#### Scenario: Предел при продлении не превышается
- **WHEN** резерв создан в момент T и продлевается в любой момент до истечения
- **THEN** `expires_at` не больше T + 2 часа

### Requirement: Выборка резервов и доступность по позициям
Система SHALL по `reservations(status=None)` возвращать неизменяемые снимки текущих резервов, по одному
на заказ, отсортированные по `created_at`, затем по `order_id`. Если передан `status`, SHALL возвращаться
только резервы с этим статусом на текущий момент часов сервиса (с учётом истечения по времени). Выборка
SHALL NOT менять статусы и остатки.

Система SHALL по `availability(warehouse=None)` возвращать строку `Availability` (`warehouse`, `sku`,
`on_hand`, `reserved`, `available`) на каждую позицию, где есть физический остаток или активный
(не истёкший) резерв. Значения SHALL совпадать с `on_hand`, `reserved` и `available` по той же позиции.
Порядок и фильтр по складу SHALL совпадать с `stock_levels`: по складу и SKU, с фильтром по складу, если он
передан.

#### Scenario: Список резервов по дате создания
- **WHEN** резервы `ORD-A` созданы в T + 2 минуты, `ORD-B` в T, `ORD-C` в T + 2 минуты
- **THEN** `reservations()` возвращает `ORD-B`, `ORD-A`, `ORD-C`

#### Scenario: Фильтр по статусу учитывает истечение
- **WHEN** резерв `ORD-D` `ACTIVE` истёк по времени, а `ORD-E` подтверждён
- **THEN** `reservations(ReservationStatus.EXPIRED)` содержит `ORD-D`, `reservations(ReservationStatus.ACTIVE)`
  его не содержит, `reservations(ReservationStatus.CONFIRMED)` содержит `ORD-E`

#### Scenario: Доступность по позициям
- **WHEN** на `MAIN` 5 шт `BOLT-M8`, активный резерв на 2 шт, на `EAST` 3 шт `BOLT-M8` без резерва,
  а SKU `NUT-M8` зарегистрирован, но ни остатка, ни резерва по нему нет
- **THEN** `availability()` возвращает `(EAST, BOLT-M8, on_hand=3, reserved=0, available=3)` и
  `(MAIN, BOLT-M8, on_hand=5, reserved=2, available=3)` в таком порядке; `NUT-M8` не попадает

#### Scenario: Доступность с фильтром по складу
- **WHEN** вызывается `availability("MAIN")`
- **THEN** возвращаются только строки склада `MAIN`

#### Scenario: Позиция только с активным резервом
- **WHEN** на `EAST` нет физического остатка `BOLT-M8`, а активный резерв держит 1 шт
- **THEN** `availability()` содержит `(EAST, BOLT-M8, on_hand=0, reserved=1, available=0)`

### Requirement: Отметка истечения резервов
Система SHALL по `sweep_expired()` находить резервы, истёкшие по времени, о которых ещё не писали, писать
по каждому событие `RESERVE_EXPIRE` с полями `order` и `expires` (значение `expires_at`) и возвращать их
`order_id` в порядке `expires_at`, затем `order_id`. О каждом резерве SHALL писаться один раз: повторный
вызов ничего не пишет. Если заказ был заменён новым резервом, и новый резерв тоже истёк, он
отмечается отдельно как другой резерв. Метод SHALL NOT менять статусы, остатки и `expires_at`.

#### Scenario: Первый вызов отмечает истёкшие резервы
- **WHEN** резерв `ORD-30` истёк в момент T1, резерв `ORD-31` истёк в момент T0 < T1, `ORD-32` ещё активен,
  и вызывается `sweep_expired()`
- **THEN** возвращается `["ORD-31", "ORD-30"]`, в журнале два `RESERVE_EXPIRE` с полями `order` и `expires`
  в этом порядке, `ORD-32` не отмечается

#### Scenario: Повторный вызов
- **WHEN** `sweep_expired()` уже вызывался, новых истёкших резервов нет, и вызывается снова
- **THEN** возвращается пустой список, журнал не меняется

#### Scenario: Истёкший резерв заменён и истёк снова
- **WHEN** резерв `ORD-33` истёк и отмечен `sweep_expired()`, затем `reserve("ORD-33", ...)` создал новый резерв
  и тот тоже истёк, и вызывается `sweep_expired()`
- **THEN** возвращается `["ORD-33"]`, пишется второе `RESERVE_EXPIRE` с `expires` нового резерва

#### Scenario: Подтверждённые и отменённые не отмечаются
- **WHEN** резерв `ORD-34` подтверждён или отменён, и время его `expires_at` прошло, и вызывается `sweep_expired()`
- **THEN** `ORD-34` не возвращается, событие не пишется

#### Scenario: Статусы и остатки не меняются
- **WHEN** `sweep_expired()` отметил `ORD-35`
- **THEN** `get_reservation("ORD-35")` по-прежнему возвращает `EXPIRED`, остатки и `available` не меняются
