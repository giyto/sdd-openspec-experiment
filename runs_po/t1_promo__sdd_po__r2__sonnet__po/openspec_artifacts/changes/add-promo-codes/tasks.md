## 1. Ошибки и модель промокода

- [x] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить тестом в `tests/test_promo.py`, что ни один из трёх не подкласс другого и все ловятся как `PromoError`/`ShopError`
- [x] 1.2 Создать `shop/promo.py` с `DiscountKind` и frozen-dataclass `PromoCode` (нормализация кода, все инварианты из спеки promo-codes); проверить тестами валидации: границы процента (0, 100], FIXED > 0 и два знака, float отвергается, пустой код, naive-даты, `starts_at >= expires_at`, `max_uses` 0/bool, нормализация `" summer10 "`

## 2. Реестр промокодов

- [x] 2.1 Реализовать `PromoRegistry(clock)`: `add` (дубликат после нормализации — `ValidationError`), `resolve` (порядок: существует → срок `[starts_at, expires_at)` → лимит), `uses`; проверить тестами с `FixedClock`: `resolve("")`, до начала → `PromoExpiredError`, границы срока, порядок «просрочен + лимит исчерпан» → `PromoExpiredError`, регистр/пробелы
- [x] 2.2 Добавить `redeem(code)` (под `threading.Lock`: повторный `resolve` и увеличение счётчика) и `release(code)` (уменьшение не ниже 0); проверить тестами: `resolve` не меняет `uses`, `redeem` увеличивает на 1, при `max_uses=1` второй `redeem` — `PromoConditionsError`, `release` уменьшает на 1 и не уходит ниже 0, после `release` код снова доступен

## 3. Расчёт скидки в итогах

- [x] 3.1 Добавить `LineTotal.discount` и `OrderTotal.discount` (по умолчанию `ZERO`, последние поля) и keyword-only `promo` в `calculate_total` без изменения поведения без кода; проверить в `tests/test_pricing_promo.py`, что старые вызовы дают прежние суммы и `discount == 0.00`, и что существующие `tests/test_pricing.py` проходят без правок
- [x] 3.2 Реализовать выбор участвующих строк (без `GIFT_CARD` и исключённых категорий), размер скидки (процент с `ROUND_HALF_UP`, фикс с ограничением суммой) и проверку `min_order_amount` (включительно, нет участвующих строк → `PromoConditionsError`); проверить тестами: 100.05 × 10 % = 10.01, фикс больше суммы, 100 %, минимум 499.99/500.00, только сертификаты
- [x] 3.3 Реализовать раскладку по строкам методом наибольших остатков в копейках и налог с суммы после скидки; `total = subtotal - discount + shipping + tax`, порог бесплатной доставки сравнивается с суммой после скидки (стоимость доставки не скидывается); проверить тестами: 10.00 на три строки по 10.00 → 3.34/3.33/3.33, сумма построчных == общая, `0 <= d_i <= amount_i`, налог 180.00 в примере 1000−100, 3100.00 со скидкой ниже порога 3000.00 — доставка платная 299.00, сумма после скидки >= 3000.00 — бесплатная, полностью скинутая строка имеет налог 0.00; добавить перебор нескольких корзин на инвариант суммы

## 4. Оформление заказа

- [x] 4.1 Добавить `promos: PromoRegistry | None` в `OrderService`, `promo_code` в `quote` и `place_order`, `Order.promo_code` (по умолчанию `None`); пустой/пробельный/`None` код — «без кода»; непустой код без реестра → `UnknownPromoCodeError`; проверить в `tests/test_orders_promo.py`: старые вызовы `quote(cart)`/`place_order(cart)` дают прежние суммы, `"   "` равно отсутствию кода, `promo_code` хранится нормализованным
- [x] 4.2 Реализовать учёт использований в `place_order` (`EmptyCartError` → `resolve` → `calculate_total` → `redeem` → сохранение заказа); проверить тестами: `quote` и `calculate_total` не меняют `uses`, неудачные попытки (неизвестный, просроченный, лимит, `min_order_amount`) не создают заказ и не меняют `uses`, успешный заказ даёт `uses == 1`, второй заказ при `max_uses=1` → `PromoConditionsError`, `cancel` заказа с кодом возвращает использование (`uses` 1 → 0, код снова доступен), `cancel` заказа без кода счётчики не трогает, порядок ошибок неизвестен → просрочен → лимит → условия

## 5. Экспорт и финальная проверка

- [x] 5.1 Экспортировать `PromoCode`, `PromoRegistry`, `DiscountKind` и новые ошибки из `shop/__init__.py`; проверить импортом `from shop import PromoRegistry`
- [x] 5.2 Выполнить `python -m pytest -q` и убедиться, что все старые и новые тесты проходят, а `git diff --stat` не показывает изменений в `shop/cli.py`, `shop/reports.py` и существующих файлах `tests/test_*.py`; проверить `grep` на отсутствие `datetime.now`, `print` и `float` в новом коде
