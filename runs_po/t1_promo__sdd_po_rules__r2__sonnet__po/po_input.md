### design.md

## Context

См. proposal.md (Why) и specs. Сейчас `calculate_total` считает налог построчно от суммы строки, `OrderService.quote/place_order` принимают только корзину, `OrderStore` в памяти. Соглашения README: `Decimal` и `quantize_money` (`ROUND_HALF_UP`), ошибки только от `ShopError`, время только через `Clock`, frozen-dataclass с инвариантами в `__post_init__`, человеческие коды нормализуются через `normalize_key`, интервалы полуоткрытые, модульные логгеры, только stdlib. Публичный API из тикета не меняется.

## Goals / Non-Goals

**Goals:**
- Скидка по промокоду с точной построчной раскладкой (сумма по строкам == общая скидка) и налогом с суммы после скидки.
- Старые вызовы дают те же суммы (новые поля и параметры только с умолчаниями / keyword-only).

**Non-Goals:**
- CLI и отчёты (`cli.py`, `reports.py`), персистентность реестра, потокобезопасность, возврат использования при отмене заказа.

## Decisions

**Модули и зависимости.** `shop/promo.py` импортирует `catalog` (`Category`, `normalize_key`), `clock`, `errors`, `money`. `pricing.py` импортирует `PromoCode`, `DiscountKind` из `promo`, обратного импорта нет (циклов нет). `orders.py` импортирует `PromoRegistry`.

**Нормализация.** `PromoCode.__post_init__` приводит `code` через `normalize_key` (через `object.__setattr__`, как `Product.sku`); пустой результат — `ValidationError`. `PromoRegistry` использует тот же `normalize_key` для `add`, `resolve`, `uses`. `resolve("")` — просто неизвестный код (`UnknownPromoCodeError`), как велел тимлид. «Пустой код — нет кода» обрабатывает только `OrderService` (`None` или `strip() == ""`), нестроковый ввод даёт `ValidationError` из `normalize_key`.

**Валидация `PromoCode`.** Проверки типов и диапазонов по spec; `value` для `FIXED` и `min_order_amount` проверяются через `to_money(x) == x`, как цена в `Product`. `PERCENT` допускает дробные значения (например `12.5`). `excluded_categories` приводится к `frozenset` и проверяется на `Category`. Интервал: `starts_at >= expires_at` — `ValidationError` (README).

**Реестр и порядок проверок.** `resolve`: найти код → `starts_at <= now < expires_at` (иначе `PromoExpiredError`, включая «ещё не началось», по решению маркетинга) → `uses < max_uses` (иначе `PromoConditionsError`). Условия заказа проверяет `calculate_total`. Время только `self._clock.now()`. Счётчики — `dict[str, int]`. Для записи использования в реестре — внутренний метод `_record_use(code)`, не входящий в публичный API тикета; его вызывает только `OrderService`.

**Расчёт скидки (`pricing.py`).** Чистая внутренняя функция: 
1. участвующие строки = все, кроме `Category.GIFT_CARD` и `promo.excluded_categories`; 
2. `base` = сумма их `amount`; если участвующих нет или `base < min_order_amount` → `PromoConditionsError`; 
3. `PERCENT`: `quantize_money(base * value / 100)`; `FIXED`: `min(to_money(value), base)`; 
4. раскладка: для каждой участвующей строки точная доля `discount * amount / base`, округление вниз до копейки, остаток копеек (`discount - сумма долей`) раздаётся по одной копейке строкам по убыванию дробного остатка, при равенстве — по порядку корзины. Работает в целых копейках (`int`) во избежание ошибок округления. Доля строки не превышает её суммы, т.к. `discount <= base`; 
5. налог строки: `tax.tax_for(category, amount - discount)`; 
6. доставка: `shipping.cost_for(subtotal_до_скидки, ...)` без изменений; `total = subtotal - discount + shipping + tax_total`.
Без промокода путь идентичен прежнему, `discount = ZERO` везде.

**Поля dataclass.** `LineTotal.discount` и `OrderTotal.discount` добавляются последними с умолчанием `ZERO`, чтобы существующие конструкции и позиционные вызовы не ломались. `Order.promo_code: str | None = None` — последним полем.

