## 1. Модель промокода и реестр (`shop/promo.py`)

- [x] 1.1 Добавить `DiscountKind.FREE_SHIPPING` и поля `max_discount`, `max_uses_per_customer` в конец `PromoCode` с валидацией по спецификации
- [x] 1.2 Хранить использования по клиентам; `consume`/`release` принимают `customer_id=None`
- [x] 1.3 `resolve(code, customer_id=None)` с проверкой лимита на клиента после общего лимита; `uses(code, customer_id=None)`; валидация типа `customer_id`

## 2. Расчёт (`shop/pricing.py`)

- [x] 2.1 Потолок `max_discount` для `PERCENT` и потолок 50 % (через `quantize_money`) для `FIXED`
- [x] 2.2 `FREE_SHIPPING`: нулевая скидка на товары, условия заказа как у других видов
- [x] 2.3 Порог доставки по `subtotal` до скидки
- [x] 2.4 `OrderTotal.shipping_discount` (последнее поле, умолчание `Decimal("0.00")`), расчёт для `FREE_SHIPPING`
- [x] 2.5 Раскладка копеек: остаток, затем большая сумма строки, затем индекс
- [x] 2.6 Обновить docstring модуля

## 3. Заказы (`shop/orders.py`)

- [x] 3.1 `Order.customer_id` в конце; `quote`/`place_order` с keyword-only `customer_id`, передача в `resolve` и `consume`
- [x] 3.2 `cancel`: возврат использования (общего и клиента) только при `now < created_at + 24 ч` по часам сервиса

## 4. Тесты и документация

- [x] 4.1 Новые тесты отдельными файлами в `tests/` по сценариям спецификаций (граница 24 часов, 50 %, порог, лимиты на клиента)
- [x] 4.2 Запустить `python -m pytest -q`; существующие тесты не править; упавшие из-за отменённых правил (`test_shipping_threshold_after_discount`, `test_fixed_capped` и т. п.) перечислить в отчёте
- [x] 4.3 Обновить раздел «Правила расчёта» в `README.md`

## 5. Сверка публичного API

- [x] 5.1 Сверить реализацию с proposal и specs: `DiscountKind.FREE_SHIPPING`, `PromoCode.max_discount`/`max_uses_per_customer` (в конце), `PromoRegistry.resolve`/`uses` с `customer_id`, `OrderTotal.shipping_discount`, `OrderService.quote`/`place_order` с keyword-only `customer_id`, `Order.customer_id`; `cli.py` и `reports.py` не изменены
