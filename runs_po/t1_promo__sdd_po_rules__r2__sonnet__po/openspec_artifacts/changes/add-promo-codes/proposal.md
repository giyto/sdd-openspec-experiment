## Why

Маркетинг запускает летнюю кампанию с промокодами. Сейчас скидки вручную делает поддержка, и суммы расходятся с чеками. Нужны промокоды, которые передаются при расчёте и оформлении заказа, а скидка честно отражается в итогах и построчно (бухгалтерия считает налог по строкам).

## What Changes

- Новый модуль `shop/promo.py`: `DiscountKind` (`PERCENT`, `FIXED`), `PromoCode` (frozen dataclass с полями `code`, `kind`, `value`, `min_order_amount`, `starts_at`, `expires_at`, `max_uses`, `excluded_categories`) и `PromoRegistry(clock)` с методами `add`, `resolve`, `uses`.
- `shop/errors.py`: `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`.
- `shop/pricing.py`: `calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None)`; новые поля `LineTotal.discount` и `OrderTotal.discount` (`Decimal("0.00")`, если скидки нет); `total = subtotal - discount + shipping + tax`. Скидка раскладывается по строкам, налог строки считается с суммы после скидки, доставка не скидывается.
- `shop/orders.py`: `OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code: str | None = None)`, `place_order(cart, promo_code: str | None = None)`, `Order.promo_code: str | None`. Счётчик использований растёт только при успешном `place_order` и уменьшается на один при отмене заказа с промокодом (`cancel`).
- Обратная совместимость: вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)` дают прежние суммы. **Не BREAKING.**
- Не меняются: `shop/cli.py`, `shop/reports.py`, существующие тесты. Новые зависимости не добавляются.
- README: обновить раздел «Правила расчёта» (формула итога, правила скидок).

## Capabilities

### New Capabilities
- `promo-codes`: модель промокода, его валидация, реестр кодов (нормализация, срок действия, лимит использований, учёт использований), иерархия ошибок промокодов.
- `order-discounts`: применение промокода при расчёте итогов (`calculate_total`) и при `quote`/`place_order`: участвующие товары, процент/фикс, построчная раскладка, налог, доставка, порядок проверок, пустой код.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций)

## Impact

- Код: `shop/promo.py` (новый), `shop/errors.py`, `shop/pricing.py`, `shop/orders.py`; новые тесты в отдельных файлах; README.
- Публичный API расширяется только заданными в тикете именами; новые поля dataclass-ов имеют значения по умолчанию.
- `shop/reports.py` и `shop/cli.py` не меняются; отчёты, считающие выручку по `total.total`, автоматически учитывают скидку, отдельной строки скидки в CLI/отчётах пока нет (отдельный тикет).
- Зависимости: только стандартная библиотека.

## Assumptions

Неоднозначности тикета, решённые автономно (подробности и обоснования в design.md):

- Подарочные сертификаты никогда не участвуют в скидке и не учитываются в минимальной сумме заказа (README).
- `min_order_amount` сравнивается с суммой участвующих строк до скидки, нестрого (`>=`).
- Если участвующих строк нет, заказ не подходит: `PromoConditionsError`.
- Порог бесплатной доставки сравнивается с суммой товаров после скидки (иначе порог добирали бы промокодом); сама стоимость доставки скидкой не уменьшается.
- Отмена заказа с промокодом возвращает использование: счётчик уменьшается на один (поддержка может переоформить заказ с лимитированным кодом).
- `uses()` для неизвестного кода — `UnknownPromoCodeError`.
