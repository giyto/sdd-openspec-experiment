## MODIFIED Requirements

### Requirement: Инварианты PromoCode
`PromoCode` (`shop/promo.py`) SHALL быть `@dataclass(frozen=True)` с полями `code`, `kind: DiscountKind`, `value: Decimal`, `min_order_amount: Decimal = Decimal("0.00")`, `starts_at: datetime | None = None`, `expires_at: datetime | None = None`, `max_uses: int | None = None`, `excluded_categories: frozenset[Category] = frozenset()`, `max_discount: Decimal | None = None`, `max_uses_per_customer: int | None = None`; прежние поля остаются без изменений, новые стоят в конце. `DiscountKind` SHALL быть `StrEnum` со значениями `PERCENT`, `FIXED` и `FREE_SHIPPING`. Код SHALL нормализоваться при создании (обрезка пробелов по краям, верхний регистр). Нарушение любого инварианта MUST приводить к `ValidationError`: пустой (после нормализации) код; `kind` не `DiscountKind`; `value` не `Decimal`; для `PERCENT` значение вне `(0, 100]`; для `FIXED` значение `<= 0` или более двух знаков после запятой; для `FREE_SHIPPING` значение, не равное `Decimal("0")`; `min_order_amount` не `Decimal`, отрицательная или с более чем двумя знаками; naive `datetime` в `starts_at`/`expires_at`; `starts_at` не раньше `expires_at` (если заданы оба); `max_uses` не `int` (в том числе `bool`) или `< 1`; `max_uses_per_customer` не `None` и не `int` (в том числе `bool`) или `< 1`; `max_discount` заданный (не `None`) у `kind`, отличного от `PERCENT`; `max_discount` не `Decimal`, не конечный или `<= 0`; элементы `excluded_categories` не `Category`.

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode(code="  summer10 ", kind=DiscountKind.PERCENT, value=Decimal("10"))`
- **THEN** `promo.code == "SUMMER10"`

#### Scenario: Некорректные значения отвергаются
- **WHEN** создаётся промокод с пустым кодом `"   "`, либо `PERCENT` со значением `0` или `100.01`, либо `FIXED` со значением `0` или `10.001`, либо `max_uses=0`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Граничные допустимые значения
- **WHEN** создаётся `PERCENT` со значением `100` или `0.5`, либо `FIXED` со значением `0.01`, либо `max_uses=1`, либо `max_uses_per_customer=1`
- **THEN** объект создаётся без ошибки

#### Scenario: Некорректный интервал действия
- **WHEN** `starts_at == expires_at`, или `starts_at > expires_at`, или любая из границ naive
- **THEN** выбрасывается `ValidationError`

#### Scenario: Промокод на бесплатную доставку
- **WHEN** создаётся `PromoCode(code="SHIP", kind=DiscountKind.FREE_SHIPPING, value=Decimal("0"))`
- **THEN** объект создаётся без ошибки

#### Scenario: Бесплатная доставка с ненулевым значением
- **WHEN** создаётся `FREE_SHIPPING` со значением `Decimal("5")` или `Decimal("0.01")`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Потолок скидки у процентного кода
- **WHEN** `max_discount=Decimal("500")` задан у `PERCENT`
- **THEN** объект создаётся без ошибки

#### Scenario: Потолок скидки у другого вида или неположительный
- **WHEN** `max_discount=Decimal("500")` задан у `FIXED` или `FREE_SHIPPING`, либо `max_discount` равен `Decimal("0")` или отрицателен у `PERCENT`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Некорректный лимит на клиента
- **WHEN** `max_uses_per_customer` равен `0`, `-1`, `True` или `"1"`
- **THEN** выбрасывается `ValidationError`

### Requirement: Разрешение кода resolve
`PromoRegistry.resolve(code: str, customer_id: str | None = None) -> PromoCode` SHALL нормализовать вводимый код (обрезка пробелов, верхний регистр) и возвращать зарегистрированный `PromoCode`, если код существует, действует в текущий момент, общий лимит не исчерпан и лимит на клиента не нарушен. Время MUST браться только из `Clock`, переданного в конструктор реестра. `customer_id` — внутренний идентификатор учётной записи: MUST сравниваться как есть, без обрезки пробелов и смены регистра. Проверки выполняются строго по порядку, первая сработавшая определяет исключение: (1) код не найден — `UnknownPromoCodeError`; (2) текущий момент вне полуоткрытого интервала `[starts_at, expires_at)` (акция ещё не началась или уже закончилась; граница `None` — без ограничения) — `PromoExpiredError`; (3) `max_uses` задан и `uses(code) >= max_uses` — `PromoConditionsError`; (4) `max_uses_per_customer` задан и `customer_id` равен `None` либо `uses(code, customer_id) >= max_uses_per_customer` — `PromoConditionsError`. Если `max_uses_per_customer` не задан, `customer_id` на результат не влияет. `resolve` MUST NOT менять счётчики. Пустая строка и строка из пробелов в `code` MUST давать `UnknownPromoCodeError`. Нестроковый `code` или `customer_id`, не являющийся `None` или строкой, MUST давать `ValidationError`. Вызов `resolve(code)` без `customer_id` работает как прежде.

#### Scenario: Поиск без учёта регистра и пробелов
- **WHEN** зарегистрирован `SUMMER10`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот `PromoCode`

#### Scenario: Неизвестный и пустой код
- **WHEN** вызывается `resolve("NOPE")`, `resolve("")` или `resolve("   ")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Начало срока включительно
- **WHEN** текущее время равно `starts_at`
- **THEN** `resolve` успешен

