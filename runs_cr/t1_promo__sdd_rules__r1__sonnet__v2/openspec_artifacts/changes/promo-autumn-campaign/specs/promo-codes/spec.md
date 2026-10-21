## MODIFIED Requirements

### Requirement: Модель PromoCode и её инварианты
`PromoCode` (`shop/promo.py`) SHALL быть неизменяемой моделью с полями `code`, `kind: DiscountKind`, `value`, `min_order_amount` (по умолчанию `Decimal("0.00")`), `starts_at`, `expires_at`, `max_uses` (по умолчанию `None`), `excluded_categories` (по умолчанию пустой `frozenset`), а затем — новыми последними полями `max_discount: Decimal | None = None` и `max_uses_per_customer: int | None = None`. `DiscountKind` SHALL иметь значения `PERCENT`, `FIXED` и `FREE_SHIPPING`. Код SHALL нормализоваться (обрезка пробелов по краям, верхний регистр). Нарушение любого инварианта SHALL давать `ValidationError`:
- код после нормализации непустой;
- `PERCENT`: `value` — `Decimal` в диапазоне `(0, 100]`; `FIXED`: `value` — `Decimal` больше 0 не более чем с двумя знаками после запятой; `FREE_SHIPPING`: `value` — `Decimal`, равный `Decimal("0")`;
- `min_order_amount` — `Decimal` не меньше 0, не более двух знаков после запятой;
- `starts_at` и `expires_at` — aware `datetime` или `None`; если заданы оба, `starts_at` строго раньше `expires_at`;
- `max_uses` — `None` или целое `>= 1` (не `bool`);
- `excluded_categories` — `frozenset` из `Category`;
- `max_discount` — `None` или `Decimal` строго больше 0 не более чем с двумя знаками после запятой; значение, отличное от `None`, допустимо только у `PERCENT`;
- `max_uses_per_customer` — `None` или целое `>= 1` (не `bool`).

Прежние позиционные и именованные создания `PromoCode` без новых полей SHALL работать как раньше.

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode(code="  summer10 ", ...)`
- **THEN** `code` равен `"SUMMER10"`

#### Scenario: Пустой код отвергается
- **WHEN** создаётся `PromoCode` с кодом `"   "`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Процент вне диапазона
- **WHEN** `PERCENT` создаётся со значением `0` или `100.01`
- **THEN** выбрасывается `ValidationError`
- **AND** значение `100` допустимо

#### Scenario: Некорректный интервал или лимит
- **WHEN** `starts_at` не раньше `expires_at`, либо дата без часового пояса, либо `max_uses` равен `0`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Бесплатная доставка с нулевым значением
- **WHEN** создаётся `PromoCode("SHIP", DiscountKind.FREE_SHIPPING, Decimal("0"))`
- **THEN** код создан

#### Scenario: Бесплатная доставка с ненулевым значением
- **WHEN** `FREE_SHIPPING` создаётся со значением `Decimal("10")` или со значением не типа `Decimal`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Потолок процентной скидки
- **WHEN** `PERCENT` создаётся с `max_discount=Decimal("500")`
- **THEN** код создан
- **WHEN** `max_discount` равен `0`, отрицателен, не `Decimal` или имеет больше двух знаков после запятой
- **THEN** выбрасывается `ValidationError`

#### Scenario: Потолок у непроцентного кода
- **WHEN** `FIXED` или `FREE_SHIPPING` создаётся с любым `max_discount`, отличным от `None`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Лимит на клиента
- **WHEN** `max_uses_per_customer` равен `1` или `None`
- **THEN** код создан
- **WHEN** `max_uses_per_customer` равен `0`, `-1`, `True` или не целое
- **THEN** выбрасывается `ValidationError`

### Requirement: Поиск кода и порядок проверок
`resolve(code, customer_id=None)` SHALL нормализовать вводимый код (но не `customer_id`) и возвращать `PromoCode`, если он существует, действует в текущий момент и не исчерпан. Проверки идут строго по порядку: существование (`UnknownPromoCodeError`), срок действия (`PromoExpiredError`), общий лимит `max_uses` (`PromoConditionsError`), затем лимит на клиента (`PromoConditionsError`). Если у кода задан `max_uses_per_customer`, то при `customer_id` равном `None` код SHALL NOT применяться (`PromoConditionsError`), а при заданном `customer_id` — также `PromoConditionsError`, когда этот клиент уже использовал код не меньше `max_uses_per_customer` раз. `customer_id` — внутренний идентификатор учётной записи, он сравнивается как есть (без обрезки пробелов и без смены регистра); у кода без `max_uses_per_customer` `customer_id` на результат `resolve` не влияет. Текущее время SHALL браться только у внедрённых часов. Срок действия — полуоткрытый интервал `[starts_at, expires_at)`; граница `None` означает отсутствие ограничения. До `starts_at` код тоже даёт `PromoExpiredError`. `resolve("")` и `resolve` от пробельной строки SHALL давать `UnknownPromoCodeError`.

#### Scenario: Регистронезависимый поиск
- **WHEN** зарегистрирован `"SUMMER10"`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот `PromoCode`

#### Scenario: Границы срока
- **WHEN** текущее время равно `starts_at`
- **THEN** код действует
- **WHEN** текущее время равно `expires_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Просроченный и исчерпанный код
- **WHEN** код одновременно просрочен и исчерпан
- **THEN** выбрасывается `PromoExpiredError`, а не `PromoConditionsError`

