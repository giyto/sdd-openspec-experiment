## Purpose

Описывает модель промокода, реестр промокодов с проверкой существования, срока действия и лимита использований, а также ошибки промокодов.

## ADDED Requirements

### Requirement: Инварианты PromoCode
`PromoCode` SHALL быть неизменяемым объектом с полями `code`, `kind` (`DiscountKind.PERCENT` или `DiscountKind.FIXED`), `value`, `min_order_amount` (по умолчанию `Decimal("0.00")`), `starts_at`, `expires_at`, `max_uses` (по умолчанию `None`), `excluded_categories` (по умолчанию пустой `frozenset`). Нарушение любого инварианта SHALL приводить к `ValidationError`: пустой после нормализации `code`; `value` не `Decimal`; для `PERCENT` `value` вне `(0, 100]`; для `FIXED` `value <= 0` или более двух знаков после запятой; `min_order_amount` отрицательная или более двух знаков; `starts_at`/`expires_at` не aware; `starts_at` не раньше `expires_at` (когда заданы оба); `max_uses` не `None` и не целое `>= 1` (`bool` не допускается); `excluded_categories` содержит не `Category`. `code` SHALL храниться в нормализованном виде (без пробелов по краям, в верхнем регистре).

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode` с `code="  summer10 "`, `kind=DiscountKind.PERCENT`, `value=Decimal("10")`
- **THEN** `promo.code == "SUMMER10"`

#### Scenario: Процент вне диапазона
- **WHEN** создаётся процентный код со `value` равным `0` или `100.01`
- **THEN** выбрасывается `ValidationError`; при `value == 100` объект создаётся

#### Scenario: Некорректный интервал
- **WHEN** `starts_at` равен `expires_at` или позже него
- **THEN** выбрасывается `ValidationError`

#### Scenario: Некорректный лимит
- **WHEN** `max_uses` равен `0`, `-1` или `True`
- **THEN** выбрасывается `ValidationError`

### Requirement: Иерархия ошибок промокодов
`PromoError` SHALL наследоваться от `ShopError`. `UnknownPromoCodeError`, `PromoExpiredError` и `PromoConditionsError` SHALL быть независимыми наследниками `PromoError`: ни один из них не является подклассом другого и не является `ValidationError`.

#### Scenario: Независимость классов
- **WHEN** проверяется `issubclass` между тремя конкретными ошибками
- **THEN** он ложен для любой пары, а каждая является подклассом `PromoError` и `ShopError`

### Requirement: Добавление кодов в реестр
`PromoRegistry(clock)` SHALL хранить коды по нормализованному ключу. `add` повторного кода (с учётом нормализации, например `"summer"` и `" SUMMER "`) SHALL выбрасывать `ValidationError`.

#### Scenario: Дубликат в другом регистре
- **WHEN** добавлены коды `SUMMER` и затем `summer`
- **THEN** второй `add` выбрасывает `ValidationError`

### Requirement: Поиск и проверка кода через resolve
`resolve(code)` SHALL нормализовать вход (обрезка пробелов, верхний регистр) и проверять строго по порядку: (1) код существует, иначе `UnknownPromoCodeError`; (2) код действует в текущий момент по часам реестра, иначе `PromoExpiredError`; (3) лимит не исчерпан, иначе `PromoConditionsError`. При успехе SHALL возвращаться `PromoCode`. Интервал действия полуоткрытый `[starts_at, expires_at)`; граница `None` означает отсутствие ограничения. Время SHALL браться только из часов, переданных реестру. Не-строковый вход SHALL приводить к `ValidationError`. `resolve("")` и `resolve("   ")` SHALL выбрасывать `UnknownPromoCodeError`.

#### Scenario: Ввод в другом регистре и с пробелами
- **WHEN** зарегистрирован `SUMMER10`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот код

#### Scenario: Граница начала включительна
- **WHEN** текущее время равно `starts_at`
- **THEN** `resolve` возвращает код

#### Scenario: Граница конца исключительна
- **WHEN** текущее время равно `expires_at`
- **THEN** `resolve` выбрасывает `PromoExpiredError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** `resolve` выбрасывает `PromoExpiredError` (отдельного исключения нет)

#### Scenario: Порядок проверок
- **WHEN** код просрочен и при этом его лимит исчерпан
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Исчерпанный лимит
- **WHEN** у кода `max_uses=2` и `uses(code) == 2`
- **THEN** `resolve` выбрасывает `PromoConditionsError`

#### Scenario: Пустой ввод
- **WHEN** вызывается `resolve("")`
- **THEN** выбрасывается `UnknownPromoCodeError`

### Requirement: Счётчик использований
`uses(code)` SHALL возвращать число засчитанных использований кода (изначально `0`), нормализуя вход как `resolve`; для неизвестного кода SHALL выбрасываться `UnknownPromoCodeError`. `resolve` и `uses` SHALL NOT менять счётчик. Реестр SHALL дополнительно предоставлять `consume(code)` (увеличить на 1) и `release(code)` (уменьшить на 1, но не ниже 0), которыми пользуется только оформление и отмена заказа.

#### Scenario: Свежий код
- **WHEN** код только что добавлен
- **THEN** `uses(code) == 0`

#### Scenario: Чтение не меняет счётчик
- **WHEN** несколько раз вызываются `resolve` и `uses`
- **THEN** `uses(code)` не изменяется
