## Purpose

Описывает промокод как модель данных, реестр промокодов (поиск, срок действия, лимит использований, учёт использований) и ошибки промокодов.

## ADDED Requirements

### Requirement: Модель PromoCode
`PromoCode` (`shop/promo.py`) SHALL быть `@dataclass(frozen=True)` с полями `code: str`, `kind: DiscountKind`, `value: Decimal`, `min_order_amount: Decimal = Decimal("0.00")`, `starts_at: datetime | None = None`, `expires_at: datetime | None = None`, `max_uses: int | None = None`, `excluded_categories: frozenset[Category] = frozenset()`. `DiscountKind` SHALL быть `StrEnum` со значениями `PERCENT` и `FIXED`. Инварианты SHALL проверяться при создании, нарушение SHALL приводить к `ValidationError`:

- `code` после нормализации (обрезка пробелов, верхний регистр) непустой и хранится в нормализованном виде;
- `kind` является `DiscountKind`; `value` является `Decimal`; для `PERCENT` `0 < value <= 100`; для `FIXED` `value > 0` и не более двух знаков после запятой;
- `min_order_amount` не отрицательна и имеет не более двух знаков после запятой;
- `starts_at` и `expires_at` aware (UTC), если заданы; если заданы оба, `starts_at` строго раньше `expires_at`;
- `max_uses` равен `None` или целому `>= 1` (bool не допускается);
- `excluded_categories` содержит только `Category`.

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode(code="  summer10 ", kind=DiscountKind.PERCENT, value=Decimal("10"))`
- **THEN** `promo.code == "SUMMER10"`

#### Scenario: Пустой код отвергается
- **WHEN** создаётся `PromoCode` с `code="   "`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Процент вне диапазона
- **WHEN** создаётся процентный `PromoCode` со `value` равным `0`, отрицательному числу или `100.01`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Сто процентов допустимо
- **WHEN** создаётся процентный `PromoCode` со `value=Decimal("100")`
- **THEN** объект создаётся

#### Scenario: Некорректная фиксированная скидка
- **WHEN** создаётся `PromoCode` вида `FIXED` со `value` равным `0`, отрицательному числу или `Decimal("10.005")`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Некорректный срок действия
- **WHEN** `starts_at` не раньше `expires_at`, либо одно из значений naive
- **THEN** выбрасывается `ValidationError`

#### Scenario: Некорректный лимит
- **WHEN** `max_uses` равен `0`, отрицательному числу или `True`
- **THEN** выбрасывается `ValidationError`

### Requirement: Иерархия ошибок промокодов
`shop/errors.py` SHALL содержать `PromoError(ShopError)` и три независимых наследника `PromoError`: `UnknownPromoCodeError` (кода нет), `PromoExpiredError` (вне срока действия), `PromoConditionsError` (лимит исчерпан или заказ не подходит). Ни один из трёх SHALL NOT быть подклассом другого.

#### Scenario: Независимость классов
- **WHEN** проверяется `issubclass` между `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`
- **THEN** ни один не является подклассом другого, все являются подклассами `PromoError` и `ShopError`

### Requirement: Реестр промокодов
`PromoRegistry(clock: Clock)` SHALL хранить промокоды по нормализованному коду. `add(promo)` SHALL добавлять код; повторное добавление того же нормализованного кода SHALL приводить к `ValidationError`. `resolve(code)` SHALL нормализовать вход (обрезка пробелов, верхний регистр) и возвращать `PromoCode` либо выбрасывать исключение. `uses(code)` SHALL возвращать число успешных использований (для нового кода `0`); код нормализуется так же, для неизвестного кода SHALL выбрасываться `UnknownPromoCodeError`.

#### Scenario: Регистронезависимый поиск
- **WHEN** добавлен `SUMMER10`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается тот же `PromoCode`

#### Scenario: Дубликат
- **WHEN** добавляются коды `"sale"` и `" SALE "`
- **THEN** второй `add` выбрасывает `ValidationError`

#### Scenario: Неизвестный код
- **WHEN** вызывается `resolve("NOPE")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Пустая строка в resolve
- **WHEN** вызывается `resolve("")` или `resolve("   ")`
- **THEN** выбрасывается `UnknownPromoCodeError`

### Requirement: Порядок проверок и срок действия
`resolve` SHALL проверять по порядку: (1) код существует, иначе `UnknownPromoCodeError`; (2) код действует сейчас, иначе `PromoExpiredError`; (3) лимит не исчерпан, иначе `PromoConditionsError`. Срок действия — полуоткрытый интервал `[starts_at, expires_at)`: `starts_at` включительно, `expires_at` исключительно, `None` — без ограничения. Код, срок которого ещё не наступил, SHALL давать `PromoExpiredError` (отдельного исключения нет). Текущее время SHALL браться только из `Clock`, переданного реестру. Лимит исчерпан, когда `uses(code) >= max_uses`.

#### Scenario: Граница начала
- **WHEN** текущее время равно `starts_at`
- **THEN** `resolve` возвращает код

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Граница окончания
- **WHEN** текущее время равно `expires_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Просрочен и исчерпан одновременно
- **WHEN** код и просрочен, и исчерпал лимит
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Лимит исчерпан
- **WHEN** `max_uses=1` и заказ с этим кодом уже оформлен
- **THEN** `resolve` выбрасывает `PromoConditionsError`

#### Scenario: Без лимита
- **WHEN** `max_uses is None`
- **THEN** `resolve` не ограничивает число использований

### Requirement: Учёт использований
Использованием SHALL считаться только успешно оформленный заказ с этим кодом. `resolve`, `quote`, `calculate_total` и неудачные попытки оформления SHALL NOT менять счётчик. Отмена заказа с промокодом (`OrderService.cancel`) SHALL уменьшать счётчик этого кода ровно на один, но не ниже нуля; после этого освободившееся использование снова доступно для `resolve` и `place_order`. Отмена заказа без промокода счётчик не меняет.

#### Scenario: Счётчик не меняется при расчёте
- **WHEN** выполняются `resolve`, `quote` с кодом или неудачный `place_order`
- **THEN** `uses(code)` остаётся прежним

#### Scenario: Успешный заказ
- **WHEN** `place_order` с кодом завершился успешно
- **THEN** `uses(code)` увеличился ровно на 1

#### Scenario: Отмена возвращает использование
- **WHEN** заказ с кодом оформлен (`uses == 1`) и затем отменён
- **THEN** `uses(code) == 0`

#### Scenario: Переоформление после отмены при лимите
- **WHEN** `max_uses=1`, заказ с кодом оформлен и отменён
- **THEN** новый `place_order` с этим кодом проходит успешно

#### Scenario: Отмена заказа без кода
- **WHEN** отменён заказ без промокода
- **THEN** счётчики кодов не меняются
