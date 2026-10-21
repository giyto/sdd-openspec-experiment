## 1. Модель PromoCode

- [x] 1.1 В `shop/promo.py` добавить `DiscountKind.FREE_SHIPPING` и поля `max_discount: Decimal | None = None`, `max_uses_per_customer: int | None = None` в конец `PromoCode`; инварианты: `FREE_SHIPPING` требует `value == Decimal("0")`, `max_discount` только у `PERCENT` и `> 0`, `max_uses_per_customer` — `int` не `bool` и `>= 1`; проверить в `tests/test_promo.py` допустимые и недопустимые значения (`ValidationError`), включая `max_discount` у `FIXED`/`FREE_SHIPPING`, `0`, отрицательное, `True`, `"1"`

## 2. Реестр

- [x] 2.1 Добавить в `PromoRegistry` клиентские счётчики; `uses(code, customer_id=None)`, `record_use`/`release_use` с необязательным `customer_id`; проверить в `tests/test_promo.py`: `uses(code, "u1")` считает только этого клиента, `uses(code)` — всех, неизвестный код — `UnknownPromoCodeError`, не ниже нуля, `customer_id` не нормализуется (`"User-1"` и `"user-1"` разные)
- [x] 2.2 Расширить `resolve(code, customer_id=None)`: после проверок существования, срока и общего лимита — лимит на клиента (`customer_id is None` или исчерпан → `PromoConditionsError`); нестроковый `customer_id` — `ValidationError`; проверить тестами: порядок проверок, код без клиентского лимита работает без `customer_id`, `resolve(code)` по-старому

## 3. Расчёт в pricing

- [x] 3.1 Добавить `OrderTotal.shipping_discount: Decimal = ZERO` в конец dataclass; запустить `python -m pytest -q` — существующие тесты проходят
- [x] 3.2 Порог доставки считать от `subtotal` до скидки (обновить docstring модуля и правило в `README.md`); проверить тестами: 3100.00 со скидкой 200.00 — бесплатно, 2999.99 — платно, ровно 3000.00 — бесплатно
- [x] 3.3 Реализовать потолок 50 % для `FIXED` (`min(value, P, quantize_money(P * 0.5))`) и `max_discount` для `PERCENT`; проверить тестами из спецификации: 300.00/500 → 150.00, 1000.00 с 400/500/600, 333.33/200 → 166.67, потолок процента сработал, не сработал, равен скидке, `PERCENT 80` без потолка
- [x] 3.4 Изменить ничью в `_split_discount`: при равных остатках больше сумма строки, затем раньше в корзине; проверить тестами: 1.00 и 3.00 при `D = 0.02` → 0.00 и 0.02, 3.00 и 1.00 → 0.02 и 0.00, три по 100.00 при 10.00 → 3.34/3.33/3.33, сумма долей равна общей скидке
- [x] 3.5 Реализовать `FREE_SHIPPING` в `calculate_total`: скидка на товары 0, `shipping == 0.00`, `shipping_discount` равен обычной стоимости доставки; условия заказа общие; проверить тестами: платная доставка 299.00, доставка бесплатна по порогу, только цифровые товары, `ShippingPolicy(fee=50, free_threshold=None)`, только сертификаты и `min_order_amount` → `PromoConditionsError`, у кодов других видов `shipping_discount == 0.00`, `total == subtotal - discount + shipping + tax`

## 4. Заказы

- [x] 4.1 Добавить `Order.customer_id: str | None = None` (в конец) и `customer_id` (только именованный) в `quote` и `place_order`; проверка типа (`ValidationError`), передача в `resolve`, запись в заказ даже без промокода, `record_use` с `customer_id` после успешного расчёта; проверить тестами: позиционная передача — `TypeError`, лимит на клиента без `customer_id`, исчерпанный лимит клиента, другой клиент проходит, неудачные попытки и `quote` счётчики не меняют
- [x] 4.2 Реализовать окно возврата в `cancel`: использование (общее и клиентское) возвращается только при `now - created_at < 24 часа` по часам сервиса; проверить тестами с `FixedClock`: сразу, 23:59:59 — вернулось, ровно 24:00:00 и 5 суток — сгорело, заказ при этом `CANCELLED`, повторная отмена не меняет счётчики, отмена без реестра и без кода работает
- [x] 4.3 Обновить два устаревших теста (`test_free_shipping_threshold_after_discount`, `test_cancel_after_expiry`) под новые правила, остальные существующие тесты не трогать; проверить `git diff --stat tests/` (изменены только эти два теста и добавлены новые)

## 5. Проверка

- [x] 5.1 Проверить обратную совместимость: старые вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)`, `resolve(code)`, `uses(code)` работают, `shipping_discount == 0.00` без кода; полный `python -m pytest -q` зелёный; `git diff --stat` не затрагивает `shop/cli.py` и `shop/reports.py`, новых зависимостей нет
- [x] 5.2 Сверить публичный API реализации с proposal и specs (значения `DiscountKind`, порядок и вид полей `PromoCode`, сигнатуры `resolve`/`uses`/`quote`/`place_order` с `customer_id` только именованным, `OrderTotal.shipping_discount`, `Order.customer_id`) и зафиксировать расхождения или их отсутствие
