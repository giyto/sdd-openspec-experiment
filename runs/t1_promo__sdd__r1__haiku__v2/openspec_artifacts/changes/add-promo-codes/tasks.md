## 1. Ошибки и модель промокода

- [x] 1.1 Добавить `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError` в `shop/errors.py`; проверить, что все четыре ловятся как `ShopError` и что наследники не являются друг другом (новый файл `tests/test_promo_errors.py`).
- [x] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация кода, проверки значений из spec «Регистрация и нормализация кода»); проверить тестами в `tests/test_promo_code.py`: нормализация пробелов и регистра, отказ при процента 0 и 150, фиксированной скидке с дробью больше копеек, `max_uses = 0`, `starts_at >= expires_at`.

## 2. Реестр промокодов

- [x] 2.1 Реализовать `PromoRegistry` (`add`, `resolve`, `uses`, `consume`, `release`) с порядком проверок существование → срок → лимит; проверить тестами в `tests/test_promo_registry.py`: неизвестный и пустой код, полуоткрытый срок `[starts_at, expires_at)`, `PromoExpiredError` до старта, порядок «срок раньше лимита», повторная регистрация отклоняется.
- [x] 2.2 Проверить, что `consume` отказывает при исчерпанном лимите без изменения счётчика, а `release` уменьшает счётчик на единицу; тесты в `tests/test_promo_registry.py`.

## 3. Расчёт скидки в `pricing.py`

- [x] 3.1 Добавить `LineTotal.discount` и `OrderTotal.discount` (по умолчанию `ZERO`) последними полями; проверить `python -m pytest -q`: существующие тесты проходят без изменений.
- [x] 3.2 Реализовать `calculate_total(..., *, promo=None)`: участвующие строки, минимальная сумма, процентная и фиксированная скидка с ограничением суммой участвующих строк; проверить в `tests/test_pricing_promo.py` ошибки `PromoConditionsError` (нет участвующих строк, сумма ниже минимума, сумма ровно равна минимуму — проходит).
- [x] 3.3 Реализовать раскладку скидки по строкам в целых копейках (остаток по убыванию, при равенстве — по порядку корзины); проверить примерами из spec: `0.33`/`0.67`, `0.34`/`0.33`/`0.33`, `250.00`/`45.00`, процент `15.02` от `100.10`.
- [x] 3.4 Налог строки с суммы после скидки и порог бесплатной доставки по `subtotal - discount`; проверить в `tests/test_pricing_promo.py` итог `subtotal = 3950.00`, `discount = 295.00`, `tax = 490.50`, `total = 4145.50` и сценарий «скидка переводит заказ под порог» (3100.00 → 2790.00, доставка 299.00).

## 4. Оформление и отмена заказов

- [x] 4.1 Добавить `Order.promo_code: str | None = None` и параметр `promos` в `OrderService`; реализовать `_resolve_promo` (пустой или `None` код → без скидки и без обращения к реестру); `quote(cart, promo_code=None)` и `place_order(cart, promo_code=None)`; проверить в `tests/test_orders_promo.py`: сервис без реестра выбрасывает `UnknownPromoCodeError` для непустого кода, а `"   "` работает как отсутствие кода.
- [x] 4.2 Учёт использований: `place_order` вызывает `consume` после расчёта и до `store.add`; `quote` и неудачные попытки счётчик не меняют; `cancel` заказа с промокодом вызывает `release`. Проверить в `tests/test_orders_promo.py`: счётчик растёт только при успешном оформлении, после отмены уменьшается, отмена заказа без промокода счётчики не трогает, номера заказов не сжигаются при ошибке.

## 5. Документация и проверка

- [x] 5.1 Добавить в `README.md` раздел о промокодах (участвующие строки, минимальная сумма, раскладка скидки, налог, доставка, счётчик использований); проверить, что формулировки совпадают со spec `promo-discounts` и `promo-codes`.
- [x] 5.2 Запустить `python -m pytest -q` целиком и убедиться, что все тесты (старые и новые) проходят; проверить `git diff --stat -- tests/test_cart.py tests/test_catalog.py tests/test_cli.py tests/test_money.py tests/test_orders.py tests/test_pricing.py tests/test_reports.py tests/conftest.py` — diff пустой.
- [x] 5.3 Проверить, что `shop/cli.py` и `shop/reports.py` не изменены: `git diff --stat -- shop/cli.py shop/reports.py` пуст.
- [x] 5.4 Запустить `openspec validate add-promo-codes --strict` и убедиться, что проверка проходит без ошибок.