#### Scenario: Конец срока исключительно
- **WHEN** текущее время равно `expires_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** выбрасывается `PromoExpiredError` (отдельного исключения для «ещё не началась» нет)

#### Scenario: Порядок проверок
- **WHEN** срок кода истёк и одновременно исчерпан лимит
- **THEN** выбрасывается `PromoExpiredError`, а не `PromoConditionsError`

#### Scenario: Исчерпанный лимит
- **WHEN** `max_uses=2` и `uses(code) == 2`
- **THEN** `resolve` выбрасывает `PromoConditionsError`; при `uses(code) == 1` возвращает промокод

#### Scenario: Время из внедрённых часов
- **WHEN** `FixedClock` реестра переведён за `expires_at`
- **THEN** тот же `resolve` начинает выбрасывать `PromoExpiredError`

#### Scenario: Лимит на клиента без customer_id
- **WHEN** у кода `max_uses_per_customer=1`, вызывается `resolve(code)` или `resolve(code, None)`
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Лимит на клиента исчерпан
- **WHEN** `max_uses_per_customer=1`, клиент `"u1"` уже использовал код один раз
- **THEN** `resolve(code, "u1")` выбрасывает `PromoConditionsError`, а `resolve(code, "u2")` возвращает промокод

#### Scenario: customer_id сравнивается как есть
- **WHEN** `max_uses_per_customer=1`, клиент `"User-1"` использовал код
- **THEN** `resolve(code, "user-1")` и `resolve(code, "User-1 ")` успешны, `resolve(code, "User-1")` выбрасывает `PromoConditionsError`

#### Scenario: Без лимита на клиента customer_id не нужен
- **WHEN** у кода `max_uses_per_customer=None`
- **THEN** `resolve(code)` и `resolve(code, "u1")` успешны независимо от прежних использований клиентом

#### Scenario: Некорректный тип customer_id
- **WHEN** вызывается `resolve(code, 123)`
- **THEN** выбрасывается `ValidationError`

### Requirement: Счётчик использований
`PromoRegistry.uses(code: str, customer_id: str | None = None) -> int` SHALL возвращать число использований кода (код нормализуется так же, как в `resolve`). Без `customer_id` результат — общее число использований кода; с `customer_id` — сколько раз код использовал этот клиент (`customer_id` сравнивается как есть). Для незарегистрированного кода `uses` MUST выбрасывать `UnknownPromoCodeError`; `customer_id`, не являющийся `None` или строкой, — `ValidationError`. Клиентский счётчик MUST вестись для любого заказа с `customer_id`, независимо от того, задан ли у кода `max_uses_per_customer`; клиент без использований даёт `0`. Счётчики MUST увеличиваться только при успешном оформлении заказа с кодом (общий — всегда, клиентский — если у заказа есть `customer_id`) и уменьшаться на один при отмене такого заказа только тогда, когда использование возвращается (см. `order-promos`), но никогда не опускаться ниже нуля; изменение счётчиков не зависит от срока действия кода. Регистрация использования и его возврат выполняются сервисом заказов через дополнительные методы реестра, не входящие в API тикета.

#### Scenario: Новый код не использован
- **WHEN** код только что добавлен
- **THEN** `uses(code) == 0` и `uses(code, "u1") == 0`

#### Scenario: Неизвестный код в uses
- **WHEN** вызывается `uses("NOPE")` или `uses("NOPE", "u1")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Счётчик по клиентам
- **WHEN** клиент `"u1"` оформил заказ с кодом дважды, клиент `"u2"` один раз, ещё один заказ оформлен без `customer_id`
- **THEN** `uses(code) == 4`, `uses(code, "u1") == 2`, `uses(code, "u2") == 1`, `uses(code, "u3") == 0`
