### design.md

## Context

`Inventory` хранит физические остатки в `InMemoryStore`, время берёт из внедрённых часов, пишет события в `EventLog`; проверки выполняются до изменений (атомарность). Мотивация — в proposal.md, требования — в specs. Отчёты читают только `RECEIVE/ISSUE/ADJUST`, новые виды событий они игнорируют.

## Goals / Non-Goals

**Goals:**
- Резервы поверх существующего сервиса без изменения старого API и формата журнала.
- Ленивое истечение по часам сервиса.

**Non-Goals:**
- Фоновая очистка, события истечения, правки CLI и отчётов, персистентность.

## Decisions

- **Хранение.** Записи резервов лежат в `InMemoryStore` (словарь `order_id → запись`), добавляются методы хранилища; конструктор не меняется. Запись хранит неизменяемые данные и записанный статус `ACTIVE/CONFIRMED/CANCELLED`. Альтернатива — словарь в `Inventory`: хуже, если хранилище разделяют.
- **Вычисляемый `EXPIRED`.** Он не хранится: эффективный статус = записанный, а для `ACTIVE` при `now >= expires_at` — `EXPIRED`. Так чтение не имеет побочных записей и не пишет событий. Граница: в момент `expires_at` резерв уже истёк (допущение).
- **Одно «сейчас».** Каждая операция читает `clock.now()` один раз и использует это значение для статуса, `created_at` и события.
- **Расчёт `reserved`.** Суммирование по резервам, активным на `now`. `available = on_hand − reserved` (без обрезки; в `InsufficientStockError.available` — `max(0, …)`).
- **Проверка сумм.** Строки группируются по `(warehouse, sku)` только для проверки; в резерве хранятся как пришли. Порядок проверок в `reserve`: коды/строки/qty/ttl → дубликат `order_id` → SKU → достаточность; затем запись и события. Итератор строк потребляется один раз.
- **`confirm`.** Проверка суммы строк позиции против физического остатка (не `available`), затем списание и `ISSUE` (ref=order_id) на каждую строку в исходном порядке, затем `RESERVE_CONFIRM`. Публичный `issue` не используется (он учитывал бы резерв самого заказа); общая внутренняя логика расхода — без проверки резервов.
- **`issue`/`transfer`.** Предел меняется с физического остатка на `available`. Для `transfer` — потому что его docstring гласит «проверки те же, что у issue», иначе перемещением можно обойти резерв.
- **`extend`:** `expires_at += ttl`, а не `now + ttl` (допущение: «продлевает на ttl»).
- **`cancel` истёкшего:** no-op, статус остаётся `EXPIRED`, без журнала (допущение; освобождать уже нечего).
- **Дубликат `order_id`** — в любом статусе, чтобы заказ имел единственную историю.
- **Время в `expires`:** `format_timestamp` (секундная точность); в снимке `expires_at` сохраняет полную точность.
- **Порядок ошибок** в `confirm/extend/cancel`: сначала `NotFound`, затем статус; для `extend` валидация `ttl` — до поиска резерва.

## Risks / Trade-offs

- [`adjust` уменьшает физический остаток ниже резервов] → `available` может быть отрицательным; `confirm` проверяет физический остаток и бросает `InsufficientStockError` без изменений.
- [Усечение до секунд в журнале при микросекундах в `expires_at`] → допустимо, формат журнала менять нельзя.
- [Линейный подсчёт `reserved`] → при росте объёма добавить индекс по позиции, API не изменится.
- [Допущения о границе истечения, `extend`, `cancel` истёкшего, `transfer`] → зафиксированы в specs и должны быть покрыты тестами.


### proposal.md

## Why

Сейчас товар списывается только при отгрузке: пока покупатель оформляет и оплачивает заказ, тот же товар успевают продать повторно, и складу приходится извиняться перед клиентом (WH-214). Нужно резервировать товар под заказ в момент оформления; неоплаченный резерв должен сам перестать действовать по истечении TTL. Фоновых задач нет, поэтому истечение определяется лениво — по часам сервиса в момент обращения.

## What Changes

- В `Inventory` добавляются резервы: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`, `available`, `reserved`.
- В `warehouse/models.py`: `ReservationStatus` (`ACTIVE="active"`, `EXPIRED="expired"`, `CONFIRMED="confirmed"`, `CANCELLED="cancelled"`), `ReservationLine(warehouse, sku, qty)`, `Reservation(order_id, lines, created_at, expires_at, status)` — неизменяемые датаклассы-снимки.
- В `warehouse/errors.py`: `ReservationError(WarehouseError)` с атрибутом `order_id` и наследники `ReservationNotFoundError`, `ReservationExpiredError`, `ReservationStateError`, `DuplicateReservationError`.
- Новый модуль `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` (по обсуждению в задаче: 15 минут, а не 30 из исходного текста).
- `issue` (и `transfer` как расход со склада-источника) не может забрать товар из чужих активных резервов: учитывается только доступное.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`; при `confirm` пишется обычный `ISSUE` на каждую строку.
- Не меняется: конструктор и прочий API `Inventory`, `on_hand`/`stock_levels` (физический остаток), формат журнала, `cli.py`, `reports.py`, существующие тесты, зависимости.

## Capabilities

### New Capabilities
- `inventory-reservations`: резервирование товара под заказы с TTL, подтверждение, отмена, продление, учёт доступного остатка, события журнала.

