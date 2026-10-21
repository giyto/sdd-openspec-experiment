# order-promos Specification

## Purpose
Определяет работу промокодов в `OrderService`: расчёт с кодом, оформление, учёт использований и возврат использования при отмене заказа.

## Requirements

### Requirement: Подключение реестра и ввод кода
`OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code: str | None = None)` и `place_order(cart, promo_code: str | None = None)` SHALL принимать код как введён человеком. Значение `None`, пустая строка или строка из пробелов означает «без промокода»: результат MUST совпадать с вызовом без кода и не вызывать ошибку. Нестроковый `promo_code` MUST давать `ValidationError`. Если непустой код передан, а `promos` не задан, он MUST считаться неизвестным (`UnknownPromoCodeError`). Вызовы `quote(cart)` и `place_order(cart)` без кода работают как прежде.

#### Scenario: Пустое поле формы
- **WHEN** `quote(cart, "")` или `place_order(cart, "   ")`
- **THEN** скидки нет, ошибки нет, `Order.promo_code is None`

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos`, вызывается `quote(cart, "SUMMER10")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Ввод в другом регистре
- **WHEN** зарегистрирован `SUMMER10`, вызывается `place_order(cart, " summer10 ")`
- **THEN** скидка применяется, `Order.promo_code == "SUMMER10"`

### Requirement: Порядок проверок и ошибки
При непустом коде сервис SHALL сначала получить промокод через `PromoRegistry.resolve` (существование, срок, лимит), затем рассчитать итог с проверкой условий заказа. Ошибки — `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`. Пустая корзина MUST по-прежнему давать `EmptyCartError`, и эта проверка предшествует проверке кода. `quote` и `place_order` при ошибке MUST NOT менять счётчик, а `place_order` — не сохранять заказ.

#### Scenario: Неудачное оформление не тратит использование
- **WHEN** `place_order` с кодом завершается `PromoConditionsError` (например, не хватает до минимальной суммы)
- **THEN** `uses(code)` не изменился, заказ не сохранён

### Requirement: Учёт использований
Использованием считается только успешно оформленный заказ с кодом: `place_order` MUST увеличивать счётчик на единицу, и только после успешного расчёта, вместе с сохранением заказа. `quote`, `calculate_total` и неудачные попытки счётчик MUST NOT менять. Заказ хранит `Order.promo_code: str | None` — нормализованный код или `None`; `Order.total` содержит скидку.

#### Scenario: Расчёт не тратит лимит
- **WHEN** несколько раз вызывается `quote(cart, code)` при `max_uses=1`
- **THEN** `uses(code) == 0`, каждый вызов успешен

#### Scenario: Лимит исчерпывается оформлением
- **WHEN** `max_uses=1`, первый `place_order(cart, code)` успешен
- **THEN** `uses(code) == 1`, а второй `place_order(cart, code)` и `quote(cart, code)` выбрасывают `PromoConditionsError`

### Requirement: Возврат использования при отмене
`cancel(order_id)` для заказа с промокодом SHALL уменьшать счётчик этого кода на один, независимо от того, действует ли код на момент отмены. Отмена заказа без промокода счётчик не трогает. Повторная отмена (`InvalidOrderStateError`) MUST NOT менять счётчик. Счётчик не опускается ниже нуля. Если у сервиса нет реестра, отмена проходит без изменения счётчиков.

#### Scenario: Отмена возвращает лимит
- **WHEN** `max_uses=1`, заказ с кодом оформлен, затем отменён
- **THEN** `uses(code) == 0`, новый `place_order(cart, code)` проходит

#### Scenario: Повторная отмена
- **WHEN** отменённый заказ отменяют ещё раз
- **THEN** выбрасывается `InvalidOrderStateError`, счётчик не меняется

#### Scenario: Отмена после окончания срока
- **WHEN** срок кода истёк между оформлением и отменой
- **THEN** отмена успешна, счётчик уменьшен на один
