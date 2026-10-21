### design.md

## Context

`Inventory` (`warehouse/inventory.py`) хранит физические остатки в `InMemoryStore`, время берёт только из внедрённых часов, пишет события в `EventLog`; соглашения README требуют атомарности (сначала все проверки, потом изменения), неизменяемых снимков и неизменного формата журнала. Мотивация и допущения — в `proposal.md`, требования — в `specs/stock-reservations/spec.md`.

## Goals / Non-Goals

**Goals:**
- Реализовать резервы целиком внутри `Inventory` без фоновых задач; публичный API ровно как в задаче.
- Не изменять поведение кода, не использующего резервы.

**Non-Goals:**
- Правки `cli.py`, `reports.py`, формата журнала, существующих тестов.
- Персистентность резервов, очистка старых записей, повторное использование `order_id`.

## Decisions

1. **Хранение.** Внутренняя изменяемая запись (`order_id`, `lines`, `created_at`, `expires_at`, явный статус из `ACTIVE/CONFIRMED/CANCELLED`) лежит в словаре в `InMemoryStore` (новый атрибут с методами add/get/iter), чтобы состояние резервов жило рядом с остатками при общем `store`. Конструктор `Inventory` не меняется. Альтернатива — словарь в самом `Inventory`: проще, но два `Inventory` над одним store разошлись бы по резервам.
2. **Ленивое истечение.** Статус `EXPIRED` не хранится, а вычисляется: если сохранённый статус `ACTIVE` и `now >= expires_at` — `EXPIRED`, иначе сохранённый. Время `now` читается один раз на операцию, чтобы проверки и запись внутри вызова были согласованы. Окончательные статусы не пересчитываются. Сравнение идёт по полной точности; секундное усечение касается только записи в журнал.
3. **Подсчёт.** `reserved(wh, sku)` — сумма `qty` строк активных (по п.2) резервов; строки одной позиции суммируются, склейки в хранимых данных нет. `available = max(0, on_hand - reserved)`. Полный перебор резервов допустим (хранилище в памяти).
4. **Проверка достаточности в одном месте.** Приватный помощник собирает требования по позициям (`dict[(wh, sku)] -> сумма`, порядок первого появления) и сравнивает с пределом: для `reserve`, `issue`, `transfer` — `available`; для `confirm` — физический остаток. `InsufficientStockError(wh, sku, requested=сумма, available=предел)`. `issue` и источник `transfer` переключаются с `on_hand` на `available`; без активных резервов результат совпадает со старым.
5. **Порядок проверок в `reserve`:** коды и количества → SKU зарегистрированы → `lines` не пуст → `ttl` → дубликат `order_id` → достаточность → мутации. Строки нормализуются в `ReservationLine` (кортеж не из трёх элементов — `ValidationError`); итерируемое материализуется один раз.
6. **`confirm`.** Проверки: найден → статус (`CONFIRMED`/`CANCELLED` → `ReservationStateError`, `EXPIRED` → `ReservationExpiredError`) → физический остаток ≥ суммы по позиции. Затем уменьшение остатков, запись `ISSUE` (`ref=order_id`) по строкам и `RESERVE_CONFIRM`. Статус записи ставится после успешных проверок. Остатки уменьшаются напрямую через store, а не через публичный `issue`, чтобы не упереться в ограничение `available` собственным резервом.
7. **`cancel`:** `CANCELLED` → снимок без записи; `CONFIRMED` → `ReservationStateError`; `EXPIRED` → снимок без изменений; иначе `CANCELLED` + `RESERVE_CANCEL`. **`extend`:** валидация `ttl` → найден → статус как в `confirm` → `expires_at += ttl` + `RESERVE_EXTEND`. Проверка `ttl` — общая с `reserve`, выполняется до поиска заказа.
8. **Журнал.** Значение `expires` — `format_timestamp(expires_at)` (формат времени события, без пробелов и `=`). Все значения проверяются до первой записи, чтобы `EventFormatError` не оставил полузаписанное состояние.
9. **Размещение кода.** Модели — `models.py`, ошибки — `errors.py` (конструкторы принимают `order_id`), `reservations.py` — `DEFAULT_RESERVATION_TTL` и чистые помощники (нормализация строк, агрегация требований, проверка `ttl`) без зависимости от `Inventory`, чтобы не было циклического импорта. Новые имена экспортируются в `warehouse/__init__.py`. Логирование — модульный `logger`, без `print`.

## Risks / Trade-offs

