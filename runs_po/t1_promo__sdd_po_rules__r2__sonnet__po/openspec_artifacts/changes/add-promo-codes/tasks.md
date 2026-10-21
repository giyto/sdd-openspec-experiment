## 1. Ошибки и модель промокода

- [x] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и независимых наследников `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить тестом `issubclass` (тесты в новом `tests/test_promo.py`)
- [x] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация кода, все инварианты из spec `promo-codes`); проверить тестами на валидные и невалидные значения (процент 0/100/100.01, фикс с тремя знаками, naive-даты, `starts_at >= expires_at`, `max_uses` 0/True)

## 2. Реестр

- [x] 2.1 Реализовать `PromoRegistry(clock)`: `add` (дубликат — `ValidationError`), `resolve` (порядок: существование → срок `[starts_at, expires_at)` → лимит), `uses`, внутренний `_record_use`, `_release_use` (не ниже нуля); проверить тестами с `FixedClock`: границы срока, «ещё не началось» = `PromoExpiredError`, `resolve("")` = `UnknownPromoCodeError`, регистр и пробелы, приоритет `PromoExpiredError` над исчерпанным лимитом

## 3. Расчёт итогов

- [x] 3.1 Добавить `discount` (по умолчанию `ZERO`) в `LineTotal` и `OrderTotal` и параметр `promo` (keyword-only) в `calculate_total`; убедиться, что существующие `tests/test_pricing.py` проходят без изменений
- [x] 3.2 Реализовать участвующие строки, размер скидки (процент с `ROUND_HALF_UP`, фикс с ограничением суммой), проверку `min_order_amount` и отсутствия участвующих строк; проверить тестами в новом `tests/test_pricing_promo.py` (исключённые категории, `GIFT_CARD`, фикс больше суммы, граница минимума)
- [x] 3.3 Реализовать точную построчную раскладку (целые копейки, наибольшие остатки, ничьи по порядку корзины), налог с суммы после скидки, доставку без изменений; проверить тестами: сумма `LineTotal.discount` == `OrderTotal.discount` (включая 3 × 33.33), `total = subtotal - discount + shipping + tax`, порог бесплатной доставки по сумме после скидки (3000 и 10% — платная доставка; 4000 и 10% — бесплатная)

## 4. Заказы

- [x] 4.1 Добавить `promos` в `OrderService.__init__`, `promo_code` в `quote` и `place_order`, `Order.promo_code`; пустой/пробельный код = без кода, нет реестра = `UnknownPromoCodeError`; использование записывается после `store.add`; `cancel` возвращает использование; проверить тестами в новом `tests/test_orders_promo.py` (нормализованный `order.promo_code`, `quote` не меняет `uses`, неудачные `place_order` не меняют `uses` и не сохраняют заказ, лимит `max_uses=1`, старые вызовы дают прежние суммы; отмена заказа с кодом уменьшает `uses` на 1, повторная отмена не уменьшает, отмена без кода не меняет, переоформление при `max_uses=1` после отмены проходит)

## 5. Документация и финальная проверка

- [x] 5.1 Обновить README («Правила расчёта»: формула итога со скидкой, правила промокодов) и убедиться, что `shop/cli.py`, `shop/reports.py` и существующие тесты не изменены (`git diff --stat`)
- [x] 5.2 Запустить `python -m pytest -q` и убедиться, что все старые и новые тесты проходят
- [x] 5.3 Сверить публичный API реализации с proposal и specs: имена, порядок и вид параметров (`promo` keyword-only, `promo_code: str | None`), поля и значения enum, три независимых наследника `PromoError`; расхождений быть не должно
