## MODIFIED Requirements

### Requirement: Подключение реестра и ввод кода
`OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code: str | None = None, *, customer_id: str | None = None)` и `place_order(cart, promo_code: str | None = None, *, customer_id: str | None = None)` SHALL принимать код как введён человеком, а `customer_id` — только именованным аргументом. Значение `None`, пустая строка или строка из пробелов в `promo_code` означает «без промокода»: результат MUST совпадать с вызовом без кода и не вызывать ошибку. Нестроковый `promo_code`, а также `customer_id`, не являющийся `None` или строкой, MUST давать `ValidationError`. Если непустой код передан, а `promos` не задан, он MUST считаться неизвестным (`UnknownPromoCodeError`). `customer_id` MUST передаваться реестру как есть, без нормализации. Вызовы `quote(cart)` и `place_order(cart)` без кода и без `customer_id` работают как прежде.

#### Scenario: Пустое поле формы
- **WHEN** `quote(cart, "")` или `place_order(cart, "   ")`
- **THEN** скидки нет, ошибки нет, `Order.promo_code is None`

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos`, вызывается `quote(cart, "SUMMER10")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Ввод в другом регистре
- **WHEN** зарегистрирован `SUMMER10`, вызывается `place_order(cart, " summer10 ")`
- **THEN** скидка применяется, `Order.promo_code == "SUMMER10"`

#### Scenario: customer_id только именованным аргументом
- **WHEN** `customer_id` передан третьим позиционным аргументом в `quote` или `place_order`
- **THEN** выбрасывается `TypeError`, а форма `customer_id="u1"` работает

#### Scenario: Заказ запоминает клиента
- **WHEN** `place_order(cart, customer_id="u1")` без промокода, затем `place_order(cart)`
- **THEN** у первого заказа `Order.customer_id == "u1"`, у второго `Order.customer_id is None`

#### Scenario: Некорректный тип customer_id
- **WHEN** `quote(cart, customer_id=42)`
- **THEN** выбрасывается `ValidationError`

### Requirement: Порядок проверок и ошибки
При непустом коде сервис SHALL сначала получить промокод через `PromoRegistry.resolve(code, customer_id)` (существование, срок, общий лимит, лимит на клиента), затем рассчитать итог с проверкой условий заказа. Ошибки — `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`. Код с лимитом на клиента, вызванный без `customer_id`, и код, у которого клиент исчерпал лимит, MUST давать `PromoConditionsError`. Пустая корзина MUST по-прежнему давать `EmptyCartError`, и эта проверка предшествует проверке кода. `quote` и `place_order` при ошибке MUST NOT менять счётчики, а `place_order` — не сохранять заказ.

#### Scenario: Неудачное оформление не тратит использование
- **WHEN** `place_order` с кодом завершается `PromoConditionsError` (например, не хватает до минимальной суммы)
- **THEN** `uses(code)` и `uses(code, customer_id)` не изменились, заказ не сохранён

#### Scenario: Лимит на клиента без customer_id
- **WHEN** у кода `max_uses_per_customer=1`, вызывается `quote(cart, code)` или `place_order(cart, code)` без `customer_id`
- **THEN** выбрасывается `PromoConditionsError`, заказ не сохранён

### Requirement: Учёт использований
Использованием считается только успешно оформленный заказ с кодом: `place_order` MUST увеличивать общий счётчик на единицу, а при заданном `customer_id` — и счётчик этого клиента, и только после успешного расчёта, вместе с сохранением заказа. `quote`, `calculate_total` и неудачные попытки счётчики MUST NOT менять. Заказ хранит `Order.promo_code: str | None` — нормализованный код или `None`, и `Order.customer_id: str | None` — переданный `customer_id` как есть или `None` (в том числе когда промокода нет); `Order.total` содержит скидку.

#### Scenario: Расчёт не тратит лимит
- **WHEN** несколько раз вызывается `quote(cart, code)` при `max_uses=1`
- **THEN** `uses(code) == 0`, каждый вызов успешен

#### Scenario: Лимит исчерпывается оформлением
- **WHEN** `max_uses=1`, первый `place_order(cart, code)` успешен
- **THEN** `uses(code) == 1`, а второй `place_order(cart, code)` и `quote(cart, code)` выбрасывают `PromoConditionsError`

#### Scenario: Лимит на клиента исчерпывается оформлением
- **WHEN** `max_uses_per_customer=1`, `place_order(cart, code, customer_id="u1")` успешен
- **THEN** `uses(code, "u1") == 1`; повторные `quote` и `place_order` для `"u1"` выбрасывают `PromoConditionsError`, а для `"u2"` проходят

### Requirement: Возврат использования при отмене
`cancel(order_id)` для заказа с промокодом SHALL возвращать использование (уменьшать общий счётчик кода на один и, если у заказа есть `customer_id`, счётчик этого клиента на один) только если с момента оформления заказа прошло меньше 24 часов: `now - Order.created_at < 24 часа`, где `now` берётся из часов сервиса заказов (`Clock`, переданного в `OrderService`). Интервал полуоткрытый: ровно через 24 часа использование уже не возвращается. Если заказ отменён позже, он всё равно переходит в `CANCELLED`, но использование сгорает, то есть оба счётчика не меняются. Возврат не зависит от того, действует ли код на момент отмены. Отмена заказа без промокода счётчики не трогает. Повторная отмена (`InvalidOrderStateError`) MUST NOT менять счётчики. Счётчики не опускаются ниже нуля. Если у сервиса нет реестра, отмена проходит без изменения счётчиков.

#### Scenario: Отмена возвращает лимит
- **WHEN** `max_uses=1`, заказ с кодом оформлен, затем сразу отменён
- **THEN** `uses(code) == 0`, новый `place_order(cart, code)` проходит

#### Scenario: Отмена за секунду до 24 часов
- **WHEN** заказ отменяется через 23 часа 59 минут 59 секунд после оформления
- **THEN** использование возвращено

#### Scenario: Отмена ровно через 24 часа
- **WHEN** заказ отменяется ровно через 24 часа после оформления
- **THEN** заказ отменён, `uses(code)` не изменился (использование сгорело)

#### Scenario: Поздняя отмена
- **WHEN** заказ отменяется через 5 суток после оформления
- **THEN** заказ отменён, общий и клиентский счётчики не изменились, `max_uses=1` по-прежнему исчерпан

#### Scenario: Возврат клиентского использования
- **WHEN** `max_uses_per_customer=1`, заказ клиента `"u1"` отменён в течение 24 часов
- **THEN** `uses(code, "u1") == 0`, новый `place_order(cart, code, customer_id="u1")` проходит

#### Scenario: Повторная отмена
- **WHEN** отменённый заказ отменяют ещё раз
- **THEN** выбрасывается `InvalidOrderStateError`, счётчики не меняются

#### Scenario: Отмена после окончания срока
- **WHEN** срок кода истёк между оформлением и отменой, а с оформления прошло меньше 24 часов
- **THEN** отмена успешна, счётчик уменьшен на один
