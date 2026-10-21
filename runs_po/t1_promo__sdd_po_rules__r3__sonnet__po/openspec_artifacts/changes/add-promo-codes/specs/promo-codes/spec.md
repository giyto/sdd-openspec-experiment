## Purpose

Описывает промокоды и реестр, который хранит их, проверяет существование, срок действия и лимит использований и ведёт учёт использований.

## ADDED Requirements

### Requirement: Описание промокода
`PromoCode` SHALL быть неизменяемым объектом с полями `code`, `kind`, `value`, `min_order_amount`, `starts_at`, `expires_at`, `max_uses`, `excluded_categories`. При создании `code` MUST нормализоваться (обрезка пробелов по краям, верхний регистр). Некорректные данные MUST вызывать `ValidationError`: пустой после нормализации `code`; `value` не `Decimal`; для `PERCENT` значение вне (0, 100]; для `FIXED` значение ≤ 0 или с более чем двумя знаками после запятой; отрицательный `min_order_amount`; naive `datetime` в `starts_at`/`expires_at`; `starts_at` не раньше `expires_at` (когда заданы оба); `max_uses` не целое или < 1.

#### Scenario: Код нормализуется
- **WHEN** создаётся `PromoCode(code="  summer10 ", ...)`
- **THEN** `promo.code == "SUMMER10"`

#### Scenario: Процент вне диапазона
- **WHEN** создаётся `PERCENT`-код со значением `0` или `100.01`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Процент 100 допустим
- **WHEN** создаётся `PERCENT`-код со значением `100`
- **THEN** объект создаётся

#### Scenario: Пустой код
- **WHEN** создаётся `PromoCode` с `code` из одних пробелов
- **THEN** выбрасывается `ValidationError`

#### Scenario: Некорректный срок
- **WHEN** `starts_at` равен `expires_at` или позже него
- **THEN** выбрасывается `ValidationError`

### Requirement: Регистрация кодов
`PromoRegistry(clock)` SHALL хранить коды по нормализованному ключу. `add` повторного кода (в любом регистре и с пробелами) MUST вызывать `ValidationError`.

#### Scenario: Дубликат
- **WHEN** добавляются коды `SUMMER10` и ` summer10`
- **THEN** второй `add` выбрасывает `ValidationError`

### Requirement: Разрешение кода
`PromoRegistry.resolve(code)` SHALL нормализовать вводимый код и проверять строго по порядку: существование (`UnknownPromoCodeError`), действие в текущий момент по внедрённым часам (`PromoExpiredError`), лимит использований (`PromoConditionsError`). Срок действия — полуоткрытый интервал `[starts_at, expires_at)`; `None` означает отсутствие границы. Код до `starts_at` и код с `expires_at` в прошлом или в текущий момент MUST давать `PromoExpiredError`. `resolve("")` и `resolve` строки из пробелов MUST давать `UnknownPromoCodeError`. `resolve` не изменяет счётчик использований.

#### Scenario: Регистр и пробелы
- **WHEN** зарегистрирован `SUMMER10`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот `PromoCode`

#### Scenario: Неизвестный код
- **WHEN** вызывается `resolve("NOPE")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Граница начала включительна
- **WHEN** текущее время равно `starts_at`
- **THEN** код разрешается

#### Scenario: Граница конца исключительна
- **WHEN** текущее время равно `expires_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Порядок проверок
- **WHEN** код одновременно просрочен и исчерпан по лимиту
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Лимит исчерпан
- **WHEN** `uses(code) == max_uses`
- **THEN** `resolve` выбрасывает `PromoConditionsError`

#### Scenario: Пустая строка
- **WHEN** вызывается `resolve("")`
- **THEN** выбрасывается `UnknownPromoCodeError`

### Requirement: Независимые типы ошибок
`UnknownPromoCodeError`, `PromoExpiredError` и `PromoConditionsError` SHALL быть наследниками `PromoError`, а `PromoError` — наследником `ShopError`. Эти три класса MUST NOT наследоваться друг от друга.

#### Scenario: Иерархия
- **WHEN** проверяется `issubclass` для каждой пары из трёх ошибок
- **THEN** ни одна не является подклассом другой, все — подклассы `PromoError` и `ShopError`

### Requirement: Учёт использований
`PromoRegistry.uses(code)` SHALL возвращать число успешно оформленных и не отменённых заказов с этим кодом (код нормализуется; для незарегистрированного кода — `UnknownPromoCodeError`). Изначально 0.

#### Scenario: Отменённый заказ не учитывается
- **WHEN** заказ с кодом оформлен, а затем отменён
- **THEN** `uses(code)` уменьшается на один и снова равен значению до оформления

#### Scenario: Начальное значение
- **WHEN** код только что добавлен
- **THEN** `uses(code) == 0`
