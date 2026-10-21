## 1. Ошибки и модель промокода

- [x] 1.1 Добавить `PromoError(ShopError)` и три независимых подкласса `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError` в `shop/errors.py`; проверить новым тестом в `tests/test_promo_errors.py`, что все три наследуют `PromoError` и не наследуют друг друга
- [x] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (frozen dataclass): нормализация кода через `normalize_key`, проверки диапазонов значений, минимальной суммы, aware-дат, `starts_at < expires_at`, `max_uses`; проверить тестами в `tests/test_promo_code.py` на допустимые и отклоняемые значения (включая `PERCENT 0`, `PERCENT 150`, `FIXED 0`, пустой код, `max_uses=0`, `max_uses=True`)

## 2. Реестр промокодов

- [x] 2.1 Реализовать `PromoRegistry(clock)` с `add` (дубликат — `ValidationError`) и `uses`; проверить тестом, что повторный код с другим регистром и пробелами отклоняется
- [x] 2.2 Реализовать `resolve` в порядке существование → срок (`[starts_at, expires_at)` по `FixedClock`) → лимит; проверить тестами все три ошибки и границы интервала (ровно `starts_at` подходит, ровно `expires_at` нет)
- [x] 2.3 Добавить `record_use(code)` и `release_use(code)` (счётчик не уходит ниже нуля); проверить тестами, что `resolve` после исчерпания лимита даёт `PromoConditionsError`, а после `release_use` снова проходит
- [x] 2.4 Реализовать `uses(code)` для неизвестного кода через `UnknownPromoCodeError`; проверить тестом

## 3. Расчёт скидки

- [x] 3.1 В `shop/pricing.py` добавить `LineTotal.discount` и `OrderTotal.discount` со значением `Decimal("0.00")` в конце dataclass; убедиться, что существующие тесты проходят без изменений (`python -m pytest -q`)
- [x] 3.2 Реализовать отбор участвующих строк (не в исключённых категориях и не `GIFT_CARD`), проверку «нет участвующих строк» и минимальной суммы (`>=`, до скидки) как `PromoConditionsError`; проверить тестами из spec-сценариев
- [x] 3.3 Реализовать общую скидку (процент с `ROUND_HALF_UP`, фиксированная с ограничением суммой участвующих строк) и целочисленную раскладку по копейкам с распределением остатка по наибольшему остатку и порядку корзины; проверить тестами «копейка первой строке», «равные остатки по порядку корзины», «сумма строк = общая скидка» (в том числе на случайных корзинах с детерминированным перебором)
- [x] 3.4 Считать налог строки от `amount − discount`, доставку — от `subtotal − discount` для порога; итог `subtotal − discount + shipping + tax`; проверить тестами из сценариев «налог после скидки», «скидка приближает доставку», «доставка не уменьшается»
- [x] 3.5 Принять `promo` в `calculate_total` как keyword-only аргумент; проверить тестом, что вызовы `calculate_total(cart)` и `calculate_total(cart, shipping, tax)` дают те же суммы, что и до изменения

## 4. Оформление заказа

- [x] 4.1 В `shop/orders.py` добавить `Order.promo_code: str | None = None` в конец dataclass и принять `promos: PromoRegistry | None = None` в `OrderService`; проверить тестом, что без промокода `Order.promo_code is None`
- [x] 4.2 Реализовать `quote(cart, promo_code=None)`: пустой, пробельный или `None` код — без промокода; непустой — `resolve` (без реестра — `UnknownPromoCodeError`), затем `calculate_total`; проверить тестами, что `quote` не меняет счётчик
- [x] 4.3 Реализовать `place_order(cart, promo_code=None)`: расчёт → `record_use` → `next_id` → сохранение; проверить тестами, что неудачный заказ не увеличивает счётчик и не расходует номер заказа, а успешный сохраняет нормализованный код
- [x] 4.4 Реализовать возврат использования в `cancel` для заказов с промокодом; проверить тестом цикл «оформить → отменить → оформить снова с тем же лимитом 1»

## 5. Сквозная проверка

- [x] 5.1 Проверить, что `shop/cli.py`, `shop/reports.py` и существующие тесты не изменены (`git diff --stat -- shop/cli.py shop/reports.py tests/` пуст для существующих файлов) и что `python -m pytest -q` проходит полностью
- [x] 5.2 Добавить в `shop/__init__.py` экспорт `PromoCode`, `PromoRegistry`, `DiscountKind` и ошибок промокодов, если публичный экспорт проекта это предполагает; проверить `python -c "import shop; shop.PromoCode"`
- [x] 5.3 Выполнить `openspec validate add-promo-codes --strict` и убедиться, что проверка проходит