### Modified Capabilities
<!-- Основных спецификаций в openspec/specs/ пока нет; ограничение расхода резервами описано в новой capability. -->

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, `warehouse/reservations.py` (новый), `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов); тесты добавляются отдельным файлом.
- API: только добавления; поведение кода без резервов не меняется.
- Зависимости и формат журнала: без изменений.


### specs/inventory-reservations/spec.md

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
`reserve(order_id, lines, ttl=None)` SHALL атомарно зарезервировать товар сразу по всем строкам (склады могут различаться), не меняя физический остаток. `created_at` SHALL быть текущим временем сервиса, `expires_at = created_at + ttl`. Строки SHALL приниматься как кортежи `(warehouse, sku, qty)` или `ReservationLine`. `order_id`, склады и SKU SHALL проверяться как коды (непустая строка без пробелов и `=`); количества — как обычные количества (`InvalidQuantityError`); незарегистрированный SKU — `UnknownSkuError`. Пустой набор строк и `ttl`, не являющийся положительным `timedelta`, SHALL давать `ValidationError`. Если резерв с таким `order_id` уже есть в любом статусе, SHALL быть `DuplicateReservationError`. Достаточность SHALL проверяться по сумме количеств строк одной позиции (склад + SKU) относительно `available`; при нехватке — `InsufficientStockError` (`requested` — сумма по позиции). При любой ошибке состояние и журнал SHALL остаться без изменений.

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

#### Scenario: Повторный order_id
- **WHEN** резерв для `order_id` уже существует (в том числе отменённый или истёкший)
- **THEN** `DuplicateReservationError` с атрибутом `order_id`

### Requirement: Доступный и зарезервированный остаток
`reserved(warehouse, sku)` SHALL возвращать сумму количеств по всем строкам активных (неистёкших на текущий момент) резервов для позиции. `available(warehouse, sku)` SHALL возвращать физический остаток минус `reserved`. Запросы для незарегистрированного SKU SHALL давать `UnknownSkuError`, для зарегистрированного без остатка — 0. `on_hand` и `stock_levels` SHALL по-прежнему показывать физический остаток.

#### Scenario: Резерв уменьшает доступное, но не физическое
- **WHEN** на складе 10, зарезервировано 4
- **THEN** `on_hand == 10`, `reserved == 4`, `available == 6`

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
`extend(order_id, ttl)` SHALL продлить активный резерв: `expires_at` увеличивается на `ttl` (от прежнего `expires_at`). `ttl` проверяется как в `reserve` (`ValidationError`), ошибки статусов — как у `confirm`. Операция SHALL вернуть снимок.

#### Scenario: Успешное продление
- **WHEN** активный резерв с `expires_at = E` продлён на 10 минут
- **THEN** `expires_at == E + 10 минут`, записан `RESERVE_EXTEND`

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
Сервис SHALL писать в журнал: `RESERVE` на каждую строку резерва (поля `order`, `wh`, `sku`, `qty`, `expires`); при `confirm` — обычный `ISSUE` на каждую строку с `ref` = номер заказа, затем `RESERVE_CONFIRM` (`order`); `RESERVE_CANCEL` (`order`) при фактической отмене; `RESERVE_EXTEND` (`order`, `expires`). Время в `expires` SHALL записываться тем же форматом, что и время события. Операции, завершившиеся ошибкой, истечение и идемпотентная повторная отмена SHALL не писать событий.

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


### tasks.md

## 1. Модели и ошибки

- [ ] 1.1 Добавить `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py`; проверить тестом создание, неизменяемость и значения enum
- [ ] 1.2 Добавить `ReservationError` и четыре наследника с атрибутом `order_id` в `warehouse/errors.py`; проверить тестом наследование от `WarehouseError` и атрибут
- [ ] 1.3 Создать `warehouse/reservations.py` с `DEFAULT_RESERVATION_TTL = timedelta(minutes=15)` и вспомогательной логикой (нормализация строк, вычисление статуса); проверить тестом значение константы

## 2. Хранилище и запросы

- [ ] 2.1 Добавить в `InMemoryStore` хранение резервов без изменения существующих методов; проверить, что существующие тесты проходят
- [ ] 2.2 Реализовать `get_reservation`, `reserved`, `available` с ленивым истечением по часам; проверить тестами границу `expires_at`, `UnknownSkuError`, 0 для SKU без остатка, окончательность `CONFIRMED`/`CANCELLED`

## 3. Операции

- [ ] 3.1 Реализовать `reserve` (валидация, дубли строк суммой, атомарность, события `RESERVE`); проверить тестами все сценарии спецификации, включая «ничего не изменилось при ошибке»
- [ ] 3.2 Реализовать `confirm` (`ISSUE` с `ref`, затем `RESERVE_CONFIRM`, ошибки статусов, нулевой `available`); проверить тестами, включая дубли строк и `adjust` ниже резерва
- [ ] 3.3 Реализовать `cancel` (идемпотентность, истёкший, подтверждённый) и `extend`; проверить тестами и отсутствием лишних событий журнала
- [ ] 3.4 Ограничить `issue` и `transfer` значением `available`; проверить тестами расход при активном и истёкшем резерве

## 4. Завершение

- [ ] 4.1 Запустить `python -m pytest -q`: старые тесты проходят без изменений, `git diff` не затрагивает `cli.py`, `reports.py` и существующие тесты
- [ ] 4.2 Сверить публичный API реализации с proposal и specs (имена, сигнатуры, порядок параметров, поля, значения enum, `DEFAULT_RESERVATION_TTL`, события и их поля) и исправить расхождения
