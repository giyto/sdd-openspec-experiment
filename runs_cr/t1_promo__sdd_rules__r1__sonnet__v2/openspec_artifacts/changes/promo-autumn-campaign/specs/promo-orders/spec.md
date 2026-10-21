## MODIFIED Requirements

### Requirement: Необязательный код в OrderService
`OrderService` SHALL принимать необязательный `promos: PromoRegistry | None`, а `quote(cart, promo_code=None, *, customer_id=None)` и `place_order(cart, promo_code=None, *, customer_id=None)` — необязательный код и необязательный именованный `customer_id: str | None`. Вызовы `quote(cart)` и `place_order(cart)` SHALL работать как раньше и давать прежние суммы. Без реестра любой непустой код SHALL быть неизвестным (`UnknownPromoCodeError`). `customer_id`, отличный от `None` и не строка, SHALL давать `ValidationError`.

#### Scenario: Без реестра
- **WHEN** сервис создан без `promos`, вызывается `quote(cart, "SUMMER10")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Старые вызовы
- **WHEN** вызываются `quote(cart)`, `quote(cart, "SUMMER10")`, `place_order(cart)` без `customer_id`
- **THEN** результат совпадает с прежним

#### Scenario: customer_id только именованный
- **WHEN** `customer_id` передаётся третьим позиционным аргументом
- **THEN** выбрасывается `TypeError`

### Requirement: Порядок проверок при quote и place_order
Код SHALL нормализоваться (как все вводимые людьми коды) и проверяться по порядку: существование, срок действия, общий лимит, лимит на клиента (через реестр, с переданным `customer_id`, который не нормализуется), затем условия заказа (расчёт итогов). Время SHALL браться только от часов, внедрённых в реестр. Код с `max_uses_per_customer` без `customer_id`, как и код, лимит которого исчерпан этим клиентом, SHALL давать `PromoConditionsError` и в `quote`, и в `place_order`. Если промокод не передан (или передана пустая строка), `customer_id` SHALL NOT влиять на расчёт.

#### Scenario: Код в другом регистре
- **WHEN** вызывается `quote(cart, " summer10 ")` для зарегистрированного `SUMMER10`
- **THEN** скидка применена так же, как для `"SUMMER10"`

#### Scenario: Заказ не подходит
- **WHEN** код действует, но сумма участвующих товаров меньше минимальной
- **THEN** выбрасывается `PromoConditionsError`, заказ не сохранён

#### Scenario: Лимит на клиента без customer_id
- **WHEN** у кода `max_uses_per_customer=1`, вызывается `quote(cart, "CODE")` или `place_order(cart, "CODE")`
- **THEN** выбрасывается `PromoConditionsError`, заказ не сохранён, счётчики не изменились

#### Scenario: Клиент исчерпал лимит
- **WHEN** клиент `"u1"` оформил заказ с кодом `max_uses_per_customer=1`
- **THEN** `quote(cart, "CODE", customer_id="u1")` и повторный `place_order` для него выбрасывают `PromoConditionsError`
- **AND** `place_order(cart, "CODE", customer_id="u2")` проходит

#### Scenario: Бесплатная доставка через сервис
- **WHEN** вызывается `quote(cart, "SHIP")` для действующего кода `FREE_SHIPPING`
- **THEN** в итогах `shipping` равно `0.00`, а `shipping_discount` равно сэкономленной доставке

### Requirement: Использование засчитывается при успешном place_order
`place_order` с кодом SHALL сохранить заказ с итогами со скидкой, `Order.promo_code`, равным нормализованному коду, и `Order.customer_id`, равным переданному `customer_id`, и увеличить общий счётчик и счётчик клиента (если `customer_id` задан) на один — только после успешного оформления. Любая ошибка (неизвестный, просроченный, исчерпанный код, исчерпанный лимит на клиента, неподходящий заказ, пустая корзина) SHALL оставлять счётчики и хранилище заказов без изменений. Заказ без кода имеет `promo_code` равный `None`; `Order.customer_id` запоминается в заказе и без кода (`None`, если не передан). Поле `Order.customer_id: str | None` SHALL быть добавлено последним, со значением по умолчанию `None`.

#### Scenario: Лимит достигнут оформлением
- **WHEN** у кода `max_uses=1`, первый `place_order` успешен
- **THEN** `uses` равен 1, второй `place_order` с этим кодом выбрасывает `PromoConditionsError`

#### Scenario: Неудачная попытка
- **WHEN** `place_order` падает с `PromoConditionsError` из-за минимальной суммы
- **THEN** `uses` не изменился и новых заказов в хранилище нет

#### Scenario: Заказ помнит клиента
- **WHEN** выполняется `place_order(cart, "CODE", customer_id="u1")`
- **THEN** `order.customer_id` равен `"u1"`, `uses("CODE", "u1")` равен 1, `uses("CODE")` равен 1

#### Scenario: Заказ без клиента
- **WHEN** выполняется `place_order(cart)`
- **THEN** `order.customer_id` равен `None`

### Requirement: Отмена заказа возвращает использование
`cancel` SHALL после успешной отмены вернуть использование кода заказа (общий счётчик и счётчик клиента заказа, если у заказа есть `customer_id`) только если отмена произошла в течение 24 часов с момента оформления: возврат делается, когда `now - order.created_at < 24 часа`, где `now` — время часов `OrderService`, а `created_at` — момент оформления. Интервал полуоткрытый: при ровно 24 часах и позже использование не возвращается («сгорает»), отмена при этом всё равно проходит и статус становится `CANCELLED`. Заказ без кода счётчики не затрагивает. Отмена уже отменённого заказа по-прежнему даёт `InvalidOrderStateError` и счётчики не меняет.

#### Scenario: Переоформление
- **WHEN** код с `max_uses=1` использован, заказ отменён через 1 час
- **THEN** `uses` равен 0 и новый `place_order` с этим кодом проходит

#### Scenario: Повторная отмена
- **WHEN** заказ отменяют второй раз
- **THEN** выбрасывается `InvalidOrderStateError`, счётчик не уменьшается повторно

#### Scenario: Отмена за секунду до границы
- **WHEN** заказ отменён через 23 часа 59 минут 59 секунд после оформления
- **THEN** использование возвращено

#### Scenario: Отмена ровно через 24 часа
- **WHEN** заказ отменён ровно через 24 часа после оформления
- **THEN** заказ отменён, использование не возвращено, `uses` не уменьшился

#### Scenario: Отмена позже 24 часов
- **WHEN** заказ отменён через 25 часов
- **THEN** заказ отменён, использование сгорело, повторный `place_order` по коду с `max_uses=1` выбрасывает `PromoConditionsError`

#### Scenario: Возврат использования клиента
- **WHEN** клиент `"u1"` оформил заказ с кодом `max_uses_per_customer=1` и отменил его через 1 час
- **THEN** `uses(code, "u1")` равен 0 и клиент снова может применить код

#### Scenario: Сгоревшее использование клиента
- **WHEN** клиент `"u1"` отменил такой заказ через 24 часа или позже
- **THEN** `uses(code, "u1")` остаётся равным 1 и код ему больше не подходит

#### Scenario: Часы сервиса, а не реестра
- **WHEN** часы `OrderService` и часы `PromoRegistry` — разные объекты
- **THEN** окно в 24 часа определяется только часами `OrderService`
