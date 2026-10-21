## 1. Модель промокода

- [x] 1.1 Добавить `DiscountKind.FREE_SHIPPING`, поля `max_discount` и `max_uses_per_customer` в конец `PromoCode` и проверки в `__post_init__` (виды, `value == 0` для бесплатной доставки, потолок только у `PERCENT` и `> 0`, два знака, `max_uses_per_customer` — `None` или целое >= 1); проверить новыми тестами в новом файле `tests/test_promo_campaign_fixes.py`
- [x] 1.2 Расширить `PromoRegistry`: `resolve(code, customer_id=None)`, `uses(code, customer_id=None)`, `consume(code, customer_id=None)`, `release(code, customer_id=None)` с счётчиками по паре `(code, customer_id)`; порядок проверок: существование → срок → общий лимит → лимит клиента (без `customer_id` при заданном лимите — `PromoConditionsError`); проверить тестами из 1.1

## 2. Расчёт заказа (`shop/pricing.py`)

- [x] 2.1 Потолок фиксированной скидки `quantize_money(base * 0.5)` и потолок процентной скидки `max_discount` в `_allocate_discount`; проверить сценарии «Размер скидки» из `specs/promo-discounts` новыми тестами
- [x] 2.2 Поменять tie-break раскладки на `(-remainder, -line_amount, index)`; проверить сценарии «Равные остатки, разные суммы» и «Равные остатки и равные суммы» новыми тестами
- [x] 2.3 Добавить `OrderTotal.shipping_discount: Decimal = ZERO` в конец; вид `FREE_SHIPPING`: нулевая скидка строк, `shipping = 0`, `shipping_discount` = снятая стоимость доставки; проверить сценарии из `specs/promo-discounts`
- [x] 2.4 Порог бесплатной доставки сравнивать с `subtotal` до скидки; проверить сценарии «Скидка не переводит заказ под порог» и «Порог не достигнут до скидки» новыми тестами
- [x] 2.5 Запустить существующие тесты `tests/test_pricing_promo.py`: ожидаемо падают `test_fixed_discount_is_capped_by_participating_amount` и `test_discount_moves_order_under_free_shipping_threshold`. Их НЕ менять; зафиксировать падения в отчёте по apply (см. design.md, «Открытые вопросы»)

## 3. Заказы (`shop/orders.py`)

- [x] 3.1 Добавить `Order.customer_id: str | None = None` в конец датакласса; `quote(cart, promo_code=None, *, customer_id=None)` и `place_order(cart, promo_code=None, *, customer_id=None)` передают `customer_id` в реестр; проверить, что `quote` не меняет счётчики
- [x] 3.2 В `cancel` возвращать использование (`release` с `customer_id` заказа) только если `self._clock.now() - order.created_at < timedelta(hours=24)`; проверить сценарии отмены из `specs/promo-codes` (в 23:59, ровно 24 часа, через 3 дня, без промокода) новыми тестами с `FixedClock`
- [x] 3.3 Проверить, что `tests/test_orders_promo.py::test_cancel_releases_use` проходит без изменений (отмена сразу после оформления попадает в окно)

## 4. Документация

- [x] 4.1 Обновить раздел «Правила расчёта» и «Промокоды» в `README.md`: порог доставки до скидки, потолки, `FREE_SHIPPING`, `shipping_discount`, лимит на клиента, окно 24 часа, tie-break копеек; формулировки должны совпасть с `specs/`

## 5. Проверка

- [x] 5.1 Запустить `pytest` целиком: все новые тесты проходят; единственные падения — два теста из 2.5; `shop/cli.py`, `shop/reports.py` и существующие тесты не изменены (`git diff --stat` подтверждает)
- [x] 5.2 Запустить `openspec validate promo-campaign-fixes --strict` и убедиться, что валидация проходит
