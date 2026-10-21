## 1. Модель промокода и реестр (shop/promo.py)

- [x] 1.1 Добавить `DiscountKind.FREE_SHIPPING` и поля `max_discount`, `max_uses_per_customer` в конец `PromoCode`; проверить инварианты из spec (`FREE_SHIPPING` с ненулевым `value`, `max_discount` не у `PERCENT`, `max_discount <= 0`, `max_uses_per_customer < 1`) тестами в новом файле `tests/test_promo_campaign_model.py`
- [x] 1.2 Добавить счётчик использований по клиентам в `PromoRegistry`; `record_use` и `release_use` принимают `customer_id=None`; проверить тестом, что `release_use` не уводит счётчик клиента в минус
- [x] 1.3 Расширить `resolve(code, customer_id=None)` проверкой лимита на клиента (без `customer_id` и при исчерпанном лимите — `PromoConditionsError`) и `uses(code, customer_id=None)`; проверить тестами из сценариев `Per-customer usage limit` в `tests/test_promo_campaign_registry.py`
- [x] 1.4 Запустить `pytest tests/test_promo_registry.py tests/test_promo_code.py`, убедиться, что существующие тесты реестра и модели проходят без изменений

## 2. Расчёт итогов (shop/pricing.py)

- [x] 2.1 Добавить константу `FIXED_MAX_SHARE = Decimal("0.50")` и потолок фиксированной скидки в `_order_discount`; проверить тестом сценарий `Fixed amount cap is rounded half up` (`999.99` → `500.00`) в `tests/test_promo_campaign_pricing.py`
- [x] 2.2 Добавить потолок `max_discount` для `PERCENT` в `_order_discount`; проверить сценарии `Percent discount reaches the ceiling` и `Percent discount below the ceiling`
- [x] 2.3 Исправить порядок получателей копейки в `_distribute_discount` (ключ `(-remainder, -base_kopecks, index)`); проверить сценарий `Tie on remainder goes to the larger line` (`0.02` на `1.00` и `3.00` → `0.00` и `0.02`) и то, что тест `Tie on remainder and amount goes to the earlier line` проходит
- [x] 2.4 Добавить поле `OrderTotal.shipping_discount: Decimal = ZERO` в конец dataclass; проверить, что старые тесты `tests/test_pricing.py` проходят без изменений
- [x] 2.5 Реализовать `FREE_SHIPPING` в `calculate_total`: скидка на товары `0.00`, `shipping = 0.00`, `shipping_discount` равен стоимости доставки без кода; проверить сценарии `Shipping saving of a free shipping code`, `Free shipping code with no saving`, `Other code kinds give no shipping saving`
- [x] 2.6 Перевести порог бесплатной доставки на сумму до скидки (`subtotal`, а не `goods_amount`); проверить сценарии `Goods before discount reach the free shipping threshold` и `Discount does not bring goods to the threshold`. Два существующих теста порога в `tests/test_promo_pricing.py` ожидаемо упадут; их не менять, результат зафиксировать в отчёте (см. design.md, «Открытые конфликты», пункт 1)

## 3. Оформление заказа (shop/orders.py)

- [x] 3.1 Добавить `Order.customer_id: str | None = None` в конец dataclass и `customer_id` в `quote` и `place_order` как keyword-only аргументы; проверить сценарии `Order remembers the customer` и `Order without customer` тестами в `tests/test_promo_campaign_orders.py`
- [x] 3.2 В `place_order` вызывать `record_use(code, customer_id)` только при наличии кода; проверить сценарий `Failed order does not consume a use` и то, что счётчик клиента растёт только при успешном заказе
- [x] 3.3 В `cancel` вернуть использование только при `now - created_at < 24 часа` по `self._clock`; проверить сценарии `Cancellation within 24 hours restores the count`, `Cancellation exactly at 24 hours spends the use` (через `FixedClock`) и `Cancellation after 24 hours keeps the count`

## 4. Проверка

- [x] 4.1 Запустить `pytest tests/test_orders.py tests/test_promo_orders.py tests/test_promo_pricing.py tests/test_promo_registry.py`; для `tests/test_promo_orders.py` проверить, что существующие сценарии отмены не продвигают часы дальше 24 часов; если продвигают, зафиксировать это в отчёте и не менять тест
- [ ] 4.2 Запустить полный набор `pytest`; ожидаемо падают только два теста порога из пункта 2.6; любые другие падения — разобрать и устранить в коде, а не в тестах
- [x] 4.3 Проверить, что `shop/cli.py` и `shop/reports.py` не изменены (`git diff --stat -- shop/cli.py shop/reports.py` пустой) и что существующие тесты (`tests/` кроме новых файлов) не изменены (`git diff --stat -- tests/`)
- [x] 4.4 Запустить `openspec validate promo-campaign-fixes --strict` и убедиться, что артефакты валидны