**`OrderService`.** `promos` — keyword-параметр `__init__` после существующих. Общий приватный шаг: нормализовать `promo_code` (пусто → `None`), иначе `registry.resolve` (если реестра нет — `UnknownPromoCodeError`), затем `calculate_total(..., promo=promo)`. `quote` использует этот шаг; `place_order` — тот же шаг, затем создаёт заказ, `store.add`, и только после этого `registry._record_use`. Все проверки идут до изменения состояния, поэтому неудачная попытка не расходует лимит и не потребляет `next_id`. `Order.promo_code` = `promo.code` или `None`.

**Допущения по неоднозначностям тикета** (приняты без вопросов к пользователю):
- `min_order_amount` сравнивается с суммой *участвующих* строк до скидки, `>=`. Альтернатива (весь `subtotal`) позволила бы открывать скидку сертификатами, что противоречит README («на сертификат не распространяются скидки и акции»).
- Нет участвующих строк → `PromoConditionsError` (иначе нулевая скидка «успешно» расходовала бы лимит).
- Порог бесплатной доставки по сумме до скидки: «на доставку скидка не распространяется».
- Отмена заказа не возвращает использование (тикет такого не требует).
- `uses()` неизвестного кода → `UnknownPromoCodeError`.
- Проценты округляются один раз от суммы участвующих строк (не по строкам), согласно тикету.

## Risks / Trade-offs

- [Реестр не потокобезопасен; гонка двух `place_order` может превысить `max_uses`] → хранилище и так in-memory и однопоточное; блокировки вне рамок, зафиксировано как ограничение.
- [Часы реестра и сервиса могут различаться] → в проде оба `SystemClock`; в тестах один `FixedClock`.
- [`_record_use` — внутренний метод между модулями пакета] → не расширяет публичный API тикета; альтернатива (публичный `register_use`) отвергнута, чтобы не менять заданный API.
- [Отчёты считают выручку по `total.total` и учтут скидку автоматически, но без отдельной строки скидки] → ожидаемо, отдельный тикет.

## Migration Plan

Изменения аддитивные; миграции данных нет. Откат — revert коммитов.


### proposal.md

## Why

Маркетинг запускает летнюю кампанию с промокодами. Сейчас скидки вручную делает поддержка, и суммы расходятся с чеками. Нужны промокоды, которые передаются при расчёте и оформлении заказа, а скидка честно отражается в итогах и построчно (бухгалтерия считает налог по строкам).

## What Changes

