## MODIFIED Requirements

### Requirement: Промокод в quote и place_order
`quote` и `place_order` SHALL принимать необязательный `promo_code` (строка) и необязательный именованный `customer_id` (строка, по умолчанию `None`). `None`, пустая строка и строка из одних пробелов в `promo_code` MUST означать «без промокода» и давать тот же результат, что и вызов без аргумента. Иначе код ищется в реестре сервиса так же, как в `resolve` (нормализация, порядок проверок, включая лимит на клиента по переданному `customer_id`), затем применяются условия заказа. Если у сервиса нет реестра, любой непустой код MUST давать `UnknownPromoCodeError`. `customer_id` — внутренний идентификатор учётной записи, он передаётся и сравнивается как есть (без обрезки пробелов и смены регистра); не строка или пустая строка — `ValidationError`, независимо от наличия промокода. Код с лимитом на клиента, применяемый без `customer_id`, MUST давать `PromoConditionsError`; исчерпанный клиентом лимит — тоже `PromoConditionsError`. Вызовы `quote(cart)`, `place_order(cart)`, `quote(cart, code)` и `place_order(cart, code)` работают как раньше.

#### Scenario: Пустое поле формы
- **WHEN** `quote(cart, "")` или `place_order(cart, "   ")`
- **THEN** ошибки нет, скидка `0.00`, `Order.promo_code` равен `None`

