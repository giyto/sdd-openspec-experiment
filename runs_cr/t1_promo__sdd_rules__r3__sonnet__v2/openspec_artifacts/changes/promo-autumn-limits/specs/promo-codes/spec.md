## MODIFIED Requirements

### Requirement: Инварианты PromoCode
`PromoCode` SHALL быть неизменяемым объектом с полями `code`, `kind` (`DiscountKind.PERCENT`, `DiscountKind.FIXED` или `DiscountKind.FREE_SHIPPING`), `value`, `min_order_amount` (по умолчанию `Decimal("0.00")`), `starts_at`, `expires_at`, `max_uses` (по умолчанию `None`), `excluded_categories` (по умолчанию пустой `frozenset`), а в конце `max_discount` (по умолчанию `None`) и `max_uses_per_customer` (по умолчанию `None`). Нарушение любого инварианта SHALL приводить к `ValidationError`: пустой после нормализации `code`; `value` не `Decimal`; для `PERCENT` `value` вне `(0, 100]`; для `FIXED` `value <= 0` или более двух знаков после запятой; для `FREE_SHIPPING` `value` не равно `Decimal("0")`; `min_order_amount` отрицательная или более двух знаков; `starts_at`/`expires_at` не aware; `starts_at` не раньше `expires_at` (когда заданы оба); `max_uses` не `None` и не целое `>= 1` (`bool` не допускается); `max_uses_per_customer` не `None` и не целое `>= 1` (`bool` не допускается); `max_discount` не `None` при виде кода не `PERCENT`, либо не `Decimal`, не конечный, `<= 0` или с более чем двумя знаками; `excluded_categories` содержит не `Category`. `code` SHALL храниться в нормализованном виде (без пробелов по краям, в верхнем регистре).

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode` с `code="  summer10 "`, `kind=DiscountKind.PERCENT`, `value=Decimal("10")`
- **THEN** `promo.code == "SUMMER10"`

#### Scenario: Процент вне диапазона
- **WHEN** создаётся процентный код со `value` равным `0` или `100.01`
- **THEN** выбрасывается `ValidationError`; при `value == 100` объект создаётся

#### Scenario: Некорректный интервал
- **WHEN** `starts_at` равен `expires_at` или позже него
- **THEN** выбрасывается `ValidationError`

#### Scenario: Некорректный лимит
- **WHEN** `max_uses` или `max_uses_per_customer` равен `0`, `-1` или `True`
- **THEN** выбрасывается `ValidationError`; `None` и `1` допустимы

#### Scenario: Бесплатная доставка с ненулевым значением
- **WHEN** создаётся код `FREE_SHIPPING` со `value=Decimal("5")`
- **THEN** выбрасывается `ValidationError`; при `value=Decimal("0")` объект создаётся

#### Scenario: Потолок у не процентного кода
- **WHEN** `max_discount=Decimal("100")` задан у `FIXED` или `FREE_SHIPPING`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Некорректный потолок процента
- **WHEN** у `PERCENT` `max_discount` равен `Decimal("0")`, `Decimal("-1")` или `Decimal("1.005")`
- **THEN** выбрасывается `ValidationError`; `Decimal("0.01")` и `None` допустимы

### Requirement: Поиск и проверка кода через resolve
`resolve(code, customer_id=None)` SHALL нормализовать `code` (обрезка пробелов, верхний регистр) и проверять строго по порядку: (1) код существует, иначе `UnknownPromoCodeError`; (2) код действует в текущий момент по часам реестра, иначе `PromoExpiredError`; (3) общий лимит `max_uses` не исчерпан, иначе `PromoConditionsError`; (4) если у кода задан `max_uses_per_customer`: `customer_id` передан и клиент использовал код меньше этого числа раз, иначе `PromoConditionsError`. При успехе SHALL возвращаться `PromoCode`. Интервал действия полуоткрытый `[starts_at, expires_at)`; граница `None` означает отсутствие ограничения. Время SHALL браться только из часов, переданных реестру. Не-строковый `code` и `customer_id`, не являющийся `str` или `None`, SHALL приводить к `ValidationError`. `customer_id` SHALL сравниваться как есть, без нормализации. `resolve("")` и `resolve("   ")` SHALL выбрасывать `UnknownPromoCodeError`. Код без `max_uses_per_customer` SHALL разрешаться и без `customer_id`.

#### Scenario: Ввод в другом регистре и с пробелами
- **WHEN** зарегистрирован `SUMMER10`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот код

#### Scenario: Граница начала включительна
- **WHEN** текущее время равно `starts_at`
- **THEN** `resolve` возвращает код

#### Scenario: Граница конца исключительна
- **WHEN** текущее время равно `expires_at`
- **THEN** `resolve` выбрасывает `PromoExpiredError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** `resolve` выбрасывает `PromoExpiredError` (отдельного исключения нет)

#### Scenario: Порядок проверок
- **WHEN** код просрочен и при этом его лимит исчерпан
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Исчерпанный лимит
- **WHEN** у кода `max_uses=2` и `uses(code) == 2`
- **THEN** `resolve` выбрасывает `PromoConditionsError`

#### Scenario: Пустой ввод
- **WHEN** вызывается `resolve("")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Лимит на клиента без customer_id
- **WHEN** у кода `max_uses_per_customer=1`, вызывается `resolve(code)`
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Клиент исчерпал свой лимит
- **WHEN** у кода `max_uses_per_customer=1`, клиент `"u1"` уже использовал код
- **THEN** `resolve(code, "u1")` выбрасывает `PromoConditionsError`, а `resolve(code, "u2")` возвращает код

#### Scenario: Идентификатор клиента сравнивается как есть
- **WHEN** клиент `"u1"` исчерпал лимит
- **THEN** `resolve(code, "U1")` и `resolve(code, "u1 ")` возвращают код

### Requirement: Счётчик использований
`uses(code, customer_id=None)` SHALL возвращать число засчитанных использований кода (изначально `0`), нормализуя `code` как `resolve`; с `customer_id` SHALL возвращаться число использований кода этим клиентом (`0` для клиента без использований); для неизвестного кода SHALL выбрасываться `UnknownPromoCodeError`. `resolve` и `uses` SHALL NOT менять счётчики. Реестр SHALL дополнительно предоставлять `consume(code, customer_id=None)` (увеличить общий счётчик на 1 и, если задан `customer_id`, счётчик клиента) и `release(code, customer_id=None)` (уменьшить так же, но не ниже 0), которыми пользуется только оформление и отмена заказа.

#### Scenario: Свежий код
- **WHEN** код только что добавлен
- **THEN** `uses(code) == 0` и `uses(code, "u1") == 0`

#### Scenario: Чтение не меняет счётчик
- **WHEN** несколько раз вызываются `resolve` и `uses`
- **THEN** `uses(code)` не изменяется

#### Scenario: Счётчик по клиентам
- **WHEN** `consume(code, "u1")` вызван дважды, `consume(code, "u2")` один раз
- **THEN** `uses(code) == 3`, `uses(code, "u1") == 2`, `uses(code, "u2") == 1`
