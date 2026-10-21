## Why

Маркетинг запускает летнюю кампанию с промокодами (SHOP-412). Сейчас скидки вручную проставляет поддержка, и суммы расходятся с чеками. Нужны промокоды, которые передаются при расчёте и оформлении заказа, а скидка честно отражается в итогах и построчно (бухгалтерия считает налог по строкам).

## What Changes

- Новый модуль `shop/promo.py`: `DiscountKind` (`PERCENT`, `FIXED`), `PromoCode` (frozen dataclass с инвариантами в `__post_init__`), `PromoRegistry(clock)` с методами `add`, `resolve`, `uses`.
- `shop/errors.py`: `PromoError(ShopError)` и три независимых наследника — `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`.
- `shop/pricing.py`: `calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None)`; новые поля `LineTotal.discount` и `OrderTotal.discount`; `total = subtotal - discount + shipping + tax`. Скидка раскладывается по строкам методом наибольшего остатка, налог считается с суммы строки после скидки.
- Порог бесплатной доставки сравнивается с суммой товаров **после** скидки (уточнение из обсуждения 14.10); стоимость доставки скидка не уменьшает.
- `shop/orders.py`: `OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code=None)`, `place_order(cart, promo_code=None)`, `Order.promo_code`. Использованием считается только успешно оформленный заказ; `cancel` возвращает использование (счётчик −1).
- Пустой или пробельный `promo_code` в `quote`/`place_order` означает «без промокода»; `resolve("")` — неизвестный код.
- Обратная совместимость: старые вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)` дают прежние суммы. Новые поля `discount` равны `Decimal("0.00")`, если скидки нет.
- Не меняются: `shop/cli.py`, `shop/reports.py`, существующие тесты. Новых зависимостей нет.

## Capabilities

### New Capabilities
- `promo-codes`: модель промокода, реестр (регистрация, нормализация кода, проверка существования/срока/лимита, счётчик использований) и иерархия ошибок промокодов.
- `promo-pricing`: расчёт скидки в `calculate_total` — участвующие строки, процентная и фиксированная скидки, раскладка по строкам, налог после скидки, условия заказа, порог бесплатной доставки.
- `order-promos`: применение промокода в `OrderService` — `quote`, `place_order`, `cancel`, учёт использований, `Order.promo_code`.

### Modified Capabilities
<!-- Существующих спецификаций в openspec/specs/ нет; поведение без промокода остаётся прежним и зафиксировано сценариями обратной совместимости. -->

## Impact

- Код: `shop/promo.py` (новый), `shop/errors.py`, `shop/pricing.py`, `shop/orders.py`; новые тесты отдельными файлами в `tests/`.
- Публичный API расширяется только обратно совместимо (новые необязательные параметры и поля со значением по умолчанию).
- `shop/reports.py` и `shop/cli.py` не меняются: отчёты по-прежнему суммируют `total`/`tax`/`shipping` (с промокодом эти значения уже учитывают скидку), показ скидок — отдельным тикетом.
- Зависимости: только стандартная библиотека.
