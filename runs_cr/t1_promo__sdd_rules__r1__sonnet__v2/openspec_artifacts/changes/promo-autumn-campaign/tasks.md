## 1. Модель промокода

- [x] 1.1 В `shop/promo.py` добавить `DiscountKind.FREE_SHIPPING` и поля `max_discount`, `max_uses_per_customer` (последние, с умолчанием `None`) с инвариантами из spec `promo-codes` (`FREE_SHIPPING.value == 0`, `max_discount` только у `PERCENT`, `> 0`, до двух знаков; лимит на клиента `None` или `>= 1`, не `bool`); проверить новыми тестами в `tests/test_promo.py` на каждое нарушение → `ValidationError` и на то, что прежние создания `PromoCode` работают

## 2. Реестр: лимит на клиента

- [x] 2.1 В `PromoRegistry` добавить счётчики по клиентам, `uses(code, customer_id=None)` и `resolve(code, customer_id=None)` (порядок: существование → срок → общий лимит → лимит на клиента; без `customer_id` при лимите на клиента → `PromoConditionsError`; `customer_id` как есть); проверить тестами из сценариев `promo-codes` (клиент `u1`/`u2`/`U1`, просрочка важнее лимита на клиента, `uses("NOPE", "u1")`)
- [x] 2.2 Расширить `redeem(code, customer_id=None)` и `release(code, customer_id=None)`: атомарная повторная проверка обоих лимитов, оба счётчика не ниже нуля; проверить тестами счётчиков

## 3. Расчёт цен

- [x] 3.1 В `shop/pricing.py` добавить `OrderTotal.shipping_discount` (последним полем, умолчание `ZERO`) и убедиться, что все прежние тесты `calculate_total` проходят (`python -m pytest -q tests/test_pricing.py`)
- [x] 3.2 Вернуть порог доставки к `subtotal` (до скидки) и поправить два конфликтующих существующих теста (`test_fixed_capped` → 600.00, `test_shipping_threshold_after_discount` → доставка 0.00); проверить сценариями «Скидка не роняет сумму ниже порога», «Сумма до скидки ниже порога» в `tests/test_pricing_promo.py`
- [x] 3.3 Реализовать потолок `FIXED` 50 % (`quantize_money`, `ROUND_HALF_UP`) и `max_discount` для `PERCENT`; проверить тестами: 1200.00 → 600.00, значение ровно на потолке, 1.01 → 0.51, процент выше и ниже `max_discount`
- [x] 3.4 Изменить ключ раскладки копеек на `(-остаток, -сумма строки, индекс)`; проверить сценарием 1.00/3.00/2.00 со скидкой 0.03 → 0.00/0.02/0.01, а также что три равные строки по-прежнему дают 0.34/0.33/0.33 и сумма долей равна скидке
- [x] 3.5 Реализовать `FREE_SHIPPING` в `calculate_total`: скидка на товары `0.00`, `shipping = 0.00`, `shipping_discount` равен стоимости доставки без кода; условия заказа действуют как для остальных видов; проверить тестами: обычная доставка, порог достигнут, нет физических товаров, нестандартный `ShippingPolicy`, `min_order_amount`, другие виды → `0.00`

## 4. Заказы

- [x] 4.1 В `shop/orders.py` добавить `Order.customer_id` (последнее поле, умолчание `None`) и keyword-only `customer_id` в `quote`/`place_order` (нестрока → `ValidationError`, передача в `resolve` и `redeem`, запись в заказ); проверить тестами `tests/test_orders_promo.py`: лимит на клиента без `customer_id`, исчерпанный лимит, другой клиент, старые вызовы, позиционная передача → `TypeError`, неудачные попытки не меняют счётчики
- [x] 4.2 Реализовать окно возврата в `cancel` (`now - created_at < 24 ч` по часам сервиса, возврат общего счётчика и счётчика клиента; позже или ровно 24 ч — сгорает, отмена проходит); проверить тестами: 1 час, 23:59:59, ровно 24 часа, 25 часов, клиентский счётчик, разные часы реестра и сервиса, повторная отмена, заказ без кода

## 5. Итоговая проверка

- [x] 5.1 Прогнать `python -m pytest -q`: все тесты зелёные; `git diff --stat` показывает, что `shop/cli.py`, `shop/reports.py` не изменены, а в существующих тестах изменены только два теста из 3.2
- [x] 5.2 Сверить публичный API реализации с proposal и specs: `DiscountKind.FREE_SHIPPING`; `PromoCode` (прежние поля без изменений, новые `max_discount`, `max_uses_per_customer` в конце); `PromoRegistry.resolve(code, customer_id=None)` и `uses(code, customer_id=None)`; `OrderTotal.shipping_discount`; `OrderService.quote(cart, promo_code=None, *, customer_id=None)` и `place_order(cart, promo_code=None, *, customer_id=None)`; `Order.customer_id`