- Новый модуль `shop/promo.py`: `DiscountKind` (`PERCENT`, `FIXED`), `PromoCode` (frozen dataclass с полями `code`, `kind`, `value`, `min_order_amount`, `starts_at`, `expires_at`, `max_uses`, `excluded_categories`) и `PromoRegistry(clock)` с методами `add`, `resolve`, `uses`.
- `shop/errors.py`: `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`.
- `shop/pricing.py`: `calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None)`; новые поля `LineTotal.discount` и `OrderTotal.discount` (`Decimal("0.00")`, если скидки нет); `total = subtotal - discount + shipping + tax`. Скидка раскладывается по строкам, налог строки считается с суммы после скидки, доставка не скидывается.
- `shop/orders.py`: `OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code: str | None = None)`, `place_order(cart, promo_code: str | None = None)`, `Order.promo_code: str | None`. Счётчик использований растёт только при успешном `place_order`.
- Обратная совместимость: вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)` дают прежние суммы. **Не BREAKING.**
- Не меняются: `shop/cli.py`, `shop/reports.py`, существующие тесты. Новые зависимости не добавляются.
- README: обновить раздел «Правила расчёта» (формула итога, правила скидок).

## Capabilities

### New Capabilities
- `promo-codes`: модель промокода, его валидация, реестр кодов (нормализация, срок действия, лимит использований, учёт использований), иерархия ошибок промокодов.
- `order-discounts`: применение промокода при расчёте итогов (`calculate_total`) и при `quote`/`place_order`: участвующие товары, процент/фикс, построчная раскладка, налог, доставка, порядок проверок, пустой код.

### Modified Capabilities

(нет: в `openspec/specs/` пока нет спецификаций)

## Impact

- Код: `shop/promo.py` (новый), `shop/errors.py`, `shop/pricing.py`, `shop/orders.py`; новые тесты в отдельных файлах; README.
- Публичный API расширяется только заданными в тикете именами; новые поля dataclass-ов имеют значения по умолчанию.
- `shop/reports.py` и `shop/cli.py` не меняются; отчёты, считающие выручку по `total.total`, автоматически учитывают скидку, отдельной строки скидки в CLI/отчётах пока нет (отдельный тикет).
- Зависимости: только стандартная библиотека.

## Assumptions

Неоднозначности тикета, решённые автономно (подробности и обоснования в design.md):

- Подарочные сертификаты никогда не участвуют в скидке и не учитываются в минимальной сумме заказа (README).
- `min_order_amount` сравнивается с суммой участвующих строк до скидки, нестрого (`>=`).
- Если участвующих строк нет, заказ не подходит: `PromoConditionsError`.
- Порог бесплатной доставки считается по сумме товаров до скидки (доставка скидкой не затрагивается).
- Отмена заказа не уменьшает счётчик использований.
- `uses()` для неизвестного кода — `UnknownPromoCodeError`.


### specs/order-discounts/spec.md

## Purpose

Определяет, как промокод влияет на итоги заказа: расчёт скидки, построчную раскладку, налог и доставку, а также работу `quote` и `place_order` с кодом.

## ADDED Requirements

### Requirement: Подпись calculate_total и поля скидки
`calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None) -> OrderTotal` SHALL принимать промокод только как keyword-аргумент. `LineTotal.discount` и `OrderTotal.discount` SHALL быть `Decimal` и равняться `Decimal("0.00")`, когда скидки нет. `OrderTotal.total` SHALL равняться `subtotal - discount + shipping + tax`; `subtotal` и `LineTotal.amount` остаются суммами до скидки. `calculate_total` проверяет только условия заказа; срок и лимит проверяет реестр.

#### Scenario: Обратная совместимость
- **WHEN** вызывается `calculate_total(cart)` или `calculate_total(cart, shipping, tax)` без `promo`
- **THEN** суммы те же, что и раньше, а `discount` равен `Decimal("0.00")` у заказа и у каждой строки

#### Scenario: Формула итога
- **WHEN** применена скидка
- **THEN** `total == subtotal - discount + shipping + tax`

### Requirement: Участвующие товары
Скидка SHALL действовать только на участвующие строки. Строка не участвует, если её категория `Category.GIFT_CARD` (подарочные сертификаты никогда не получают скидок) или входит в `excluded_categories` кода. У неучаствующих строк `discount == Decimal("0.00")`.

#### Scenario: Исключённая категория
- **WHEN** у кода `excluded_categories={Category.BOOKS}`, в корзине книга и футболка
- **THEN** скидка считается только от суммы футболки, у книги `discount == 0.00`

#### Scenario: Подарочный сертификат
- **WHEN** в корзине сертификат и обычный товар, а код не исключает категорий
- **THEN** сертификат не получает скидки и не входит в базу расчёта

### Requirement: Размер скидки
Для `PERCENT` скидка SHALL равняться сумме участвующих строк, умноженной на `value / 100` и округлённой через `quantize_money` (`ROUND_HALF_UP`). Для `FIXED` скидка SHALL равняться `min(value, сумма участвующих строк)`. Все суммы SHALL быть `Decimal` с двумя знаками.

#### Scenario: Округление половины вверх
- **WHEN** участвующие строки дают `10.10`, код на 5 %
- **THEN** скидка равна `0.51` (0.505 округляется вверх)

#### Scenario: Фиксированная скидка больше суммы
- **WHEN** `FIXED` на `5000` при участвующих строках на `1200.00`
- **THEN** скидка равна `1200.00`, налог по этим строкам равен нулю

### Requirement: Построчная раскладка скидки
Общая скидка SHALL раскладываться по участвующим строкам пропорционально суммам строк с точностью до копейки так, чтобы сумма `LineTotal.discount` по строкам в точности равнялась `OrderTotal.discount`. Скидка строки SHALL NOT превышать её сумму и SHALL NOT быть отрицательной. Копейки, оставшиеся после округления вниз, распределяются по наибольшим дробным остаткам; при равенстве остатков — по порядку строк корзины. Результат SHALL быть детерминированным.

#### Scenario: Сумма по строкам равна общей скидке
- **WHEN** скидка `10.00` на три строки по `33.33`
- **THEN** сумма скидок строк равна `10.00`, каждая скидка кратна `0.01`

#### Scenario: Равные остатки
- **WHEN** остатки копеек равны
- **THEN** лишние копейки получают строки, добавленные в корзину раньше

### Requirement: Налог и доставка при скидке
Налог строки SHALL считаться с суммы строки после скидки (`amount - discount`) по ставке категории с округлением в каждой строке отдельно; налог заказа — сумма налогов строк. Стоимость доставки SHALL NOT уменьшаться скидкой, порог бесплатной доставки SHALL определяться по сумме товаров до скидки. Доставка по-прежнему не облагается налогом.

#### Scenario: Налог после скидки
- **WHEN** строка `1000.00` с налогом 20 % получает скидку `100.00`
- **THEN** налог строки равен `180.00`

#### Scenario: Бесплатная доставка сохраняется
- **WHEN** сумма товаров `3000.00`, скидка 10 %
- **THEN** доставка остаётся `0.00`

#### Scenario: Платная доставка не снижается
- **WHEN** сумма товаров `1000.00`, скидка `FIXED 200`
- **THEN** доставка равна `299.00`

### Requirement: Условия заказа
Если в `calculate_total` передан промокод, а заказ не подходит, SHALL выбрасываться `PromoConditionsError`. Заказ не подходит, если сумма участвующих строк до скидки меньше `min_order_amount` (равенство допустимо) либо участвующих строк нет. Пустая корзина по-прежнему даёт `EmptyCartError`.

#### Scenario: Сумма ниже минимума
- **WHEN** `min_order_amount=1000.00`, участвующие строки на `999.99`
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Сумма ровно минимум
- **WHEN** участвующие строки на `1000.00`
- **THEN** скидка применяется

#### Scenario: Нет участвующих товаров
- **WHEN** в корзине только подарочные сертификаты или только исключённые категории
- **THEN** выбрасывается `PromoConditionsError`

### Requirement: quote и place_order с промокодом
`OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code: str | None = None)` и `place_order(cart, promo_code: str | None = None)` SHALL принимать код строкой. `None`, пустая строка и строка из одних пробелов SHALL означать «без промокода» и не быть ошибкой. Непустой код SHALL нормализоваться и разрешаться через реестр (порядок проверок: существование, срок, лимит, затем условия заказа). Без реестра любой непустой код SHALL давать `UnknownPromoCodeError`. `Order.promo_code` SHALL хранить нормализованный код либо `None`. Использование SHALL засчитываться только после успешного сохранения заказа; при любой ошибке заказ не создаётся и счётчик не меняется. `quote` SHALL NOT менять счётчик.

#### Scenario: Пустое поле формы
- **WHEN** `place_order(cart, promo_code="  ")`
- **THEN** заказ оформлен без скидки, `order.promo_code is None`, суммы как у `place_order(cart)`

#### Scenario: Код в другом регистре
- **WHEN** `place_order(cart, promo_code=" summer10 ")`
- **THEN** скидка применена, `order.promo_code == "SUMMER10"`, `uses("SUMMER10") == 1`

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos`, вызывается `quote(cart, "ANY")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Котировка не расходует лимит
- **WHEN** `quote(cart, "SUMMER10")` вызван несколько раз
- **THEN** `uses("SUMMER10")` равен `0`

#### Scenario: Заказ не подходит
- **WHEN** сумма ниже `min_order_amount`
- **THEN** `place_order` выбрасывает `PromoConditionsError`, заказ не сохранён, `uses` не изменился

#### Scenario: Лимит
- **WHEN** `max_uses=1` и первый заказ оформлен
- **THEN** второй `place_order` с тем же кодом выбрасывает `PromoConditionsError`

#### Scenario: Старые вызовы
- **WHEN** вызываются `quote(cart)` и `place_order(cart)`
- **THEN** суммы те же, что и раньше, `order.promo_code is None`, `total.discount == Decimal("0.00")`


### specs/promo-codes/spec.md

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
Использованием SHALL считаться только успешно оформленный заказ с этим кодом. `resolve`, `quote`, `calculate_total` и неудачные попытки оформления SHALL NOT менять счётчик. Отмена заказа счётчик не уменьшает.

#### Scenario: Счётчик не меняется при расчёте
- **WHEN** выполняются `resolve`, `quote` с кодом или неудачный `place_order`
- **THEN** `uses(code)` остаётся прежним

#### Scenario: Успешный заказ
- **WHEN** `place_order` с кодом завершился успешно
- **THEN** `uses(code)` увеличился ровно на 1


### tasks.md

## 1. Ошибки и модель промокода

- [ ] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и независимых наследников `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить тестом `issubclass` (тесты в новом `tests/test_promo.py`)
- [ ] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация кода, все инварианты из spec `promo-codes`); проверить тестами на валидные и невалидные значения (процент 0/100/100.01, фикс с тремя знаками, naive-даты, `starts_at >= expires_at`, `max_uses` 0/True)

