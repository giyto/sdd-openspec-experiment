# promo-codes Specification

## Purpose
Промокод как модель данных и реестр промокодов: хранение, поиск, проверка срока действия и лимита, счётчик использований.

## Requirements

### Requirement: Модель PromoCode и её инварианты
`PromoCode` (`shop/promo.py`) SHALL быть неизменяемой моделью с полями `code`, `kind: DiscountKind`, `value`, `min_order_amount` (по умолчанию `Decimal("0.00")`), `starts_at`, `expires_at`, `max_uses` (по умолчанию `None`), `excluded_categories` (по умолчанию пустой `frozenset`). `DiscountKind` SHALL иметь значения `PERCENT` и `FIXED`. Код SHALL нормализоваться (обрезка пробелов по краям, верхний регистр). Нарушение любого инварианта SHALL давать `ValidationError`:
- код после нормализации непустой;
- `PERCENT`: `value` — `Decimal` в диапазоне `(0, 100]`; `FIXED`: `value` — `Decimal` больше 0 не более чем с двумя знаками после запятой;
- `min_order_amount` — `Decimal` не меньше 0, не более двух знаков после запятой;
- `starts_at` и `expires_at` — aware `datetime` или `None`; если заданы оба, `starts_at` строго раньше `expires_at`;
- `max_uses` — `None` или целое `>= 1` (не `bool`);
- `excluded_categories` — `frozenset` из `Category`.

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode(code="  summer10 ", ...)`
- **THEN** `code` равен `"SUMMER10"`

#### Scenario: Пустой код отвергается
- **WHEN** создаётся `PromoCode` с кодом `"   "`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Процент вне диапазона
- **WHEN** `PERCENT` создаётся со значением `0` или `100.01`
- **THEN** выбрасывается `ValidationError`
- **AND** значение `100` допустимо

#### Scenario: Некорректный интервал или лимит
- **WHEN** `starts_at` не раньше `expires_at`, либо дата без часового пояса, либо `max_uses` равен `0`
- **THEN** выбрасывается `ValidationError`

### Requirement: Иерархия ошибок промокодов
Система SHALL предоставлять `PromoError(ShopError)` и три его независимых наследника: `UnknownPromoCodeError` (кода нет), `PromoExpiredError` (вне срока действия), `PromoConditionsError` (лимит исчерпан или заказ не подходит). Ни один из трёх SHALL NOT быть подклассом другого.

#### Scenario: Независимость исключений
- **WHEN** перехватывается `PromoExpiredError`
- **THEN** `UnknownPromoCodeError` и `PromoConditionsError` им не перехватываются
- **AND** все три перехватываются как `PromoError` и как `ShopError`

### Requirement: Регистрация кодов в реестре
`PromoRegistry(clock)` SHALL принимать `Clock` через конструктор и хранить коды по нормализованному ключу. `add` повторного кода (с учётом регистра и пробелов) SHALL давать `ValidationError`.

#### Scenario: Дубликат
- **WHEN** добавляются коды `"SUMMER10"` и `" summer10"`
- **THEN** второй `add` выбрасывает `ValidationError`

### Requirement: Поиск кода и порядок проверок
`resolve(code)` SHALL нормализовать вводимый код и возвращать `PromoCode`, если он существует, действует в текущий момент и не исчерпан. Проверки идут строго по порядку: существование (`UnknownPromoCodeError`), срок действия (`PromoExpiredError`), лимит (`PromoConditionsError`). Текущее время SHALL браться только у внедрённых часов. Срок действия — полуоткрытый интервал `[starts_at, expires_at)`; граница `None` означает отсутствие ограничения. До `starts_at` код тоже даёт `PromoExpiredError`. `resolve("")` и `resolve` от пробельной строки SHALL давать `UnknownPromoCodeError`.

#### Scenario: Регистронезависимый поиск
- **WHEN** зарегистрирован `"SUMMER10"`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот `PromoCode`

#### Scenario: Границы срока
- **WHEN** текущее время равно `starts_at`
- **THEN** код действует
- **WHEN** текущее время равно `expires_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Просроченный и исчерпанный код
- **WHEN** код одновременно просрочен и исчерпан
- **THEN** выбрасывается `PromoExpiredError`, а не `PromoConditionsError`

#### Scenario: Лимит исчерпан
- **WHEN** число использований равно `max_uses`
- **THEN** `resolve` выбрасывает `PromoConditionsError`

#### Scenario: Неизвестный и пустой код
- **WHEN** вызывается `resolve("NOPE")` или `resolve("")`
- **THEN** выбрасывается `UnknownPromoCodeError`

### Requirement: Счётчик использований
`uses(code)` SHALL возвращать число учтённых использований кода (для нового кода `0`), нормализуя ввод; для неизвестного кода — `UnknownPromoCodeError`. Использование SHALL учитываться только при успешном оформлении заказа (см. `promo-orders`); `resolve` и `uses` счётчик не меняют. Счётчик SHALL NOT уходить ниже нуля.

#### Scenario: Начальное значение
- **WHEN** код только что добавлен
- **THEN** `uses(code)` равен `0`, и повторные `resolve` его не меняют
