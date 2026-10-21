### design.md

## Context

Вся бизнес-логика живёт в `Inventory` (`warehouse/inventory.py`), состояние — в `InMemoryStore`, время — только из внедрённых часов, журнал — `EventLog` с неизменяемым форматом строки. Операции атомарны: сначала проверки, потом изменения. Мотивация и состав API — см. proposal.md, требования — specs/stock-reservations/spec.md. Публичный API из задачи реализуется дословно.

## Goals / Non-Goals

**Goals:**
- Реализовать резервы внутри `Inventory` с ленивым истечением, не меняя старое поведение.

**Non-Goals:**
- Фоновые задачи, персистентность, события об истечении, правки `cli.py`/`reports.py`.
- Склейка одинаковых позиций в резерве.

## Decisions

1. **Хранение.** Внутренняя изменяемая запись резерва (order_id, строки-кортеж `ReservationLine`, created_at, expires_at, хранимый статус `ACTIVE/CONFIRMED/CANCELLED`) лежит в `dict[str, record]` в `InMemoryStore` (методы добавляются, существующие не меняются); `DEFAULT_RESERVATION_TTL` и запись — в `warehouse/reservations.py`. Наружу — только frozen-снимок `Reservation`. Альтернатива (словарь прямо в `Inventory`) отвергнута: состояние сервиса уже хранится в store.
2. **Ленивое истечение.** Хранимый статус никогда не становится `EXPIRED`; эффективный статус вычисляется по `now = clock.now()` в момент обращения: `ACTIVE` и `now >= expires_at` → `EXPIRED`. Граница включительная (допущение). Операция читает часы один раз. `CONFIRMED`/`CANCELLED` со временем не меняются.
3. **Агрегаты.** `reserved(wh, sku)` — сумма `qty` по всем строкам эффективно-активных резервов (линейный проход, достаточно для in-memory). `available = on_hand - reserved`; не обрезается нулём (после `adjust` может быть отрицательным), в `InsufficientStockError` в поле `available` передаётся `max(0, available)`.
4. **Проверка по сумме позиции.** В `reserve` строки группируются по `(warehouse, sku)` только для проверки наличия (`requested` = сумма); в резерве строки хранятся как пришли. То же в `confirm` (сравнение с физическим остатком, а не с `available`).
5. **Порядок проверок `reserve`:** `order_id` (код) → `ttl` → непустота строк → нормализация и валидация каждой строки (форма, склад, SKU, qty) → `DuplicateReservationError` → достаточность по позициям. Затем запись состояния и журнала. Допущение: уникальность `order_id` вечная, в том числе для отменённых/истёкших.
6. **Расход и резервы.** Проверка в `issue` и в `transfer` (источник) использует `available` вместо физического остатка. `transfer` включён, т.к. по его контракту источник — обычный расход. `adjust` не меняется. `confirm` не вызывает публичный `issue`, а сам уменьшает остаток и пишет те же события `ISSUE` (ref = order_id), чтобы не упираться в `available`; затем `RESERVE_CONFIRM`.
7. **`cancel`.** `ACTIVE` → `CANCELLED` + событие; `CANCELLED` → no-op; `CONFIRMED` → `ReservationStateError`; истёкший → no-op со снимком `EXPIRED` (допущение: освобождать нечего, а истечение не журналируется).
8. **`extend`.** `expires_at += ttl` от прежнего `expires_at` («продлевает на ttl»); истёкший не оживает. Порядок проверок: `ttl` → существование → статус.
9. **Операции над существующим резервом:** найти (`NotFound`) → проверить статус/время → проверить остаток (`confirm`) → выполнить.
10. **Журнал.** Поле `expires` форматируется `format_timestamp` (секундная точность, как время события). Все события операции получают одно `now`.
11. **Ошибки.** `ReservationError(order_id, message)`; наследники принимают `order_id` и сами формируют сообщение; новые имена экспортируются из `warehouse/__init__.py`.
12. **Тесты.** Новый `tests/test_reservations.py` на `ManualClock`; существующие тесты не трогаем.

## Risks / Trade-offs

