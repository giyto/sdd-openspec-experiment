## 1. Ошибки

- [x] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить тестом в `tests/test_promo.py`, что они не наследуют друг друга и ловятся как `ShopError`

## 2. Промокоды и реестр (`shop/promo.py`)

- [x] 2.1 Реализовать `DiscountKind` и `PromoCode` с инвариантами и нормализацией кода; тесты на валидные/невалидные значения, пустой код, aware-даты, `starts_at < expires_at`, `float`
- [x] 2.2 Реализовать `PromoRegistry` (`add`, `resolve`, `uses`, `redeem` и `release` под блокировкой) с порядком проверок существование → срок `[starts_at, expires_at)` → лимит; тесты на регистр/пробелы, дубликат, границы времени с `FixedClock`, «ещё не началась» = `PromoExpiredError`, `resolve("")` = Unknown, порядок проверок, `uses`, `release` (уменьшение, не ниже нуля, неизвестный код)

## 3. Расчёт (`shop/pricing.py`)

- [x] 3.1 Добавить `discount` (default `ZERO`) в `LineTotal` и `OrderTotal`; убедиться, что существующие `tests/test_pricing.py` проходят без изменений
- [x] 3.2 Добавить параметр `promo` в `calculate_total`: участвующие строки (без сертификатов и excluded_categories), условия заказа (минимум `>=`, наличие участвующих строк), процент с `ROUND_HALF_UP`, фиксированная с ограничением суммой; тесты в `tests/test_pricing_promo.py`
- [x] 3.3 Реализовать распределение по строкам методом наибольших остатков в копейках, налог с суммы после скидки, `total = subtotal - discount + shipping + tax`, порог бесплатной доставки по сумме товаров после скидки (стоимость доставки не уменьшается); тесты: сумма построчных равна общей (в том числе на неделящихся суммах), скидка строки не больше суммы строки, детерминизм, налог после скидки, скидка опускает сумму ниже порога (3100.00 → доставка платная), после скидки порог достигнут

## 4. Заказы (`shop/orders.py`)

- [x] 4.1 Добавить `Order.promo_code` (default `None`) и `OrderService(..., promos=None)`; `quote(cart, promo_code=None)` с нормализацией, пустым = «нет кода», ошибкой при отсутствии реестра; тесты в `tests/test_orders_promo.py`
- [x] 4.2 Реализовать `place_order(cart, promo_code=None)`: `resolve` → `calculate_total` → `redeem` → `next_id` → `store.add`; тесты: счётчик +1 только при успехе, не меняется при `quote` и при всех видах ошибок, лимит `max_uses`, `Order.promo_code` нормализован

- [x] 4.3 Возврат использования при отмене: `OrderService.cancel` вызывает `promos.release(order.promo_code)` после успешной отмены заказа с кодом; тесты: счётчик −1, лимитированный код снова доступен, повторная отмена не уменьшает повторно, заказ без кода не трогает счётчики

## 5. Итоговая проверка

- [x] 5.1 Запустить `python -m pytest -q`: все старые и новые тесты проходят; `git diff --stat` не показывает изменений в существующих тестах, `shop/cli.py` и `shop/reports.py`
