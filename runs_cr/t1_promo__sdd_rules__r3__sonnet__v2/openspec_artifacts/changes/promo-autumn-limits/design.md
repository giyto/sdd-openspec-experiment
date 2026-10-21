## Context

Модули `shop/promo.py`, `shop/pricing.py`, `shop/orders.py` реализуют SHOP-412. Деньги считаются только через `quantize_money` (`ROUND_HALF_UP`), интервалы времени полуоткрытые, время берётся из внедрённых `Clock`, ошибки наследуют `ShopError`.

## Goals / Non-Goals

**Goals:** реализовать правила тикета без изменения заданных публичных сигнатур; сохранить совместимость старых вызовов.
**Non-Goals:** `shop/cli.py`, `shop/reports.py`, постоянное хранение, изменение налогов.

## Decisions

1. **Потолок фикса 50 %.** Обсуждение (22.10) поправляет тикет: согласовано 50 %. Скидка `FIXED` = `min(value, base, quantize_money(base * 0.5))`, где `base` — сумма участвующих строк. Константа именованная, в `pricing.py`.
2. **`max_discount`.** Скидка `PERCENT` = `min(quantize_money(base * value / 100), max_discount)`. Валидация: `Decimal`, конечное, `> 0`, не более двух знаков; задано у `FIXED`/`FREE_SHIPPING` — `ValidationError`.
3. **`FREE_SHIPPING`.** `value == 0` (любое представление нуля, тип `Decimal`), иначе `ValidationError`. Скидка на товары `0.00`, у всех строк `discount == 0.00`, налог не меняется. Условия заказа проверяются как у остальных видов (нужны участвующие строки, `min_order_amount`): единое правило проще, а корзина только из сертификатов и так не платит за доставку. `shipping` = `0.00`; `shipping_discount` = стоимость доставки по обычной политике (с порогом и «только сертификаты») без кода, `0.00`, если платить было нечего. `OrderTotal.shipping_discount: Decimal = ZERO` — последнее поле. Формула `total = subtotal - discount + shipping + tax` не меняется.
4. **Порог доставки** сравнивается с `subtotal` (до скидки): в `ShippingPolicy.cost_for` передаётся `subtotal`.
5. **Раскладка копеек.** Ключ сортировки при раздаче лишних копеек: `(-остаток, -сумма строки, индекс)`.
6. **Учёт по клиентам.** Реестр хранит счётчики по `(код, customer_id)`. `customer_id` сравнивается как есть (без `strip`/регистра); пустая строка — обычное значение, `None` — «клиента нет»; иной тип — `ValidationError`. `consume`/`release` получают необязательный `customer_id=None` (дополнение API); при заданном `customer_id` меняется и счётчик клиента, `release` не опускает ниже 0. Клиент учитывается даже у кодов без лимита на клиента.
7. **Порядок проверок:** код существует → действует → общий лимит → лимит на клиента (нет `customer_id` или `uses(code, customer_id) >= max_uses_per_customer` — `PromoConditionsError`) → условия заказа в `calculate_total`. `uses(code, customer_id)` для неизвестного клиента — `0`.
8. **Возврат при отмене.** `cancel` сравнивает `self._clock.now()` с `order.created_at`: возврат, если `now < created_at + 24 ч` (при `now < created_at` тоже). Иначе заказ всё равно `CANCELLED`, счётчики (общий и клиента) не меняются. Возврат идёт и по клиенту заказа.
9. **`customer_id` в `place_order`** сохраняется в `Order.customer_id` (последнее поле, умолчание `None`) и передаётся в `consume`.

## Risks / Trade-offs

- Существующие тесты `test_shipping_threshold_after_discount`, `test_fixed_capped` (500 при сумме 300 теперь даёт 150.00) закрепляют отменяемые правила и упадут. Рамка «тесты не меняем» сохраняется: при реализации их не править, а сообщить пользователю об устаревании. Новые тесты — в новых файлах.
- Выбор 50 % вместо 30 % опирается на сообщение из обсуждения; при ошибке меняется одна константа.

## Implementation notes

- Три существующих теста закрепляют отменённые правила и падают, как и предполагалось; не правились: `tests/test_pricing_promo.py::test_fixed_capped`, `tests/test_pricing_promo.py::test_shipping_threshold_after_discount`, `tests/test_orders_promo.py::test_cancel_after_expiry_releases`.
- Проверка типа `customer_id` также выполняется в `consume`/`release`/`uses`.
