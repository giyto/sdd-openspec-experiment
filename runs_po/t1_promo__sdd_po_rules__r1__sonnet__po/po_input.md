### design.md

## Context

Текущий расчёт — чистая функция `calculate_total` в `shop/pricing.py`; `OrderService` вызывает её из `quote` и `place_order`. Соглашения README обязательны: деньги только `Decimal` и `quantize_money` (`ROUND_HALF_UP`), ошибки только от `ShopError`, время только через `Clock`, модели — `frozen` dataclass с проверкой в `__post_init__`, человеческие коды нормализуются через `normalize_key`, интервалы времени полуоткрытые, подарочные сертификаты никогда не получают скидок. Мотивация и допущения — в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:**
- Скидка точно отражается в итогах и построчно; сумма по строкам равна общей скидке.
- Старые вызовы работают без изменений.

**Non-Goals:**
- CLI, отчёты, возврат использования при отмене заказа, потокобезопасность хранилища заказов.

## Decisions

1. **Модули и зависимости.** `shop/promo.py` импортирует `catalog` (`Category`, `normalize_key`), `clock`, `errors`, `money`; `pricing.py` импортирует `promo` (для типа и `DiscountKind`); `orders.py` импортирует оба. Циклов нет.

2. **Нормализация кода** в `PromoCode.__post_init__` через `object.__setattr__(self, "code", normalize_key(self.code))`, как в `Product`. Реестр нормализует вход `add`/`resolve`/`uses` тем же `normalize_key`. Не-строка даёт `ValidationError` из `normalize_key`. Альтернатива (своя нормализация) отвергнута: единое правило проекта.

3. **Дробный процент и копейки.** `PERCENT value` — любой `Decimal` из (0, 100]; скидка = `quantize_money(base * value / 100)`. Для `FIXED` значение должно быть кратно копейке (`to_money(value) == value`), чтобы не терять сумму молча, как это делает `Product.price`. `float` отвергается (`value` должен быть `Decimal`).

4. **Алгоритм расчёта в `calculate_total`:**
   1. Построить строки как раньше; определить участвующие (не `GIFT_CARD`, не в `excluded_categories`).
   2. При `promo`: `base` = сумма участвующих; если участвующих нет или `base < min_order_amount` — `PromoConditionsError`.
   3. Скидка: `PERCENT` → `quantize_money(base * value / 100)`; `FIXED` → `min(value, base)`.
   4. Раскладка методом наибольших остатков в целых копейках: доля = `discount_cents * line_cents / base_cents`; берём пол, остаток копеек отдаём строкам с наибольшей дробной частью, при равенстве — раньше в корзине. Пол ≤ точной доли ≤ суммы строки, а +1 получают только строки с ненулевой дробной частью, поэтому скидка строки никогда не превышает её сумму. Реализовать через целочисленную арифметику (`divmod`), без `Decimal`-округления.
   5. `tax = tax_policy.tax_for(category, amount - discount)`.
   6. Доставка считается как раньше от `subtotal` до скидки; `total = subtotal - discount + shipping + tax`.
   Без `promo` скидки нулевые, путь расчёта сохраняет прежние суммы. Новые поля `discount` в `LineTotal` и `OrderTotal` идут последними с умолчанием `ZERO`, чтобы не ломать позиционное создание.

5. **Распределение ответственности.** `calculate_total` не знает про часы и счётчик: он принимает готовый `PromoCode` и проверяет только условия заказа. Срок и лимит проверяет `PromoRegistry.resolve` в порядке: существование → срок → лимит. Затем условия заказа проверяет `calculate_total` — так порядок «код, срок, лимит, условия» выдерживается.

6. **Реестр.** `PromoRegistry` хранит `dict[str, PromoCode]` и `dict[str, int]` счётчиков, текущее время берёт из `self._clock.now()`. Срок: `starts_at is not None and now < starts_at` или `expires_at is not None and now >= expires_at` → `PromoExpiredError`. Лимит: `max_uses is not None and uses >= max_uses` → `PromoConditionsError`. Дополнительный публичный метод `consume(code) -> None` повторно проверяет лимит и увеличивает счётчик под `threading.Lock` (стандартная библиотека), чтобы два одновременных заказа не превысили лимит. Альтернатива — трогать приватные поля реестра из `OrderService`; отвергнута. `uses` неизвестного кода — `UnknownPromoCodeError`.

