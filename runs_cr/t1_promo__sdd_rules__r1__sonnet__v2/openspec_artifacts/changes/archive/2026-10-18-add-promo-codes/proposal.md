## Why

Маркетинг запускает летнюю кампанию с промокодами (SHOP-412). Сейчас скидки вручную делает поддержка, и суммы расходятся с чеками. Нужны промокоды в расчёте и оформлении заказа, а скидка должна честно попадать в итоги и построчно в чек: бухгалтерия считает налог по строкам.

## What Changes

- Новый модуль `shop/promo.py`: `DiscountKind` (`PERCENT`, `FIXED`), `PromoCode` (frozen dataclass), `PromoRegistry(clock)` с методами `add`, `resolve`, `uses`.
- В `shop/errors.py` три независимых наследника `PromoError(ShopError)`: `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`.
- `shop/pricing.py`: `calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None)`; поля `LineTotal.discount` и `OrderTotal.discount` (`Decimal("0.00")`, если скидки нет); `total = subtotal - discount + shipping + tax`. Скидка раскладывается по участвующим строкам методом наибольшего остатка, налог строки считается с суммы после скидки, порог бесплатной доставки сравнивается с суммой товаров после скидки.
- `shop/orders.py`: `OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code=None)`, `place_order(cart, promo_code=None)`, `Order.promo_code`. Счётчик использований растёт только при успешном `place_order`; `cancel` возвращает использование.
- Обратная совместимость: старые вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)` дают прежние суммы. `shop/cli.py`, `shop/reports.py` и существующие тесты не меняются; новые тесты идут отдельными файлами. Зависимости не добавляются.

Решения из обсуждения тикета (они приоритетнее исходного текста):
- Акция, которая ещё не началась, — `PromoExpiredError`.
- Пустой или пробельный `promo_code` в `quote`/`place_order` означает «без кода»; `resolve("")` — `UnknownPromoCodeError`.
- Порог бесплатной доставки сравнивается с суммой товаров после скидки.
- `cancel` уменьшает счётчик использований кода на один.

## Capabilities

### New Capabilities
- `promo-codes`: модель промокода, его валидация и нормализация, реестр (поиск, срок действия, лимит, счётчик использований), иерархия ошибок промокодов.
- `promo-pricing`: расчёт скидки в `calculate_total` — участвующие товары, минимальная сумма, процент и фикс, раскладка по строкам, налог после скидки, влияние на доставку.
- `promo-orders`: передача кода в `quote`/`place_order`, порядок проверок, учёт использований при оформлении и отмене заказа, `Order.promo_code`.

### Modified Capabilities
<!-- В openspec/specs/ пока нет спецификаций, изменяемых требований нет. -->

## Impact

- Код: `shop/promo.py` (новый), `shop/errors.py`, `shop/pricing.py`, `shop/orders.py`; новые тесты `tests/test_promo.py`, `tests/test_pricing_promo.py`, `tests/test_orders_promo.py`.
- Публичный API: только добавления (новые необязательные параметры и поля с значениями по умолчанию в конце).
- HTTP-слой (другой репозиторий) получает новый необязательный `promo_code` и три новых исключения.
- `reports.py` и CLI скидок пока не показывают (отдельный тикет): `OrderTotal.subtotal` остаётся суммой до скидки.
- Зависимости: нет.
