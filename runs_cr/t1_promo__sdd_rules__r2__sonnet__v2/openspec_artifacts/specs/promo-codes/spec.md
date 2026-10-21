# promo-codes Specification

## Purpose
Описывает промокод как доменный объект и реестр промокодов: регистрация, нормализация вводимого кода, проверка существования, срока действия и лимита, счётчик использований.

## Requirements

### Requirement: Инварианты PromoCode
`PromoCode` (`shop/promo.py`) SHALL быть `@dataclass(frozen=True)` с полями `code`, `kind: DiscountKind`, `value: Decimal`, `min_order_amount: Decimal = Decimal("0.00")`, `starts_at: datetime | None = None`, `expires_at: datetime | None = None`, `max_uses: int | None = None`, `excluded_categories: frozenset[Category] = frozenset()`. `DiscountKind` SHALL быть `StrEnum` со значениями `PERCENT` и `FIXED`. Код SHALL нормализоваться при создании (обрезка пробелов по краям, верхний регистр). Нарушение любого инварианта MUST приводить к `ValidationError`: пустой (после нормализации) код; `kind` не `DiscountKind`; `value` не `Decimal`; для `PERCENT` значение вне `(0, 100]`; для `FIXED` значение `<= 0` или более двух знаков после запятой; `min_order_amount` не `Decimal`, отрицательная или с более чем двумя знаками; naive `datetime` в `starts_at`/`expires_at`; `starts_at` не раньше `expires_at` (если заданы оба); `max_uses` не `int` (в том числе `bool`) или `< 1`; элементы `excluded_categories` не `Category`.

#### Scenario: Код нормализуется при создании
- **WHEN** создаётся `PromoCode(code="  summer10 ", kind=DiscountKind.PERCENT, value=Decimal("10"))`
- **THEN** `promo.code == "SUMMER10"`

#### Scenario: Некорректные значения отвергаются
- **WHEN** создаётся промокод с пустым кодом `"   "`, либо `PERCENT` со значением `0` или `100.01`, либо `FIXED` со значением `0` или `10.001`, либо `max_uses=0`
- **THEN** выбрасывается `ValidationError`

#### Scenario: Граничные допустимые значения
- **WHEN** создаётся `PERCENT` со значением `100` или `0.5`, либо `FIXED` со значением `0.01`, либо `max_uses=1`
- **THEN** объект создаётся без ошибки

#### Scenario: Некорректный интервал действия
- **WHEN** `starts_at == expires_at`, или `starts_at > expires_at`, или любая из границ naive
- **THEN** выбрасывается `ValidationError`

### Requirement: Регистрация кодов в PromoRegistry
`PromoRegistry(clock: Clock)` SHALL хранить промокоды по нормализованному коду. `add(promo)` MUST регистрировать код; повторное добавление кода, совпадающего после нормализации, MUST приводить к `ValidationError`. Новый код стартует со счётчиком использований `0`.

#### Scenario: Дубликат отвергается
- **WHEN** в реестр добавлен `"SUMMER10"`, а затем промокод с кодом `" summer10"`
- **THEN** второй `add` выбрасывает `ValidationError`, первый код остаётся без изменений

### Requirement: Разрешение кода resolve
`PromoRegistry.resolve(code: str) -> PromoCode` SHALL нормализовать вводимый код (обрезка пробелов, верхний регистр) и возвращать зарегистрированный `PromoCode`, если код существует, действует в текущий момент и лимит не исчерпан. Время MUST браться только из `Clock`, переданного в конструктор реестра. Проверки выполняются строго по порядку, первая сработавшая определяет исключение: (1) код не найден — `UnknownPromoCodeError`; (2) текущий момент вне полуоткрытого интервала `[starts_at, expires_at)` (акция ещё не началась или уже закончилась; граница `None` — без ограничения) — `PromoExpiredError`; (3) `max_uses` задан и `uses(code) >= max_uses` — `PromoConditionsError`. `resolve` MUST NOT менять счётчик. Пустая строка и строка из пробелов MUST давать `UnknownPromoCodeError`. Нестроковый аргумент MUST давать `ValidationError`.

#### Scenario: Поиск без учёта регистра и пробелов
- **WHEN** зарегистрирован `SUMMER10`, вызывается `resolve("  summer10 ")`
- **THEN** возвращается этот `PromoCode`

#### Scenario: Неизвестный и пустой код
- **WHEN** вызывается `resolve("NOPE")`, `resolve("")` или `resolve("   ")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Начало срока включительно
- **WHEN** текущее время равно `starts_at`
- **THEN** `resolve` успешен

#### Scenario: Конец срока исключительно
- **WHEN** текущее время равно `expires_at`
- **THEN** выбрасывается `PromoExpiredError`

#### Scenario: Акция ещё не началась
- **WHEN** текущее время раньше `starts_at`
- **THEN** выбрасывается `PromoExpiredError` (отдельного исключения для «ещё не началась» нет)

#### Scenario: Порядок проверок
- **WHEN** срок кода истёк и одновременно исчерпан лимит
- **THEN** выбрасывается `PromoExpiredError`, а не `PromoConditionsError`

#### Scenario: Исчерпанный лимит
- **WHEN** `max_uses=2` и `uses(code) == 2`
- **THEN** `resolve` выбрасывает `PromoConditionsError`; при `uses(code) == 1` возвращает промокод

#### Scenario: Время из внедрённых часов
- **WHEN** `FixedClock` реестра переведён за `expires_at`
- **THEN** тот же `resolve` начинает выбрасывать `PromoExpiredError`

### Requirement: Счётчик использований
`PromoRegistry.uses(code: str) -> int` SHALL возвращать число использований кода (код нормализуется так же, как в `resolve`). Для незарегистрированного кода `uses` MUST выбрасывать `UnknownPromoCodeError`. Счётчик MUST увеличиваться только при успешном оформлении заказа и уменьшаться на один при отмене такого заказа, но никогда не опускаться ниже нуля; изменение счётчика не зависит от срока действия кода. Регистрация использования и его возврат выполняются сервисом заказов через дополнительные методы реестра, не входящие в API тикета.

#### Scenario: Новый код не использован
- **WHEN** код только что добавлен
- **THEN** `uses(code) == 0`

#### Scenario: Неизвестный код в uses
- **WHEN** вызывается `uses("NOPE")`
- **THEN** выбрасывается `UnknownPromoCodeError`

### Requirement: Иерархия ошибок промокодов
`shop/errors.py` SHALL содержать `PromoError(ShopError)` и три независимых наследника `PromoError`: `UnknownPromoCodeError` (такого кода нет), `PromoExpiredError` (вне срока действия, включая «ещё не началась»), `PromoConditionsError` (лимит исчерпан или заказ не подходит под условия). Три наследника MUST NOT наследоваться друг от друга.

#### Scenario: Независимость исключений
- **WHEN** проверяется `issubclass(PromoExpiredError, UnknownPromoCodeError)` и любая другая пара из трёх
- **THEN** результат `False`; каждый из трёх при этом является подклассом `PromoError` и `ShopError`