## 2. Реестр

- [ ] 2.1 Реализовать `PromoRegistry(clock)`: `add` (дубликат — `ValidationError`), `resolve` (порядок: существование → срок `[starts_at, expires_at)` → лимит), `uses`, внутренний `_record_use`; проверить тестами с `FixedClock`: границы срока, «ещё не началось» = `PromoExpiredError`, `resolve("")` = `UnknownPromoCodeError`, регистр и пробелы, приоритет `PromoExpiredError` над исчерпанным лимитом

## 3. Расчёт итогов

- [ ] 3.1 Добавить `discount` (по умолчанию `ZERO`) в `LineTotal` и `OrderTotal` и параметр `promo` (keyword-only) в `calculate_total`; убедиться, что существующие `tests/test_pricing.py` проходят без изменений
- [ ] 3.2 Реализовать участвующие строки, размер скидки (процент с `ROUND_HALF_UP`, фикс с ограничением суммой), проверку `min_order_amount` и отсутствия участвующих строк; проверить тестами в новом `tests/test_pricing_promo.py` (исключённые категории, `GIFT_CARD`, фикс больше суммы, граница минимума)
- [ ] 3.3 Реализовать точную построчную раскладку (целые копейки, наибольшие остатки, ничьи по порядку корзины), налог с суммы после скидки, доставку без изменений; проверить тестами: сумма `LineTotal.discount` == `OrderTotal.discount` (включая 3 × 33.33), `total = subtotal - discount + shipping + tax`, порог бесплатной доставки по сумме до скидки

## 4. Заказы

- [ ] 4.1 Добавить `promos` в `OrderService.__init__`, `promo_code` в `quote` и `place_order`, `Order.promo_code`; пустой/пробельный код = без кода, нет реестра = `UnknownPromoCodeError`; использование записывается после `store.add`; проверить тестами в новом `tests/test_orders_promo.py` (нормализованный `order.promo_code`, `quote` не меняет `uses`, неудачные `place_order` не меняют `uses` и не сохраняют заказ, лимит `max_uses=1`, старые вызовы дают прежние суммы)

## 5. Документация и финальная проверка

- [ ] 5.1 Обновить README («Правила расчёта»: формула итога со скидкой, правила промокодов) и убедиться, что `shop/cli.py`, `shop/reports.py` и существующие тесты не изменены (`git diff --stat`)
- [ ] 5.2 Запустить `python -m pytest -q` и убедиться, что все старые и новые тесты проходят
- [ ] 5.3 Сверить публичный API реализации с proposal и specs: имена, порядок и вид параметров (`promo` keyword-only, `promo_code: str | None`), поля и значения enum, три независимых наследника `PromoError`; расхождений быть не должно