- [`transfer` с резервами меняет поведение относительно буквального текста задачи, где упомянут только `issue`] → следует из контракта `transfer` (расход источника) и защищает от того же двойного списания; зафиксировано в spec.
- [Линейный подсчёт `reserved`] → приемлемо для in-memory; индекс можно добавить без смены API.
- [Отрицательный `available` после `adjust`] → отражает реальность инвентаризации; резервировать при этом нельзя.
- [Допущения: граница истечения `>=`, вечная уникальность `order_id`, `cancel` истёкшего — no-op] → зафиксированы в spec и могут быть изменены отдельной задачей.


### proposal.md

## Why

Товар списывается только при отгрузке, поэтому пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать повторно (WH-214). Нужно резервировать товар под заказ в момент оформления; неоплаченный резерв должен сам перестать действовать по истечении TTL.

## What Changes

- В `Inventory` добавляются методы `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved` (сигнатуры — как в задаче, без изменений).
- В `warehouse/models.py` добавляются `ReservationStatus` (`ACTIVE`, `EXPIRED`, `CONFIRMED`, `CANCELLED`), `ReservationLine`, `Reservation`.
- В `warehouse/errors.py` добавляются `ReservationError(WarehouseError)` и наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у всех атрибут `order_id`.
- Новый модуль `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (значение уточнено в обсуждении: 15 минут, а не 30 из текста задачи).
- Истечение вычисляется лениво по часам сервиса в момент обращения: фоновых задач нет, в журнал истечение не пишется.
- `issue` (и `transfer` как расход со склада-источника) не может забрать товар из чужих активных резервов.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` пишет обычные `ISSUE` с `ref` = номер заказа.
- Не ломается: конструктор и `receive/issue/transfer/adjust/on_hand/stock_levels` для кода без резервов; `on_hand`/`stock_levels` по-прежнему показывают физический остаток. `cli.py`, `reports.py` и существующие тесты не меняются, зависимостей не добавляется.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказ с TTL, подтверждение, отмена, продление, запросы `available`/`reserved`, влияние резервов на расход и записи в журнале.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций; поведение `issue`/`transfer` при наличии резервов описано в новой capability, без резервов оно не меняется)

## Impact

- Код: `warehouse/inventory.py`, `warehouse/models.py`, `warehouse/errors.py`, `warehouse/__init__.py` (экспорт), новый `warehouse/reservations.py`, `warehouse/storage.py` (хранение резервов); новый `tests/test_reservations.py`.
- Формат строки журнала не меняется, добавляются только новые типы событий (внешняя выгрузка увидит новые `kind`).
- Зависимости: нет.


### specs/stock-reservations/spec.md

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
Для одного `order_id` MUST существовать не более одного резерва за всё время жизни сервиса, независимо от его статуса. Повторный `reserve` с уже использованным `order_id` MUST бросать `DuplicateReservationError` (атрибут `order_id`), не меняя состояние.

#### Scenario: Повторный reserve для активного заказа
- **WHEN** `reserve("SO-1", ...)` вызван второй раз при активном резерве `SO-1`
- **THEN** бросается `DuplicateReservationError` и первый резерв не изменён

#### Scenario: Повторный reserve для отменённого или истёкшего заказа
- **WHEN** резерв `SO-1` отменён или истёк, и снова вызывается `reserve("SO-1", ...)`
- **THEN** бросается `DuplicateReservationError`

### Requirement: Доступное и зарезервированное количество
`reserved(warehouse, sku)` SHALL возвращать сумму количеств по всем строкам активных (не истёкших) резервов для этой позиции. `available(warehouse, sku)` SHALL возвращать физический остаток минус `reserved`. Для незарегистрированного SKU оба метода MUST бросать `UnknownSkuError`; для зарегистрированного без остатка — возвращать 0. Резервировать MUST быть можно только из доступного количества. Резервы со статусами `EXPIRED`, `CONFIRMED`, `CANCELLED` MUST NOT учитываться в `reserved`.

#### Scenario: Резерв уменьшает доступное, но не физическое
- **WHEN** `on_hand("A","X") == 10` и создан резерв на 4
- **THEN** `reserved == 4`, `available == 6`, `on_hand == 10`

#### Scenario: Нельзя резервировать больше доступного
- **WHEN** `available("A","X") == 6` и вызывается `reserve` на 7
- **THEN** бросается `InsufficientStockError`