7. **Поток `OrderService`.** Вспомогательная функция разбора: `None`/пустая/пробельная строка → `None`; иначе `promos.resolve(code)` (при `promos is None` — `UnknownPromoCodeError`). `quote` вызывает `calculate_total(..., promo=promo)`. `place_order`: разобрать и рассчитать, затем `consume`, затем `next_id`, создать и сохранить заказ с `promo_code=promo.code`. Порядок «`consume` перед `store.add`» гарантирует, что при исчерпанном лимите заказ не сохраняется; расход происходит только когда все остальные шаги, способные упасть, пройдены. `Order.promo_code` добавляется последним полем с умолчанием `None`.

8. **Ошибки.** `PromoError(ShopError)` и три прямых наследника без общих подклассов между собой; не `ValidationError`, поскольку это не ошибки формата ввода.

## Risks / Trade-offs

- [Порог бесплатной доставки по сумме до скидки может не совпасть с ожиданием маркетинга] → зафиксировано как допущение в proposal; изменение локально в одной строке расчёта.
- [`min_order_amount` считается по участвующим строкам, а не по всему заказу] → допущение в proposal; легко заменить.
- [Расход лимита при отмене заказа не возвращается] → вне рамок тикета.
- [Дополнительный метод `consume` расширяет API реестра] → только добавление, заданный API не меняется.
- [Блокировка защищает только реестр, а не `OrderStore`] → приемлемо, хранилище в памяти и в этом тикете не меняется.


### proposal.md

## Why

Летняя кампания маркетинга (SHOP-412) идёт с промокодами, а скидки сейчас вручную делает поддержка, из-за чего суммы расходятся с чеками. Нужна автоматическая скидка, которая попадает в итоги и построчно в чек: бухгалтерия считает налог по строкам.

## What Changes