- [`movement_summary` увидит `sku` в `RESERVE*` и добавит нулевую строку для SKU, по которому были только резервы] → reports.py не трогаем по условию задачи; суммы не искажаются, так как учитываются только `RECEIVE/ISSUE/ADJUST`.
- [`adjust` может опустить остаток ниже активных резервов, и `confirm` вынужден отказать] → `InsufficientStockError` с откатом; `available` обрезается нулём.
- [Граница истечения `now >= expires_at` и секундное усечение времени в журнале дают расхождение до секунды между `expires` в журнале и реальным моментом] → принято; снимок хранит полную точность.
- [Записи резервов не удаляются, `order_id` не переиспользуется] → осознанно (см. допущения в proposal); рост памяти не критичен.
- [Полный перебор резервов в `reserved`] → приемлемо для хранилища в памяти; индекс можно добавить позже без изменения API.


### proposal.md

## Why

Сейчас товар списывается только при отгрузке: пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать второй раз, и склад вынужден извиняться перед клиентом (WH-214). Нужно удерживать товар под заказ с момента оформления, а неоплаченные резервы должны сами переставать действовать по TTL — без фоновых задач, по часам сервиса в момент обращения.

## What Changes

- В `warehouse/models.py` добавляются `ReservationStatus` (`ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`), `ReservationLine(warehouse, sku, qty)` и `Reservation(order_id, lines, created_at, expires_at, status)` — неизменяемые датаклассы, как задано в задаче.
- В `warehouse/errors.py` добавляются `ReservationError(WarehouseError)` и её наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`; у всех атрибут `order_id`.
- Новый модуль `warehouse/reservations.py` с константой `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (по обновлению от 13.10: 15 минут, а не 30).
- В `Inventory` добавляются методы `reserve(order_id, lines, ttl=None)`, `confirm(order_id)`, `cancel(order_id)`, `extend(order_id, ttl)`, `get_reservation(order_id)`, `available(warehouse, sku)`, `reserved(warehouse, sku)`.
- Истечение резерва определяется лениво, по часам сервиса в момент обращения; в журнал не пишется. `CONFIRMED` и `CANCELLED` окончательные и истечением не меняются.
- `issue` (и `transfer`, у которого для источника «проверки те же, что у `issue`») не могут забрать товар из чужих активных резервов.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; `confirm` дополнительно пишет обычные `ISSUE` с `ref` = номер заказа.
- Старый API (`Inventory(...)`, `receive/issue/transfer/adjust/on_hand/stock_levels`) для кода без резервов работает как раньше. Не меняются `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты; зависимости не добавляются.

## Capabilities

### New Capabilities
- `stock-reservations`: резервирование товара под заказы с TTL — создание, подтверждение, отмена, продление, запросы `available`/`reserved`, учёт резервов при расходе, события журнала.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций. Влияние на `issue`/`transfer` описано в новой спецификации как требование при наличии активных резервов; поведение без резервов не меняется.)

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, `warehouse/inventory.py`, новый `warehouse/reservations.py`; возможно `warehouse/storage.py` (хранение резервов) и `warehouse/__init__.py` (экспорт новых имён).
- Журнал: четыре новых типа событий; формат строки не меняется. Отчёт `movement_summary` игнорирует незнакомые типы событий, но `RESERVE*` с полем `sku` добавят в сводку нулевую строку для SKU, по которому были только резервы (reports.py не трогаем — принято).
- Зависимости: нет. Публичный API старых методов не ломается.

## Допущения (решения без ответа автора)

- Резерв истёк, когда `now >= expires_at` (в момент `expires_at` резерв уже не действует).
- `extend` сдвигает существующий `expires_at` на `ttl` (`expires_at += ttl`), а не отсчитывает от текущего момента.
- `order_id` уникален навсегда: повторный `reserve` с тем же `order_id` — `DuplicateReservationError`, даже если прежний резерв истёк, отменён или подтверждён.
- `cancel` истёкшего резерва — не ошибка и не действие: статус остаётся `EXPIRED`, журнал не пишется.
- `available` не бывает отрицательным: если инвентаризация (`adjust`) опустила физический остаток ниже резервов, `available` = 0.


### specs/stock-reservations/spec.md

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
`Inventory.extend(order_id, ttl)` SHALL продлевать активный резерв, сдвигая `expires_at` на `ttl` (`new_expires_at = expires_at + ttl`), и возвращать снимок. `ttl` проверяется как в `reserve` (положительный `timedelta`, иначе `ValidationError`). Ошибки по статусам такие же, как у `confirm`: истёкший — `ReservationExpiredError`, `CONFIRMED`/`CANCELLED` — `ReservationStateError`, отсутствующий — `ReservationNotFoundError`.

#### Scenario: Успешное продление
- **WHEN** резерв с `expires_at = T+15m` продлевается на 10 минут в момент T+5m
- **THEN** `expires_at == T+25m`, статус `ACTIVE`

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
Каждая успешная операция SHALL писать события в `EventLog` в существующем формате строки: `reserve` — `RESERVE` на каждую строку в порядке строк с полями `order`, `wh`, `sku`, `qty`, `expires`; `confirm` — `ISSUE` на каждую строку (поля как у обычного расхода, `ref` = номер заказа), затем `RESERVE_CONFIRM` с полем `order`; `cancel` активного резерва — `RESERVE_CANCEL` с `order`; `extend` — `RESERVE_EXTEND` с `order` и `expires` (новое значение). Значение `expires` SHALL быть записано тем же форматом, что время события. Истечение, повторная отмена, отмена истёкшего и любые неуспешные операции SHALL не писать событий.

#### Scenario: События confirm
- **WHEN** резерв из двух строк подтверждается
- **THEN** в журнале появляются два `ISSUE` с `ref=<order_id>` и затем один `RESERVE_CONFIRM order=<order_id>`

#### Scenario: Формат expires
- **WHEN** создан резерв с `expires_at = 2026-03-01T10:15:00Z`
- **THEN** каждое событие `RESERVE` содержит `expires=2026-03-01T10:15:00Z`


### tasks.md

## 1. Модели, ошибки, константы

- [ ] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py` ровно по сигнатурам задачи; проверить тестом: значения enum, неизменяемость датаклассов, `ReservationStatus` — наследник `str`
- [ ] 1.2 Добавить `ReservationError` и четыре наследника с атрибутом `order_id` в `warehouse/errors.py`; проверить тестом: иерархия от `WarehouseError`, `order_id` доступен
- [ ] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` и помощниками (нормализация строк, агрегация по позициям, проверка `ttl`); проверить юнит-тестами нормализации и ошибок `ValidationError`/`InvalidQuantityError`

## 2. Хранение и запросы

- [ ] 2.1 Добавить в `InMemoryStore` хранилище записей резервов (без изменения конструктора `Inventory`); проверить, что существующие тесты проходят без правок
- [ ] 2.2 Реализовать вычисление эффективного статуса по часам сервиса (`now >= expires_at` → `EXPIRED`, окончательные статусы не меняются), `get_reservation`, `reserved`, `available` (не меньше 0, `UnknownSkuError` для незарегистрированного SKU); проверить тестами на `ManualClock`, включая границу ровно `expires_at` и подтверждённый заказ после времени резерва

## 3. Операции

- [ ] 3.1 Реализовать `reserve` (порядок проверок, суммирование дублей позиции, `DuplicateReservationError`, события `RESERVE` на каждую строку, атомарность); проверить тестами: несколько складов, дубли строк, порядок `lines`, нехватка, `ValidationError`, журнал не меняется при ошибке
- [ ] 3.2 Реализовать `confirm` (физический остаток по сумме позиции, нулевой `available` допустим, события `ISSUE` с `ref` и `RESERVE_CONFIRM`, ошибки по статусам); проверить тестами, включая атомарность при нехватке
- [ ] 3.3 Реализовать `cancel` (идемпотентность без записи в журнал, `ReservationStateError` для подтверждённого, `EXPIRED` без изменений, `RESERVE_CANCEL`) и `extend` (`expires_at += ttl`, `RESERVE_EXTEND`, ошибки как у `confirm`); проверить тестами
- [ ] 3.4 Перевести `issue` и источник `transfer` на проверку по `available`; проверить тестами: расход из чужого резерва даёт `InsufficientStockError`, после истечения резерва проходит, без резервов поведение и значение `available` в ошибке прежние

## 4. Интеграция и проверка

- [ ] 4.1 Экспортировать новые имена в `warehouse/__init__.py`; проверить импортом из пакета
- [ ] 4.2 Проверить формат строк журнала новых событий (`expires=…Z`, порядок полей, `parse_line` разбирает все строки) тестом
- [ ] 4.3 Запустить `python -m pytest -q`: все прежние тесты проходят без правок; `git diff` не затрагивает `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты
- [ ] 4.4 Сверить публичный API реализации с proposal и specs (имена, порядок и вид параметров, поля датаклассов, значения enum, атрибут `order_id` у ошибок, `DEFAULT_RESERVATION_TTL` = 15 минут) и убедиться, что расхождений нет