#### Scenario: Второй заказ видит только остаток после первого резерва
- **WHEN** физически 10, резерв `SO-1` на 8, затем `reserve("SO-2", [("A","X",3)])`
- **THEN** бросается `InsufficientStockError`

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
`extend(order_id, ttl)` SHALL продлить активный резерв: новый `expires_at` равен прежнему `expires_at + ttl`; возвращается снимок. `ttl` MUST проверяться как в `reserve` (положительный `timedelta`, иначе `ValidationError`). Ошибки по статусам такие же, как у `confirm`: истёкший — `ReservationExpiredError`, `CONFIRMED`/`CANCELLED` — `ReservationStateError`. Истёкший резерв продлить нельзя.

#### Scenario: Успешное продление
- **WHEN** активный резерв с `expires_at = T` продлён на 10 минут
- **THEN** `expires_at == T + 10 минут`, статус `ACTIVE`

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
Операции MUST писать события в журнал существующим форматом и только при успешном выполнении. `reserve` пишет по одному `RESERVE` на каждую строку в порядке строк с полями `order`, `wh`, `sku`, `qty`, `expires` (время в формате журнала). `confirm` пишет по одному обычному `ISSUE` на каждую строку в порядке строк с `ref` = номер заказа, затем `RESERVE_CONFIRM` с полем `order`. `cancel` пишет `RESERVE_CANCEL` (`order`) только при реальной отмене. `extend` пишет `RESERVE_EXTEND` с полями `order` и `expires` (новое значение). Истечение и операции чтения MUST NOT писать в журнал. Неуспешная операция MUST NOT оставлять событий.

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


### tasks.md

## 1. Модели и ошибки

- [ ] 1.1 Добавить в `warehouse/models.py` `ReservationStatus`, `ReservationLine`, `Reservation` (frozen, поля как в задаче); проверить тестом на неизменяемость и значения enum
- [ ] 1.2 Добавить в `warehouse/errors.py` `ReservationError` и четыре наследника с атрибутом `order_id`; проверить тестом `isinstance(..., WarehouseError)` и `exc.order_id`
- [ ] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` и внутренней записью резерва; проверить тестом значения константы

## 2. Хранение и запросы

- [ ] 2.1 Добавить в `InMemoryStore` методы хранения резервов, не меняя существующие; существующие тесты проходят
- [ ] 2.2 Реализовать вычисление эффективного статуса по часам сервиса, `get_reservation`, `reserved`, `available`; тесты: истечение на границе, `CONFIRMED`/`CANCELLED` не истекают, `ReservationNotFoundError`, `UnknownSkuError`

## 3. Операции

- [ ] 3.1 Реализовать `reserve` с валидацией, дублями строк, `DuplicateReservationError`, атомарностью и событиями `RESERVE`; тесты по сценариям spec (разные склады, TTL, дубли позиций, ошибки, журнал не меняется при ошибке)
- [ ] 3.2 Реализовать `confirm` (проверка по сумме позиции против физического остатка, `ISSUE` с `ref`, затем `RESERVE_CONFIRM`); тесты: нулевой `available`, дубли строк, истёкший, повторный, отменённый
- [ ] 3.3 Реализовать `cancel` (идемпотентность, истёкший no-op, подтверждённый — ошибка) и `RESERVE_CANCEL`; тесты: повторная отмена не пишет в журнал
- [ ] 3.4 Реализовать `extend` и `RESERVE_EXTEND`; тесты: успех, истёкший, финальные статусы, невалидный `ttl`
- [ ] 3.5 Учесть активные резервы в `issue` и `transfer` (по `available`); тесты: расход сверх доступного, в пределах доступного, истёкший резерв не блокирует, поведение без резервов прежнее

## 4. Завершение

- [ ] 4.1 Экспортировать новые имена в `warehouse/__init__.py` и проверить импорт `from warehouse import Reservation, ReservationError, ...`
- [ ] 4.2 Запустить `python -m pytest -q` целиком: существующие тесты проходят без правок, а `git diff` не затрагивает `cli.py`, `reports.py`, существующие тесты и зависимости
- [ ] 4.3 Сверить публичный API реализации с proposal и specs: имена, сигнатуры и порядок параметров `reserve/confirm/cancel/extend/get_reservation/available/reserved`, поля моделей, значения enum, атрибут `order_id` у ошибок, `DEFAULT_RESERVATION_TTL == timedelta(minutes=15)`, поля событий