- Новый модуль `shop/promo.py`: `DiscountKind` (`PERCENT`, `FIXED`), `PromoCode` (frozen dataclass, поля `code`, `kind`, `value`, `min_order_amount`, `starts_at`, `expires_at`, `max_uses`, `excluded_categories`) и `PromoRegistry(clock)` с методами `add`, `resolve`, `uses`.
- `shop/errors.py`: `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`.
- `shop/pricing.py`: `calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None)`; новые поля `LineTotal.discount` и `OrderTotal.discount`; `total = subtotal - discount + shipping + tax`. Скидка раскладывается по строкам с точной суммой, налог считается с суммы строки после скидки, доставка не скидывается. Функция проверяет только условия заказа (срок и лимит проверяет реестр).
- `shop/orders.py`: `OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code=None)`, `place_order(cart, promo_code=None)`, `Order.promo_code: str | None`. Использование кода засчитывается только при успешно оформленном заказе.
- Не ломаем: старые вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)` дают прежние суммы. `shop/cli.py`, `shop/reports.py` и существующие тесты не меняются; новые тесты — в отдельных файлах.

Допущения (задача не уточняет, решение принято автономно):

- Подарочные сертификаты не участвуют никогда (README), независимо от `excluded_categories`.
- Порог бесплатной доставки считается по `subtotal` до скидки: скидка не влияет на доставку вообще.
- `min_order_amount` сравнивается с суммой участвующих строк до скидки (включительно: сумма >= минимума).
- Если участвующих строк нет, код не подходит заказу: `PromoConditionsError`.
- Отмена заказа счётчик использований не уменьшает (тикет считает использованием оформленный заказ).
- Для реестра добавляется один дополнительный метод `consume(code)` для учёта использования при оформлении заказа; остальной заданный API не меняется.

## Capabilities

### New Capabilities
- `promo-codes`: описание промокода, его валидация и нормализация, реестр с проверкой существования, срока и лимита, учёт использований, иерархия ошибок.
- `order-discounts`: применение промокода при расчёте итогов, построчная раскладка скидки, налог после скидки, интеграция с `quote`/`place_order` и сохранение кода в заказе.

### Modified Capabilities

## Impact

- Код: `shop/promo.py` (новый), `shop/errors.py`, `shop/pricing.py`, `shop/orders.py`; новые тесты в отдельных файлах.
- Публичный API: только расширение с необязательными параметрами и полями; обратная совместимость сохраняется.
- Зависимости: новых нет (только стандартная библиотека). `cli.py`, `reports.py` не затрагиваются.


### specs/order-discounts/spec.md

## Purpose

Определяет, как промокод влияет на итоги заказа и чек: какие строки участвуют, как считается и раскладывается скидка, как меняется налог и как код передаётся при расчёте и оформлении заказа.

## ADDED Requirements

### Requirement: Расчёт итогов со скидкой
`calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None) -> OrderTotal` SHALL принимать `promo` только как keyword-параметр. `LineTotal.discount` и `OrderTotal.discount` SHALL быть `Decimal` с двумя знаками, `Decimal("0.00")` при отсутствии скидки. Должно выполняться `OrderTotal.total = subtotal - discount + shipping + tax`, где `subtotal` — сумма строк до скидки, а `OrderTotal.discount` равен сумме `LineTotal.discount` по строкам. Вызовы без `promo` SHALL давать те же суммы, что и до изменения.

#### Scenario: Обратная совместимость
- **WHEN** вызывается `calculate_total(cart)` или `calculate_total(cart, shipping, tax)`
- **THEN** все суммы прежние, а `discount` равен `Decimal("0.00")` в итогах и во всех строках

### Requirement: Участвующие товары
Скидка SHALL действовать только на участвующие строки. Строка не участвует, если её категория `Category.GIFT_CARD` или входит в `excluded_categories` кода. Для неучаствующих строк `LineTotal.discount` SHALL быть `Decimal("0.00")`.

#### Scenario: Сертификат и исключённая категория
- **WHEN** в корзине книги, одежда и подарочный сертификат, а у кода `excluded_categories={Category.BOOKS}`
- **THEN** скидку получает только одежда

### Requirement: Размер скидки
Для `PERCENT` скидка SHALL равняться сумме участвующих строк × `value` / 100, округлённой через `ROUND_HALF_UP` до копеек. Для `FIXED` скидка SHALL равняться `min(value, сумма участвующих строк)`. Доставка не входит в базу и не уменьшается; решение о бесплатной доставке SHALL приниматься по `subtotal` до скидки.

#### Scenario: Процент с округлением
- **WHEN** сумма участвующих строк `100.05` и код `PERCENT 10`
- **THEN** скидка `10.01` (10.005 округляется вверх)

#### Scenario: Фиксированная скидка больше базы
- **WHEN** сумма участвующих строк `500.00` и код `FIXED 800`
- **THEN** скидка `500.00`

#### Scenario: Доставка не меняется
- **WHEN** скидка опускает сумму товаров ниже порога бесплатной доставки, но `subtotal` порог достигает
- **THEN** доставка остаётся бесплатной и скидка на доставку не применяется

### Requirement: Раскладка скидки по строкам
Общая скидка SHALL раскладываться по участвующим строкам пропорционально их сумме, в копейках, так что сумма `LineTotal.discount` в точности равна общей скидке, а скидка строки не отрицательна и не превышает её сумму. Остаток копеек SHALL распределяться по наибольшей дробной части доли, при равенстве — по порядку строк в корзине. Результат SHALL быть детерминированным.

#### Scenario: Сумма по строкам равна общей скидке
- **WHEN** фиксированная скидка `10.00` на три участвующие строки по `10.00`
- **THEN** скидки строк `3.34`, `3.33`, `3.33` в порядке корзины, сумма `10.00`

### Requirement: Налог после скидки
Налог строки SHALL считаться с `amount - discount` по ставке категории строки с округлением в строке; налог заказа — сумма налогов строк.

#### Scenario: Налог со скидкой
- **WHEN** строка электроники `1000.00` получает скидку `100.00`
- **THEN** налог строки `180.00`

### Requirement: Условия заказа в расчёте
`calculate_total` SHALL проверять только условия заказа и не проверять срок и лимит. Если сумма участвующих строк меньше `min_order_amount` либо участвующих строк нет, SHALL выбрасываться `PromoConditionsError`. Равенство минимальной сумме SHALL допускаться.

#### Scenario: Ниже минимальной суммы
- **WHEN** `min_order_amount=1000.00`, сумма участвующих строк `999.99`
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Только сертификаты
- **WHEN** корзина состоит из подарочных сертификатов и передан любой код
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Просроченный код передан напрямую
- **WHEN** в `calculate_total` передан `PromoCode` с истёкшим сроком
- **THEN** расчёт выполняется, срок не проверяется

### Requirement: Промокод в OrderService
`OrderService(..., promos: PromoRegistry | None = None)`. `quote(cart, promo_code: str | None = None)` и `place_order(cart, promo_code: str | None = None)` SHALL трактовать `None`, пустую и пробельную строку как «без промокода» (результат как без кода, без ошибок, в том числе без реестра). Иначе код SHALL разрешаться через реестр, а проверки идти в порядке: существование, срок, лимит, условия заказа. Без реестра любой непустой код SHALL давать `UnknownPromoCodeError`. `Order.promo_code: str | None` SHALL содержать нормализованный код либо `None`; `Order.total` SHALL содержать скидки. `quote` SHALL не менять счётчик и не сохранять заказ.

#### Scenario: Пустое поле формы
- **WHEN** `quote(cart, "  ")` или `place_order(cart, "")`
- **THEN** результат как без промокода, `Order.promo_code is None`

#### Scenario: Код в другом регистре
- **WHEN** `place_order(cart, " summer10 ")`
- **THEN** скидка применена, `Order.promo_code == "SUMMER10"`, `uses("SUMMER10") == 1`

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos` и вызван `quote(cart, "SUMMER10")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Неудачное оформление не расходует лимит
- **WHEN** `place_order` с кодом падает с `PromoConditionsError` или `EmptyCartError`
- **THEN** заказ не сохранён и `uses` не изменился

#### Scenario: Последнее использование
- **WHEN** `max_uses=1` и первый `place_order` с кодом успешен
- **THEN** второй `place_order` с кодом выбрасывает `PromoConditionsError`


### specs/promo-codes/spec.md

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
`PromoRegistry.uses(code: str) -> int` SHALL возвращать число успешно оформленных заказов с этим кодом (код нормализуется; для зарегистрированного кода без использований — `0`; для неизвестного — `UnknownPromoCodeError`). Использование SHALL засчитываться только при успешном оформлении заказа через `place_order`. `resolve`, `quote`, `calculate_total` и неудачные попытки оформления SHALL не менять счётчик. Учёт использования SHALL повторно проверять лимит и при исчерпании выбрасывать `PromoConditionsError`.

#### Scenario: Расчёт не расходует лимит
- **WHEN** вызываются `resolve`, `quote` и `calculate_total` с кодом
- **THEN** `uses(code) == 0`

### Requirement: Иерархия ошибок промокодов
`PromoError` SHALL наследовать `ShopError`. `UnknownPromoCodeError`, `PromoExpiredError` и `PromoConditionsError` SHALL быть независимыми прямыми наследниками `PromoError`: ни один не является подклассом другого и ни один не является `ValidationError`.

#### Scenario: Независимость исключений
- **WHEN** проверяется иерархия
- **THEN** каждый из трёх классов является подклассом `PromoError` и `ShopError` и не является подклассом двух других


### tasks.md

## 1. Ошибки и модель промокода

- [ ] 1.1 Добавить в `shop/errors.py` `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`; проверить тестом `tests/test_promo_errors.py`, что они не являются подклассами друг друга и `ValidationError`
- [ ] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация кода, все инварианты в `__post_init__`); проверить тестами `tests/test_promo.py` сценарии валидации из спецификации `promo-codes`

## 2. Реестр

- [ ] 2.1 Реализовать `PromoRegistry(clock)`: `add` (дубликат — `ValidationError`), `resolve` с порядком «существует → срок `[starts_at, expires_at)` → лимит», `uses`, `consume` с повторной проверкой лимита; проверить тестами с `FixedClock` в `tests/test_promo_registry.py`: регистр и пробелы, `resolve("")`, границы срока, не начавшаяся акция, порядок проверок, `resolve` не расходует лимит

## 3. Расчёт со скидкой

- [ ] 3.1 Добавить `LineTotal.discount` и `OrderTotal.discount` (последние поля, по умолчанию `ZERO`) и параметр `promo` (keyword-only) в `calculate_total`; убедиться, что существующие `tests/test_pricing.py` проходят без изменений
- [ ] 3.2 Реализовать участвующие строки, размер скидки (процент с `ROUND_HALF_UP`, фиксированная не больше базы), проверку `min_order_amount` и отсутствия участвующих строк; проверить в `tests/test_pricing_promo.py` включая сертификаты, исключённые категории и равенство минимуму
- [ ] 3.3 Реализовать раскладку по строкам методом наибольших остатков и налог с суммы после скидки; проверить в `tests/test_pricing_promo.py`: сумма по строкам равна общей скидке (в том числе `10.00` на три строки по `10.00`), скидка строки не больше её суммы, `total = subtotal - discount + shipping + tax`, доставка не меняется

## 4. Оформление заказа

- [ ] 4.1 Добавить `OrderService(..., promos=None)`, `quote(cart, promo_code=None)`, `place_order(cart, promo_code=None)` и `Order.promo_code`; пустой и пробельный код равен отсутствию кода, без реестра непустой код — `UnknownPromoCodeError`; использование засчитывается только после успешных проверок; проверить в `tests/test_orders_promo.py`: нормализованный код в заказе, `quote` и неудачные попытки не меняют `uses`, лимит `max_uses=1`, порядок проверок ошибок
- [ ] 4.2 Проверить обратную совместимость: `python -m pytest -q` проходит полностью, `shop/cli.py`, `shop/reports.py` и существующие тесты не изменены (`git diff --stat`)

## 5. Сверка API

- [ ] 5.1 Сверить публичный API реализации с proposal и specs (имена модулей, классов, полей, сигнатуры, порядок и вид параметров, значения `DiscountKind`, keyword-only `promo`, иерархия ошибок) и проверить скриптом через `inspect.signature` и `dataclasses.fields`; расхождения исправить