#### Scenario: Код в произвольном регистре
- **WHEN** `quote(cart, " summer10 ")` и в реестре есть `SUMMER10`
- **THEN** скидка применена

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos` и передан код `SUMMER10`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Порядок ошибок
- **WHEN** код существует, просрочен, а корзина не проходит условия
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Условия заказа
- **WHEN** код действует и лимит не исчерпан, но минимальная сумма не набрана
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Лимит на клиента без customer_id
- **WHEN** у кода `max_uses_per_customer=1` и вызывается `quote(cart, "CODE")` или `place_order(cart, "CODE")` без `customer_id`
- **THEN** выбрасывается `PromoConditionsError`, счётчик не меняется

#### Scenario: Клиент исчерпал лимит
- **WHEN** `max_uses_per_customer=1`, клиент `u1` оформил заказ с кодом, затем вызывает `quote(cart, "CODE", customer_id="u1")`
- **THEN** выбрасывается `PromoConditionsError`; для `customer_id="u2"` скидка применяется

#### Scenario: Идентификатор как есть
- **WHEN** клиент `u1` исчерпал лимит и вызывается `quote(cart, "CODE", customer_id="U1")`
- **THEN** скидка применяется (другой клиент)

#### Scenario: Некорректный customer_id
- **WHEN** `quote(cart, customer_id="")` или `place_order(cart, customer_id=5)`
- **THEN** выбрасывается `ValidationError`, заказ не сохранён

#### Scenario: customer_id без промокода
- **WHEN** `place_order(cart, customer_id="u1")`
- **THEN** заказ оформлен, `Order.customer_id == "u1"`, `Order.promo_code` равен `None`

### Requirement: Использование засчитывается только при оформлении
Счётчик использований SHALL увеличиваться на 1 (общий и, если передан `customer_id`, счётчик клиента) только при успешном `place_order` с промокодом. `quote`, `calculate_total` и любая неудачная попытка (ошибка кода, условий, лимита, пустая корзина, любая иная ошибка) MUST NOT менять счётчики. Неудачный `place_order` MUST NOT сохранять заказ. Заказ SHALL хранить в `Order.promo_code` нормализованный код, либо `None`, если кода не было, и в `Order.customer_id` — переданный `customer_id` как есть, либо `None`. Скидка в `Order.total` (включая `shipping_discount`) SHALL совпадать с `quote` для той же корзины и того же состояния.

#### Scenario: Успешное оформление
- **WHEN** `place_order(cart, "summer10", customer_id="u1")` завершился успешно
- **THEN** `uses("SUMMER10")` и `uses("SUMMER10", "u1")` выросли на 1, `order.promo_code == "SUMMER10"`, `order.customer_id == "u1"`

#### Scenario: Расчёт не расходует лимит
- **WHEN** вызван `quote(cart, "SUMMER10", customer_id="u1")`
- **THEN** `uses` общий и клиента не меняются

#### Scenario: Неудачная попытка
- **WHEN** `place_order` с кодом завершается `PromoConditionsError`
- **THEN** `uses` не меняется, заказ не сохранён

#### Scenario: Последнее использование
- **WHEN** `max_uses=1` и первый заказ оформлен
- **THEN** второй `place_order` с этим кодом даёт `PromoConditionsError`

#### Scenario: Лимит на клиента при оформлении
- **WHEN** `max_uses_per_customer=1`, клиент `u1` оформил заказ с кодом
- **THEN** второй `place_order` с этим кодом и `customer_id="u1"` даёт `PromoConditionsError`, заказ не сохранён, а `u2` оформить заказ может

#### Scenario: Бесплатная доставка в заказе
- **WHEN** оформлен заказ с кодом бесплатной доставки
- **THEN** `Order.total.shipping_discount` и остальные суммы совпадают с `quote` для той же корзины

### Requirement: Возврат кода при отмене
`cancel` заказа с промокодом SHALL возвращать использование этого кода (уменьшать на 1 общий счётчик и счётчик клиента заказа, если у заказа есть `customer_id`), только если заказ отменён в течение 24 часов с момента оформления: время отмены берётся из часов сервиса заказов, окно — полуоткрытый интервал `[created_at, created_at + 24 часа)`. Отмена ровно через 24 часа и позже MUST NOT возвращать использование (оно сгорает), но заказ при этом отменяется. Если по часам сервиса отмена оказалась раньше `created_at`, она считается внутри окна. Возврат внутри окна происходит независимо от срока действия кода. Отмена заказа без промокода счётчики не меняет. Повторная отмена (`InvalidOrderStateError`) MUST NOT возвращать код второй раз.

#### Scenario: Переоформление после отмены
- **WHEN** `max_uses=1`, заказ с кодом оформлен и отменён через 1 час
- **THEN** `uses` равен 0 и новый `place_order` с этим кодом успешен

#### Scenario: Повторная отмена
- **WHEN** отменённый заказ отменяется ещё раз
- **THEN** выбрасывается `InvalidOrderStateError`, счётчик не меняется

#### Scenario: Отмена после окончания срока
- **WHEN** срок кода истёк после оформления заказа, затем заказ отменён в пределах 24 часов
- **THEN** счётчик уменьшается на 1

#### Scenario: Отмена за секунду до границы
- **WHEN** заказ отменён через 23 часа 59 минут 59 секунд после оформления
- **THEN** использование возвращено

#### Scenario: Отмена ровно через 24 часа
- **WHEN** заказ отменён ровно через 24 часа после оформления
- **THEN** заказ отменён (`CANCELLED`), использование не возвращено, `uses` не меняется

#### Scenario: Поздняя отмена
- **WHEN** `max_uses=1`, заказ с кодом отменён через 3 дня
- **THEN** заказ отменён, `uses` остаётся 1, новый `place_order` с этим кодом даёт `PromoConditionsError`

#### Scenario: Возврат лимита на клиента
- **WHEN** `max_uses_per_customer=1`, клиент `u1` оформил заказ и отменил его через 2 часа
- **THEN** `uses("CODE", "u1")` равен 0 и клиент может оформить заказ снова

#### Scenario: Поздняя отмена не возвращает лимит клиента
- **WHEN** `max_uses_per_customer=1`, клиент `u1` отменил заказ через 25 часов
- **THEN** `uses("CODE", "u1")` остаётся 1, повторный `place_order` для `u1` даёт `PromoConditionsError`
