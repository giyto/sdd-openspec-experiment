## 1. Ошибки и модель промокода

- [x] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и независимые `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить в `tests/test_promo.py`, что все три — подклассы `PromoError` и не являются подклассами друг друга
- [x] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация кода, все инварианты из спецификации `promo-codes`); проверить тестами в `tests/test_promo.py` граничные и некорректные значения (`ValidationError`)

## 2. Реестр

- [x] 2.1 Реализовать `PromoRegistry(clock)`: `add` (дубликат — `ValidationError`), `resolve` (порядок: неизвестный → срок `[starts_at, expires_at)` → лимит), `uses`; проверить тестами с `FixedClock`: регистр/пробелы, `resolve("")`, границы срока, «ещё не началась» = `PromoExpiredError`, порядок проверок
- [x] 2.2 Добавить `record_use` и `release_use` (не ниже нуля, без привязки к сроку); проверить тестами счётчика в `tests/test_promo.py`

## 3. Расчёт скидки

- [x] 3.1 Добавить `discount` в `LineTotal` и `OrderTotal` (значения по умолчанию `ZERO`, поля в конце); запустить существующие тесты `python -m pytest -q` — все проходят без изменений
- [x] 3.2 Реализовать в `calculate_total` параметр `promo` (только именованный): участвующие строки, `PERCENT`/`FIXED`, условия заказа (`PromoConditionsError`); проверить в `tests/test_pricing_promo.py` минимальную сумму (ровно граница), отсутствие участвующих строк, сертификаты и исключённые категории
- [x] 3.3 Реализовать раскладку по строкам в целых копейках (наибольший остаток, ничья — раньше в корзине), налог с суммы после скидки, порог доставки по сумме после скидки; проверить тестами из спецификации `promo-pricing` и свойством `Σ line.discount == order.discount` на нескольких корзинах

## 4. Интеграция в заказы

- [x] 4.1 Добавить `Order.promo_code` и `OrderService(..., promos=None)`; реализовать разбор `promo_code` (`None`/пустой/пробельный = без кода, нестроковый = `ValidationError`, без реестра = `UnknownPromoCodeError`) в `quote`; проверить в `tests/test_orders_promo.py`
- [x] 4.2 Реализовать `place_order(cart, promo_code)` с `record_use` только после успешного расчёта; проверить тестами: `quote` и неудачные попытки не меняют `uses`, лимит исчерпывается оформлением, `Order.promo_code` нормализован
- [x] 4.3 Реализовать возврат использования в `cancel`; проверить тестами: отмена возвращает лимит, повторная отмена не меняет счётчик, отмена после истечения срока работает, отмена без промокода счётчик не трогает

## 5. Проверка

- [x] 5.1 Проверить обратную совместимость: тесты старых вызовов `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)` дают прежние суммы и нулевые `discount`; полный `python -m pytest -q` зелёный, `shop/cli.py`, `shop/reports.py` и существующие тесты не изменены (`git diff --stat`)
- [x] 5.2 Сверить публичный API реализации с proposal и specs (имена модулей, классов, сигнатуры, порядок и вид параметров, поля `PromoCode`, `LineTotal.discount`, `OrderTotal.discount`, `Order.promo_code`, значения `DiscountKind`, иерархия ошибок) и зафиксировать расхождения или их отсутствие
