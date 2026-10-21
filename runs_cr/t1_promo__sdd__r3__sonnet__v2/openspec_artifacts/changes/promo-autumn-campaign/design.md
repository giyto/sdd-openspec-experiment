## Context

Тикет SHOP-447 правит промокоды после летней кампании (мотивация — в `proposal.md`, требования — в `specs/`). Текущее состояние: `PromoRegistry` держит общий счётчик использований, `calculate_total` считает скидку и порог доставки по `subtotal - discount`, `OrderService.cancel` всегда вызывает `release`. Соглашения README обязательны: `Decimal` и `quantize_money`, `ShopError`-иерархия, `Clock` через конструктор, frozen-dataclass с проверкой в `__post_init__`, полуоткрытые интервалы, только stdlib.

## Goals / Non-Goals

**Goals:**
- Реализовать все изменения тикета аддитивно: старые вызовы и старые сигнатуры работают.
- Скидка и `shipping_discount` считаются в одном месте (`pricing.py`) и одинаково для `quote` и `place_order`.

**Non-Goals:**
- `shop/cli.py`, `shop/reports.py`, существующие тесты не меняются (CLI и отчёты не показывают `shipping_discount`).
- Персистентность счётчиков, комбинирование нескольких кодов.

## Разрешение противоречий в тикете

- **30 % или 50 %.** Поправка маркетинга (22.10) позже тикета и согласована с финансами → потолок фиксированной скидки **50 %**. Константа в одном месте (`FIXED_DISCOUNT_MAX_SHARE = Decimal("0.5")`).
- **Раздача копеек.** Комментарий бухгалтерии принят как требование: ключ сортировки `(-остаток, -сумма строки, индекс)`. Изменение затрагивает только случаи с равными остатками и разными суммами; пример тикета с равными строками не меняется.
- **24 часа.** Тимлид подтвердил: полуоткрытый интервал, ровно 24 часа — использование сгорает: возврат, если `now - created_at < timedelta(hours=24)`.
- **Старые тесты.** три существующих теста кодируют отменяемые правила и упадут: `test_shipping_threshold_after_discount` и проверка фиксированной скидки `500` на `320.00` (ждёт `320.00`) в `tests/test_pricing_promo.py`, а также `test_cancel_releases` в `tests/test_orders_promo.py` (отмена через 2 дня ждёт возврата). Менять их по условию нельзя: при реализации не править, а явно сообщить об этом.

## Decisions

1. **`DiscountKind.FREE_SHIPPING = "free_shipping"`.** `PromoCode.__post_init__`: для этого вида `value` обязано равняться нулю (`Decimal("0")` или `0`), иначе `ValidationError`; значение нормализуется в `Decimal("0")`. Ветка `PERCENT` / `FIXED` не меняется (текущее `else` разбить на `FIXED` и `FREE_SHIPPING`).
2. **`max_discount`.** Допустим только при `PERCENT` (иначе `ValidationError`), `Decimal`/`int` не `bool`, конечное, `> 0`, не более двух знаков (как фиксированная скидка и `min_order_amount`, проверка `to_money(x) == x`), хранится как `to_money`. `max_uses_per_customer` проверяется как `max_uses` (общий хелпер для обоих полей).
3. **`customer_id`.** Валидация (`str`, непустая, без нормализации) — один общий хелпер в `promo.py`, используемый реестром и `OrderService`. Пустая строка → `ValidationError` (а не «нет клиента»): принято допущение, чтобы не молча обходить лимит на клиента; `None` — «клиента нет».
4. **Реестр.** Хранит `_uses[code]` (общий) и `_uses_by_customer[code][customer_id]`. `resolve(code, customer_id=None)`: unknown → expired → общий лимит → лимит на клиента (`customer_id is None` при заданном лимите → `PromoConditionsError`). `uses(code, customer_id=None)`; `redeem(code, customer_id=None)` и `release(code, customer_id=None)` (прежние имена, новый необязательный параметр). Всё под существующим `threading.Lock`. `release` не опускает счётчики ниже 0; фиксация без `customer_id` меняет только общий счётчик.
5. **`calculate_total`.**
   - `_discount_amount`: `PERCENT` → `min(quantize(base * value / 100), max_discount)` если потолок задан; `FIXED` → `min(value, base, quantize_money(base * 0.5))`; `FREE_SHIPPING` → `ZERO`.
   - Раскладка вызывается как прежде (скидка `0.00` раскладывается в нули; для `FREE_SHIPPING` раскладку пропускаем); ключ сортировки получает `-amount` вторым элементом.
   - Доставка: `shipping_cost = shipping.cost_for(subtotal, ...)` (порог от суммы до скидки); для `FREE_SHIPPING` `shipping_discount = shipping_cost`, `shipping_cost = ZERO`; иначе `shipping_discount = ZERO`.
   - `total = subtotal - discount + shipping + tax` без изменений формулы.
   - `OrderTotal.shipping_discount: Decimal = ZERO` добавляется последним полем (после `discount`).
   - Условия заказа (участвующие строки, `min_order_amount`) общие для всех видов, в том числе `FREE_SHIPPING`: код на бесплатную доставку не применяется к корзине без участвующих товаров.
6. **`OrderService`.** `quote(cart, promo_code=None, *, customer_id=None)` и `place_order(...)`: `customer_id` валидируется всегда, передаётся в `resolve` и `redeem`; `Order.customer_id: str | None = None` добавляется последним полем. `cancel`: после `store.save(cancelled)` — если у заказа есть код и сервис имеет реестр и `self._clock.now() - order.created_at < timedelta(hours=24)`, вызывается `release(code, order.customer_id)`; иначе — `logger.info` о сгоревшем использовании. Отрицательная разница (часы откатились) попадает в окно. Окно — модульная константа `CANCEL_REFUND_WINDOW`.
7. **Экспорт.** Новых публичных имён нет (`DiscountKind` уже экспортируется). Версия не меняется. В README обновить строку про порог доставки и добавить правила новых кодов.

## Risks / Trade-offs

- [Старые тесты упадут из-за отменяемых правил] → описано выше; не править, сообщить.
- [Часы реестра и сервиса — разные объекты] → окно возврата по часам сервиса (требование тикета), срок кода — по часам реестра.
- [Заказы, оформленные до изменения, не имеют `customer_id`] → поле `None`; при отмене возвращается только общий счётчик.
- [Сгоревшее использование нельзя восстановить] → осознанная цель тикета.

## Assumptions (где тикет неоднозначен)

- Потолок фиксированной скидки — 50 % (поправка маркетинга), не 30 %.
- `max_discount` с более чем двумя знаками — `ValidationError`; `float`/`bool` отвергаются как везде.
- `value` кода бесплатной доставки: любое числовое нулевое значение (`Decimal("0")`, `Decimal("0.00")`, `0`) допустимо и нормализуется; ненулевое — `ValidationError`.
- Код бесплатной доставки при уже бесплатной доставке применим, использование засчитывается, `shipping_discount = 0.00`.
- Лимит на клиента учитывает только использования с переданным `customer_id`; общий лимит `max_uses` считает все.
- Пустая строка и не-`str` в `customer_id` — `ValidationError`; пробелы и регистр не нормализуются.
- Отмена до `created_at` (откат часов) считается внутри окна.
- Поздняя отмена не возвращает ни общий счётчик, ни счётчик клиента.
- `uses(code, customer_id)` для неизвестного клиента — `0`, для неизвестного кода — `UnknownPromoCodeError`.
- Тесты — только в новых файлах (например, `tests/test_promo_autumn.py`), существующие не правятся.
