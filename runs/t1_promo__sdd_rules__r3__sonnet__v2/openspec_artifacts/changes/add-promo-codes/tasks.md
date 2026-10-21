## 1. Ошибки и модель промокода

- [x] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и независимые `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить новым тестом `tests/test_promo_errors.py`, что `issubclass` между тремя классами ложен, а все они наследуют `PromoError` и `ShopError`
- [x] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация `code` через `normalize_key`, все инварианты из спецификации `promo-codes`, `logger = logging.getLogger(__name__)`); проверить тестами в `tests/test_promo.py` на каждый инвариант и на нормализацию
- [x] 1.3 Реализовать `PromoRegistry(clock)`: `add` (дубликат → `ValidationError`), `resolve` (порядок: существует → `[starts_at, expires_at)` → лимит), `uses`, `consume`, `release`; проверить в `tests/test_promo.py` с `FixedClock`: границы интервала, «ещё не началась» → `PromoExpiredError`, порядок проверок, `resolve("")` → `UnknownPromoCodeError`, регистр и пробелы, счётчик не меняется от `resolve`/`uses`

## 2. Расчёт итогов со скидкой

- [x] 2.1 В `shop/pricing.py` добавить `LineTotal.discount` и `OrderTotal.discount` (по умолчанию `ZERO`, последние поля) и параметр `*, promo: PromoCode | None = None`; проверить, что весь существующий `tests/test_pricing.py` проходит без изменений и что вызовы без промокода дают прежние суммы
- [x] 2.2 Реализовать участвующие строки, условия заказа (нет участвующих → `PromoConditionsError`; минималка по участвующим до скидки, равенство подходит) и размер скидки (процент `ROUND_HALF_UP`, фикс ограничен суммой); проверить в `tests/test_pricing_promo.py` сценариями спецификации `promo-pricing` (сертификат и исключённая категория не в счёт, ровно 1000 при минималке 1000, только сертификаты при минималке 0)
- [x] 2.3 Реализовать целочисленную раскладку методом наибольшего остатка (ничья — раньше в корзине), налог с суммы после скидки, порог доставки по сумме после скидки; проверить в `tests/test_pricing_promo.py`: сумма скидок строк равна общей, `3.34/3.33/3.33`, ничья остатков, скидка 100 %, `total = subtotal - discount + shipping + tax`, порог доставки после скидки, доставка не уменьшается

## 3. Заказы

- [x] 3.1 В `shop/orders.py` добавить `Order.promo_code` (последнее поле, по умолчанию `None`), `OrderService(..., promos=None)`, `quote(cart, promo_code=None)` и `place_order(cart, promo_code=None)` с обработкой пустого/пробельного ввода как «без кода» и порядком проверок из спецификации `promo-orders`; проверить в `tests/test_orders_promo.py`, включая отсутствие реестра, регистр/пробелы и неизменный счётчик после `quote`
- [x] 3.2 Засчитывать использование в `place_order` только после сохранения заказа и возвращать его в `cancel` (не ниже 0, повторная отмена не меняет счётчик); проверить в `tests/test_orders_promo.py`: неудачные попытки не меняют счётчик/хранилище/нумерацию, лимит 1 → второй заказ отклонён, после `cancel` оформление снова проходит, отмена после истечения срока кода тоже возвращает использование
- [x] 3.3 Экспортировать новые имена в `shop/__init__.py`, дополнить правила расчёта в `README.md`; проверить, что `python -m pytest -q` проходит целиком, существующие тесты, `shop/cli.py` и `shop/reports.py` не изменены (`git diff --stat`)

## 4. Сверка API

- [x] 4.1 Сверить публичный API реализации с proposal и specs: имена, порядок и вид параметров (`calculate_total(cart, shipping=None, tax=None, *, promo=None)`, `OrderService(..., promos=None)`, `quote/place_order(cart, promo_code=None)`), поля `LineTotal.discount`, `OrderTotal.discount`, `Order.promo_code`, значения `DiscountKind`, три независимых наследника `PromoError`; проверить скриптом `inspect.signature` и ручным сравнением с тикетом
