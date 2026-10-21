# promo-orders Specification

## Purpose
Описывает использование промокодов при расчёте и оформлении заказа: ввод кода покупателем, порядок проверок, учёт и возврат использований.

## Requirements

### Requirement: Совместимость без промокода
`OrderService.quote(cart)` и `OrderService.place_order(cart)` без кода SHALL работать как раньше; `Order.promo_code` SHALL быть `None`. `OrderService(..., promos: PromoRegistry | None = None)` без реестра SHALL считать любой непустой код неизвестным.

#### Scenario: Заказ без кода
- **WHEN** вызывается `place_order(cart)`
- **THEN** суммы прежние, `order.promo_code is None`, `order.total.discount == Decimal("0.00")`

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos`, вызывается `quote(cart, "SUMMER")`
- **THEN** выбрасывается `UnknownPromoCodeError`

### Requirement: Пустой ввод означает отсутствие кода
`promo_code` равный `None`, `""` или состоящий только из пробелов SHALL в `quote` и `place_order` означать «без промокода», а не ошибку (в том числе без реестра).

#### Scenario: Пробелы в поле формы
- **WHEN** вызывается `quote(cart, "   ")`
- **THEN** результат совпадает с `quote(cart)`

### Requirement: Расчёт с промокодом
При непустом `promo_code` сервис SHALL получить код через `PromoRegistry.resolve` (с нормализацией ввода) и применить его в расчёте итогов. Порядок проверок: пустая корзина (`EmptyCartError`); существует ли код (`UnknownPromoCodeError`); действует ли (`PromoExpiredError`); лимит (`PromoConditionsError`); условия заказа (`PromoConditionsError`). `quote` SHALL NOT менять счётчик использований.

#### Scenario: Ввод в другом регистре
- **WHEN** зарегистрирован `SUMMER10`, вызывается `quote(cart, " summer10 ")`
- **THEN** скидка применена, счётчик `uses("SUMMER10")` не изменился

#### Scenario: Просрочен и не подходит заказ
- **WHEN** код просрочен, а минимальная сумма не набрана
- **THEN** выбрасывается `PromoExpiredError`

### Requirement: Оформление заказа засчитывает использование
`place_order(cart, promo_code)` с применённым кодом SHALL сохранить в `Order.promo_code` нормализованный код и увеличить `uses` на 1 ровно при успешном оформлении. Любая ошибка (неизвестный, просроченный, исчерпанный код, неподходящий заказ, пустая корзина) SHALL оставлять счётчик, хранилище заказов и нумерацию без изменений.

#### Scenario: Успешный заказ
- **WHEN** `place_order(cart, "summer10")` успешен
- **THEN** `order.promo_code == "SUMMER10"`, `uses("SUMMER10")` увеличилось на 1, `order.total.discount` равна скидке расчёта

#### Scenario: Неудачная попытка
- **WHEN** `place_order` падает с `PromoConditionsError` из-за минимальной суммы
- **THEN** `uses` не изменился, заказ не сохранён

#### Scenario: Последнее использование
- **WHEN** у кода `max_uses=1`, первый `place_order` успешен
- **THEN** второй `place_order` и `quote` с этим кодом выбрасывают `PromoConditionsError`

### Requirement: Отмена возвращает использование
`cancel(order_id)` для заказа с промокодом SHALL после успешной отмены уменьшить `uses` кода на 1 (не ниже 0), даже если срок кода уже истёк. Для заказа без кода счётчики не меняются. Повторная отмена (`InvalidOrderStateError`) SHALL NOT менять счётчик.

#### Scenario: Переоформление после отмены
- **WHEN** заказ с кодом `max_uses=1` отменён
- **THEN** `uses == 0` и новый `place_order` с этим кодом успешен

#### Scenario: Повторная отмена
- **WHEN** отменённый заказ отменяют ещё раз
- **THEN** выбрасывается `InvalidOrderStateError`, счётчик не меняется