#### Scenario: Лимит исчерпан
- **WHEN** число использований равно `max_uses`
- **THEN** `resolve` выбрасывает `PromoConditionsError`

#### Scenario: Неизвестный и пустой код
- **WHEN** вызывается `resolve("NOPE")` или `resolve("")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Лимит на клиента без customer_id
- **WHEN** у кода `max_uses_per_customer=1`, вызывается `resolve("CODE")` или `resolve("CODE", None)`
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Клиент исчерпал свой лимит
- **WHEN** у кода `max_uses_per_customer=1`, клиент `"u1"` уже использовал код один раз
- **THEN** `resolve("CODE", "u1")` выбрасывает `PromoConditionsError`
- **AND** `resolve("CODE", "u2")` возвращает код

#### Scenario: Идентификатор клиента сравнивается как есть
- **WHEN** клиент `"u1"` исчерпал лимит
- **THEN** `resolve("CODE", "U1")` и `resolve("CODE", " u1")` возвращают код, как для другого клиента

#### Scenario: Просроченный код важнее лимита на клиента
- **WHEN** код просрочен и вызывается без `customer_id`, хотя задан `max_uses_per_customer`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Код без лимита на клиента
- **WHEN** у кода `max_uses_per_customer` равен `None`, вызывается `resolve("CODE")` без `customer_id`
- **THEN** код возвращается

### Requirement: Счётчик использований
`uses(code, customer_id=None)` SHALL возвращать число учтённых использований кода (для нового кода `0`), нормализуя ввод; с заданным `customer_id` — сколько раз код использовал именно этот клиент (для клиента без использований `0`). Для неизвестного кода SHALL выбрасываться `UnknownPromoCodeError`. Использования клиентов SHALL учитываться для любого кода, независимо от наличия `max_uses_per_customer`; каждое успешное использование увеличивает и общий счётчик, и счётчик клиента (если `customer_id` задан). Использование SHALL учитываться только при успешном оформлении заказа (см. `promo-orders`); `resolve` и `uses` счётчики не меняют. Ни один счётчик SHALL NOT уходить ниже нуля.

#### Scenario: Начальное значение
- **WHEN** код только что добавлен
- **THEN** `uses(code)` равен `0`, и повторные `resolve` его не меняют

#### Scenario: Счётчик клиента
- **WHEN** клиент `"u1"` использовал код дважды, клиент `"u2"` — один раз
- **THEN** `uses(code, "u1")` равен `2`, `uses(code, "u2")` равен `1`, `uses(code)` равен `3`
- **AND** `uses(code, "u3")` равен `0`

#### Scenario: Неизвестный код со счётчиком клиента
- **WHEN** вызывается `uses("NOPE", "u1")`
- **THEN** выбрасывается `UnknownPromoCodeError`
