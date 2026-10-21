## Purpose

Описывает промокод, его проверку при создании и реестр, который по введённому человеком коду определяет, действует ли он и не исчерпан ли лимит использований.

## ADDED Requirements

### Requirement: Модель PromoCode и её инварианты
`PromoCode` SHALL быть `@dataclass(frozen=True)` с полями `code`, `kind: DiscountKind`, `value: Decimal`, `min_order_amount: Decimal = Decimal("0.00")`, `starts_at: datetime | None = None`, `expires_at: datetime | None = None`, `max_uses: int | None = None`, `excluded_categories: frozenset[Category] = frozenset()`. `DiscountKind` SHALL быть `StrEnum` со значениями `PERCENT` и `FIXED`. Инварианты SHALL проверяться при создании, нарушение SHALL приводить к `ValidationError`:

- `code` после нормализации (обрезка пробелов, верхний регистр) непустой и хранится в нормализованном виде;
- `value` — `Decimal`; для `PERCENT` в диапазоне (0, 100], для `FIXED` больше 0 и не более двух знаков после запятой;
- `min_order_amount` — `Decimal`, не отрицательный, не более двух знаков;
- `starts_at` и `expires_at` — aware `datetime`; если заданы оба, `starts_at` строго раньше `expires_at`;
- `max_uses` — `None` или целое `>= 1` (не `bool`);
- `excluded_categories` — набор значений `Category`.

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode(code="  summer10 ", ...)`
- **THEN** `promo.code == "SUMMER10"`

#### Scenario: Пустой код отвергается
- **WHEN** создаётся `PromoCode` с `code="   "`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Недопустимые значения скидки
- **WHEN** создаётся процентный код со `value` равным `0` или `100.01`, либо фиксированный со `value` равным `0` или `10.001`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Процент 100 допустим
- **WHEN** создаётся процентный код со `value=Decimal("100")`
- **THEN** объект создан без ошибки

#### Scenario: Некорректный срок или лимит
- **WHEN** `starts_at` равен или позже `expires_at`, либо datetime naive, либо `max_uses` равен `0`
- **THEN** выбрасывается `ValidationError`

### Requirement: Регистрация кодов в PromoRegistry
`PromoRegistry(clock: Clock)` SHALL хранить коды по нормализованному ключу. `add(promo)` SHALL регистрировать код; повторное добавление того же нормализованного кода (в любом регистре и с пробелами) SHALL приводить к `ValidationError`.

#### Scenario: Дубликат в другом регистре
- **WHEN** добавлен код `SUMMER10`, затем добавляется код `summer10`
- **THEN** выбрасывается `ValidationError`, исходный код остаётся без изменений

### Requirement: Разрешение кода через resolve
`PromoRegistry.resolve(code: str) -> PromoCode` SHALL нормализовать `code` (обрезка пробелов, верхний регистр) и проверять строго по порядку: (1) код существует, иначе `UnknownPromoCodeError`; (2) код действует в текущий момент, иначе `PromoExpiredError`; (3) лимит не исчерпан, иначе `PromoConditionsError`. Время SHALL браться только из часов, переданных в конструктор реестра. Срок действия SHALL быть полуоткрытым интервалом `[starts_at, expires_at)`; граница `None` означает отсутствие ограничения. Акция, которая ещё не началась, SHALL давать `PromoExpiredError`. `resolve` SHALL не менять счётчик использований. `resolve("")` и `resolve` пробельной строки SHALL давать `UnknownPromoCodeError`.

#### Scenario: Регистр и пробелы не важны
- **WHEN** зарегистрирован `SUMMER10` и вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот `PromoCode`

#### Scenario: Неизвестный код
- **WHEN** вызывается `resolve("NOPE")` или `resolve("")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Начало срока включительно
- **WHEN** текущее время ровно `starts_at`
- **THEN** код разрешается

#### Scenario: Конец срока исключительно
- **WHEN** текущее время ровно `expires_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Порядок проверок
- **WHEN** код просрочен и при этом лимит исчерпан
- **THEN** выбрасывается `PromoExpiredError`, а не `PromoConditionsError`

#### Scenario: Лимит исчерпан
- **WHEN** у кода `max_uses=2` и оформлены два заказа с ним
- **THEN** `resolve` выбрасывает `PromoConditionsError`

### Requirement: Учёт использований
`PromoRegistry.uses(code: str) -> int` SHALL возвращать число действующих (оформленных и не отменённых) заказов с этим кодом (код нормализуется; для зарегистрированного кода без использований — `0`; для неизвестного — `UnknownPromoCodeError`). Использование SHALL засчитываться только при успешном оформлении заказа через `place_order`. `resolve`, `quote`, `calculate_total` и неудачные попытки оформления SHALL не менять счётчик. Учёт использования (`consume`) SHALL повторно проверять лимит и при исчерпании выбрасывать `PromoConditionsError`. `PromoRegistry.release(code: str) -> None` SHALL уменьшать счётчик на один, не опуская его ниже нуля; для неизвестного кода — `UnknownPromoCodeError`. Возврат вызывается при отмене заказа с этим кодом.

#### Scenario: Расчёт не расходует лимит
- **WHEN** вызываются `resolve`, `quote` и `calculate_total` с кодом
- **THEN** `uses(code) == 0`

#### Scenario: Возврат использования
- **WHEN** `uses(code) == 1` и вызывается `release(code)`
- **THEN** `uses(code) == 0`; повторный `release` оставляет `0`

### Requirement: Иерархия ошибок промокодов
`PromoError` SHALL наследовать `ShopError`. `UnknownPromoCodeError`, `PromoExpiredError` и `PromoConditionsError` SHALL быть независимыми прямыми наследниками `PromoError`: ни один не является подклассом другого и ни один не является `ValidationError`.

#### Scenario: Независимость исключений
- **WHEN** проверяется иерархия
- **THEN** каждый из трёх классов является подклассом `PromoError` и `ShopError` и не является подклассом двух других
