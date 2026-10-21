## MODIFIED Requirements

### Requirement: Совместимость без промокода
`OrderService.quote(cart)` и `OrderService.place_order(cart)` без кода SHALL работать как раньше; `Order.promo_code` и `Order.customer_id` SHALL быть `None`, если не переданы. Сигнатуры: `quote(cart, promo_code=None, *, customer_id: str | None = None)`, `place_order(cart, promo_code=None, *, customer_id: str | None = None)`; `Order` получает поле `customer_id: str | None = None` в конце. `OrderService(..., promos: PromoRegistry | None = None)` без реестра SHALL считать любой непустой код неизвестным.

#### Scenario: Заказ без кода
- **WHEN** вызывается `place_order(cart)`
- **THEN** суммы прежние, `order.promo_code is None`, `order.customer_id is None`, `order.total.discount == Decimal("0.00")`, `order.total.shipping_discount == Decimal("0.00")`

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos`, вызывается `quote(cart, "SUMMER")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Клиент без кода
- **WHEN** вызывается `place_order(cart, customer_id="u1")`
- **THEN** `order.customer_id == "u1"`, `order.promo_code is None`

### Requirement: Расчёт с промокодом
При непустом `promo_code` сервис SHALL получить код через `PromoRegistry.resolve(code, customer_id)` (с нормализацией кода) и применить его в расчёте итогов. Порядок проверок: пустая корзина (`EmptyCartError`); существует ли код (`UnknownPromoCodeError`); действует ли (`PromoExpiredError`); общий лимит (`PromoConditionsError`); лимит на клиента (`PromoConditionsError`); условия заказа (`PromoConditionsError`). `quote` SHALL NOT менять счётчики использований.

#### Scenario: Ввод в другом регистре
- **WHEN** зарегистрирован `SUMMER10`, вызывается `quote(cart, " summer10 ")`
- **THEN** скидка применена, счётчик `uses("SUMMER10")` не изменился

#### Scenario: Просрочен и не подходит заказ
- **WHEN** код просрочен, а минимальная сумма не набрана
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Лимит на клиента без customer_id
- **WHEN** у кода `max_uses_per_customer=1`, вызывается `quote(cart, code)` без `customer_id`
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Лимит на клиента исчерпан
- **WHEN** клиент `"u1"` оформил заказ с кодом, у которого `max_uses_per_customer=1`
- **THEN** `quote(cart, code, customer_id="u1")` и `place_order(...)` выбрасывают `PromoConditionsError`, а для `"u2"` расчёт успешен

### Requirement: Оформление заказа засчитывает использование
`place_order(cart, promo_code, customer_id=...)` с применённым кодом SHALL сохранить в `Order.promo_code` нормализованный код, в `Order.customer_id` переданный идентификатор как есть, и увеличить общий счётчик `uses` и (при заданном `customer_id`) счётчик клиента на 1 ровно при успешном оформлении. Любая ошибка (неизвестный, просроченный, исчерпанный код, неподходящий заказ, пустая корзина) SHALL оставлять счётчики, хранилище заказов и нумерацию без изменений.

#### Scenario: Успешный заказ
- **WHEN** `place_order(cart, "summer10", customer_id="u1")` успешен
- **THEN** `order.promo_code == "SUMMER10"`, `order.customer_id == "u1"`, `uses("SUMMER10")` и `uses("SUMMER10", "u1")` увеличились на 1, `order.total.discount` равна скидке расчёта

#### Scenario: Неудачная попытка
- **WHEN** `place_order` падает с `PromoConditionsError` из-за минимальной суммы
- **THEN** `uses` не изменился, заказ не сохранён

#### Scenario: Последнее использование
- **WHEN** у кода `max_uses=1`, первый `place_order` успешен
- **THEN** второй `place_order` и `quote` с этим кодом выбрасывают `PromoConditionsError`

### Requirement: Отмена возвращает использование
`cancel(order_id)` SHALL всегда переводить заказ в `CANCELLED`, а использование промокода возвращать (общий счётчик и счётчик клиента заказа уменьшаются на 1, не ниже 0, даже если срок кода истёк) только если отмена произошла в течение 24 часов с момента оформления: `created_at <= now < created_at + 24 ч`, где `now` берётся из часов `OrderService`. При `now >= created_at + 24 ч` (в том числе ровно через 24 часа) использование не возвращается и сгорает. Для заказа без кода счётчики не меняются. Повторная отмена (`InvalidOrderStateError`) SHALL NOT менять счётчики.

#### Scenario: Переоформление после отмены
- **WHEN** заказ с кодом `max_uses=1` отменён через 23 часа 59 минут
- **THEN** `uses == 0` и новый `place_order` с этим кодом успешен

#### Scenario: Ровно через 24 часа
- **WHEN** заказ отменён ровно через 24 часа после `created_at`
- **THEN** статус `CANCELLED`, `uses` не изменился

#### Scenario: Отмена позже
- **WHEN** заказ с кодом `max_uses=1` отменён через 25 часов
- **THEN** `uses == 1`, новый `place_order` с этим кодом выбрасывает `PromoConditionsError`

#### Scenario: Возврат по клиенту
- **WHEN** заказ клиента `"u1"` с `max_uses_per_customer=1` отменён в пределах 24 часов
- **THEN** `uses(code, "u1") == 0` и клиент снова может использовать код

#### Scenario: Повторная отмена
- **WHEN** отменённый заказ отменяют ещё раз
- **THEN** выбрасывается `InvalidOrderStateError`, счётчик не меняется
