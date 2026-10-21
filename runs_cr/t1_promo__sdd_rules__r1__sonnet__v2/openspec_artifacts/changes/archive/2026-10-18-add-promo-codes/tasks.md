## 1. Ошибки и модель промокода

- [x] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и независимые `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить в `tests/test_promo.py`, что ни один не подкласс другого
- [x] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация кода, все инварианты); проверить тестами `tests/test_promo.py` на каждое нарушение → `ValidationError` и на нормализацию `"  summer10 "`

## 2. Реестр промокодов

- [x] 2.1 Реализовать `PromoRegistry(clock)`: `add` (дубликат → `ValidationError`), `resolve` (порядок: неизвестный → срок `[starts_at, expires_at)` → лимит), `uses`; проверить тестами границ срока, «ещё не началась», просрочен+исчерпан, `resolve("")`
- [x] 2.2 Добавить служебные `redeem` и `release` (не ниже нуля, `redeem` повторно проверяет лимит); проверить тестами счётчика

## 3. Расчёт скидки

- [x] 3.1 Добавить `discount` (по умолчанию `ZERO`, последним полем) в `LineTotal` и `OrderTotal`; убедиться, что все существующие тесты проходят без изменений (`python -m pytest -q`)
- [x] 3.2 Реализовать в `calculate_total` параметр `promo` (keyword-only): участвующие строки, `PromoConditionsError` (нет участвующих / ниже минималки, равенство подходит), размер скидки `PERCENT`/`FIXED`; проверить в `tests/test_pricing_promo.py`
- [x] 3.3 Реализовать раскладку по строкам в целых копейках (наибольший остаток, ничья — раньше в корзине); проверить тестами: Σ строк == общая скидка, сценарии 1.00 на три строки и наибольший остаток, неучаствующим 0.00
- [x] 3.4 Считать налог с `amount - discount`, `total = subtotal - discount + shipping + tax`, порог доставки по сумме после скидки; проверить тестами налога строки, перехода порога, неизменной стоимости доставки и совпадения сумм без промокода со старыми

## 4. Заказы

- [x] 4.1 Добавить `Order.promo_code` (после `status`, по умолчанию `None`) и `OrderService(..., promos=None)`; `quote(cart, promo_code=None)` с разбором кода (пусто/пробелы → без кода; без реестра → `UnknownPromoCodeError`); проверить в `tests/test_orders_promo.py`
- [x] 4.2 Реализовать `place_order(cart, promo_code=None)`: сохранение нормализованного кода, `redeem` только после успешного расчёта, при любой ошибке счётчик и хранилище не меняются; проверить тестами лимита `max_uses=1` и неудачных попыток
- [x] 4.3 Реализовать возврат использования в `cancel` после успешного сохранения; проверить тестами переоформления, повторной отмены (`InvalidOrderStateError`, счётчик не уменьшается) и заказа без кода

## 5. Итоговая проверка

- [x] 5.1 Прогнать `python -m pytest -q`: все старые и новые тесты зелёные, `shop/cli.py`, `shop/reports.py` и существующие тесты не изменены (`git diff --stat`)
- [x] 5.2 Сверить публичный API реализации с proposal и specs: имена модулей, классов, сигнатуры и порядок параметров (`calculate_total(..., *, promo)`, `OrderService(..., promos)`, `quote`/`place_order(cart, promo_code)`), поля `PromoCode`, `LineTotal.discount`, `OrderTotal.discount`, `Order.promo_code`, значения `DiscountKind`, иерархия `PromoError`
