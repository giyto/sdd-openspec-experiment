### design.md

## Context

Модули `pricing.py` (чистая функция `calculate_total`) и `orders.py` (`OrderService`) см. в README. Соглашения: `Decimal` и `quantize_money` с `ROUND_HALF_UP`, frozen-датаклассы с инвариантами в `__post_init__`, `normalize_key` для вводимых человеком кодов, `Clock` вместо `datetime.now()`, полуоткрытые интервалы, ошибки только от `ShopError`. Мотивация — в proposal.md, требования — в specs.

## Goals / Non-Goals

**Goals:**
- Публичный API ровно как в тикете, без переименований; расширение обратно совместимо.
- Одна точка расчёта скидки в `calculate_total`; реестр отвечает за срок и лимит.

**Non-Goals:**
- CLI, отчёты, потокобезопасность, персистентность счётчиков, возврат использования при отмене заказа.

## Decisions

1. **Разделение ответственности.** `PromoRegistry.resolve` проверяет существование → срок → лимит; `calculate_total` — только `min_order_amount` и наличие участвующих строк. `OrderService` склеивает: `resolve` → `calculate_total` → сохранение заказа → фиксация использования. Альтернатива (всё в сервисе) отвергнута: `calculate_total` в тикете сам принимает `promo`.
2. **Фиксация использования.** В реестр добавляется служебный метод `redeem(code)`, вызываемый `place_order` только после успешного `store.add`; он повторно проверяет лимит и увеличивает счётчик. Это единственное дополнение сверх API тикета. Альтернатива «увеличивать в `resolve`» нарушает требование, что `quote` счётчик не трогает.
3. **Раскладка скидки — метод наибольших остатков.** Доля строки = скидка × сумма_строки / сумма_участвующих; пол до копеек, остаток копеек раздаётся по убыванию дробной части, при равенстве — более ранней строке корзины. Доля не превышает сумму строки, так как скидка ≤ суммы участвующих; арифметика только `Decimal`. Альтернатива «остаток в последнюю строку» может превысить сумму маленькой строки.
4. **Участие.** Не участвует `GIFT_CARD` всегда + `excluded_categories`. Нет участвующих строк → `PromoConditionsError`.
5. **`min_order_amount`** сравнивается с суммой участвующих строк до скидки, равенство проходит.
6. **Доставка** считается как раньше от суммы до скидки; `subtotal` остаётся до скидки, `total = subtotal - discount + shipping + tax`.
7. **Ввод.** `PromoCode.code` и ключ реестра нормализуются через `normalize_key`. В сервисе: `None` или пустая/пробельная строка → кода нет; иначе `registry.resolve`. `resolve("")` остаётся `UnknownPromoCodeError`. Нестрока → `ValidationError` (из `normalize_key`).
8. **Поля с умолчаниями.** `LineTotal.discount` и `OrderTotal.discount` добавляются в конец с умолчанием `ZERO`, `Order.promo_code=None` — последним полем, чтобы не сломать позиционные вызовы.
9. **Валидация `PromoCode`:** `FIXED.value` не более двух знаков после запятой (иначе `ValidationError`, а не тихое округление); `max_uses` — `int`, не `bool`; `starts_at < expires_at`, оба aware.
10. **Ошибки:** `PromoError(ShopError)` и три независимых наследника; не смешиваем с `ValidationError`.
11. **`uses(unknown)`** — `UnknownPromoCodeError`.

## Risks / Trade-offs

- [Отчёты считают выручку по итогам заказа и могут не учитывать скидку] → `reports.py` вне рамок; вынести в следующий тикет.
- [Не потокобезопасно: гонка за последнее использование] → повторная проверка лимита в `redeem`; полноценная блокировка вне рамок.
- [Допущения 4 и 5 — продуктовые] → зафиксированы в proposal.md, легко изменить.
- [Отмена заказа не возвращает использование] → тикет этого не требует.


### proposal.md

## Why

Скидки по летней кампании сейчас вручную проставляет поддержка, из-за чего суммы расходятся с чеками, а бухгалтерия не получает построчной скидки для расчёта налога. Нужны промокоды, которые передаются при расчёте и оформлении заказа и честно отражаются в итогах и в строках.

## What Changes

- Новый модуль `shop/promo.py`: `DiscountKind` (`PERCENT`, `FIXED`), `PromoCode` (frozen dataclass, поля как в тикете), `PromoRegistry(clock)` с `add`, `resolve`, `uses`.
- `shop/errors.py`: `PromoError(ShopError)` и три независимых наследника `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError`.
- `shop/pricing.py`: `calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None)`; новые поля `LineTotal.discount` и `OrderTotal.discount`; `total = subtotal - discount + shipping + tax`; скидка раскладывается по строкам с точным совпадением суммы, налог считается с суммы строки после скидки.
- `shop/orders.py`: `OrderService(..., promos: PromoRegistry | None = None)`, `quote(cart, promo_code=None)`, `place_order(cart, promo_code=None)`, `Order.promo_code`. Использование кода засчитывается только при успешно оформленном заказе.
- Обратная совместимость: старые вызовы без промокода дают те же суммы. `shop/cli.py`, `shop/reports.py` и существующие тесты не меняются.

## Capabilities

### New Capabilities
- `promo-codes`: описание промокода, его валидация, реестр кодов, проверка существования, срока действия и лимита, учёт использований.
- `order-discounts`: применение промокода при расчёте и оформлении заказа — участвующие строки, размер скидки, раскладка по строкам, налог, доставка, условия заказа, обработка ввода.

### Modified Capabilities

## Impact

- Код: `shop/promo.py` (новый), `shop/errors.py`, `shop/pricing.py`, `shop/orders.py`, `shop/__init__.py` (экспорт), новые файлы тестов.
- Публичный API расширяется только обратно совместимо (новые необязательные параметры и поля со значениями по умолчанию).
- Зависимости: новых нет.

## Допущения

- `min_order_amount` сравнивается с суммой участвующих строк до скидки (подарочные сертификаты и исключённые категории не засчитываются); равенство проходит.
- Если у корзины нет ни одной участвующей строки, код не подходит заказу: `PromoConditionsError`.
- Порог бесплатной доставки считается по сумме товаров до скидки (доставка скидкой не затрагивается).
- Подарочные сертификаты не участвуют в скидке всегда, независимо от `excluded_categories` (README).
- Не начавшаяся акция — тоже `PromoExpiredError` (решение маркетинга в обсуждении).
- Пустой или пробельный `promo_code` в `quote`/`place_order` — «без кода»; `resolve("")` — `UnknownPromoCodeError` (решение тимлида).


### specs/order-discounts/spec.md

## Purpose

Определяет, как промокод влияет на расчёт и оформление заказа: какие строки участвуют, как считается и раскладывается скидка, как она влияет на налог, доставку и итоги.

## ADDED Requirements

### Requirement: Обратная совместимость
Вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`, `place_order(cart)` MUST давать те же суммы, что и раньше; `LineTotal.discount` и `OrderTotal.discount` MUST быть `Decimal("0.00")`, `Order.promo_code` — `None`.

#### Scenario: Без промокода
- **WHEN** считается заказ без промокода
- **THEN** все скидки равны `0.00`, `total = subtotal + shipping + tax`

### Requirement: Участвующие строки
Скидка SHALL действовать только на участвующие строки. Строка не участвует, если её категория входит в `excluded_categories` кода или это `Category.GIFT_CARD` (всегда, независимо от кода).

#### Scenario: Сертификат без скидки
- **WHEN** в корзине книга и подарочный сертификат, применён процентный код
- **THEN** `discount` строки сертификата равен `0.00`

#### Scenario: Исключённая категория
- **WHEN** категория строки входит в `excluded_categories`
- **THEN** строка не получает скидку

### Requirement: Размер скидки
Для `PERCENT` скидка SHALL равняться сумме участвующих строк × `value` / 100, округлённой через `ROUND_HALF_UP` до копеек. Для `FIXED` скидка SHALL равняться `min(value, сумма участвующих строк)`. Скидка MUST NOT превышать сумму участвующих строк.

#### Scenario: Процент с округлением
- **WHEN** сумма участвующих строк `10.05`, код `PERCENT` 10
- **THEN** общая скидка `1.01` (1.005 округляется вверх)

#### Scenario: Фиксированная больше суммы
- **WHEN** сумма участвующих строк `500.00`, код `FIXED` 800
- **THEN** общая скидка `500.00`, сумма товаров после скидки равна нулю

### Requirement: Раскладка по строкам
Общая скидка SHALL раскладываться по участвующим строкам пропорционально их суммам с точностью до копейки; сумма `LineTotal.discount` MUST в точности равняться `OrderTotal.discount`. Скидка строки MUST NOT превышать сумму строки и MUST NOT быть отрицательной. Раскладка MUST быть детерминированной: остаток копеек достаётся строкам с наибольшей дробной частью долей, при равенстве — более ранней строке корзины.

#### Scenario: Копейки не теряются
- **WHEN** фиксированная скидка `10.00` раскладывается на три равные участвующие строки
- **THEN** скидки строк `3.34`, `3.33`, `3.33`, сумма равна `10.00`

### Requirement: Налог и итоги
Налог строки SHALL считаться со `amount - discount` по ставке категории с обычным округлением; налог заказа — сумма налогов строк. `OrderTotal.subtotal` MUST оставаться суммой до скидки, `total = subtotal - discount + shipping + tax`.

#### Scenario: Налог после скидки
- **WHEN** строка `1000.00` с налогом 20 % получила скидку `100.00`
- **THEN** налог строки `180.00`

### Requirement: Доставка
Скидка MUST NOT уменьшать стоимость доставки; бесплатная доставка определяется по сумме товаров до скидки.

#### Scenario: Доставка не меняется
- **WHEN** заказ на `3100.00` получает скидку `500.00`
- **THEN** доставка остаётся бесплатной, как и без кода

### Requirement: Условия заказа
`calculate_total` с `promo` SHALL проверять только условия заказа и выбрасывать `PromoConditionsError`, если сумма участвующих строк до скидки меньше `min_order_amount` либо участвующих строк нет. Срок и лимит `calculate_total` не проверяет.

#### Scenario: Сумма ниже минимума
- **WHEN** сумма участвующих строк `999.99`, `min_order_amount` `1000.00`
- **THEN** выбрасывается `PromoConditionsError`

#### Scenario: Ровно минимум
- **WHEN** сумма участвующих строк равна `min_order_amount`
- **THEN** код применяется

#### Scenario: Только сертификаты
- **WHEN** в корзине только подарочные сертификаты
- **THEN** выбрасывается `PromoConditionsError`

### Requirement: Промокод в OrderService
`OrderService.quote(cart, promo_code)` и `place_order(cart, promo_code)` SHALL принимать код, разрешать его через `PromoRegistry` (с нормализацией) и применять к расчёту. `promo_code` равный `None`, `""` или строке из пробелов означает отсутствие кода. Непустой код без заданного реестра MUST давать `UnknownPromoCodeError`. `Order.promo_code` SHALL содержать нормализованный код или `None`. Нестроковый `promo_code` MUST давать `ValidationError`.

#### Scenario: Пустое поле формы
- **WHEN** `place_order(cart, "   ")`
- **THEN** заказ оформляется без скидки, `order.promo_code is None`, ошибки нет

#### Scenario: Нет реестра
- **WHEN** сервис создан без `promos`, вызывается `quote(cart, "SUMMER10")`
- **THEN** выбрасывается `UnknownPromoCodeError`

#### Scenario: Нормализация в заказе
- **WHEN** `place_order(cart, " summer10 ")` для существующего кода
- **THEN** `order.promo_code == "SUMMER10"`

### Requirement: Учёт использования при оформлении
Использование кода SHALL засчитываться ровно один раз за успешно оформленный заказ. `quote`, `calculate_total`, `resolve` и неудачные попытки (любая ошибка кода, пустая корзина, ошибка расчёта) MUST NOT менять `uses`. Время для проверки срока берётся только из часов реестра.

#### Scenario: Quote не расходует лимит
- **WHEN** вызывается `quote(cart, "SUMMER10")` несколько раз
- **THEN** `uses("SUMMER10") == 0`

#### Scenario: Успешный заказ
- **WHEN** оформляется заказ с кодом
- **THEN** `uses` увеличивается на 1

#### Scenario: Неудачная попытка
- **WHEN** `place_order` падает с `PromoConditionsError` из-за минимальной суммы
- **THEN** `uses` не меняется, заказ не сохранён

#### Scenario: Последнее использование
- **WHEN** `max_uses=1` и один заказ уже оформлен
- **THEN** второй `place_order` с этим кодом выбрасывает `PromoConditionsError`


### specs/promo-codes/spec.md

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
`PromoRegistry.uses(code)` SHALL возвращать число успешно оформленных заказов с этим кодом (код нормализуется; для незарегистрированного кода — `UnknownPromoCodeError`). Изначально 0.

#### Scenario: Начальное значение
- **WHEN** код только что добавлен
- **THEN** `uses(code) == 0`


### tasks.md

## 1. Ошибки и модель промокода

- [ ] 1.1 Добавить `PromoError`, `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError` в `shop/errors.py`; проверить тестом, что три класса — независимые подклассы `PromoError`/`ShopError`
- [ ] 1.2 Создать `shop/promo.py` с `DiscountKind` и `PromoCode` (нормализация, валидация в `__post_init__`); тесты в новом `tests/test_promo.py` покрывают сценарии создания из spec `promo-codes`

## 2. Реестр

- [ ] 2.1 Реализовать `PromoRegistry` (`add`, `resolve`, `uses`, служебный `redeem`) с порядком проверок существование → срок `[starts_at, expires_at)` → лимит и временем только из `Clock`; тесты в `tests/test_promo.py` (границы, порядок, пустая строка, дубликат, регистр)

## 3. Расчёт

- [ ] 3.1 Добавить `discount` в `LineTotal` и `OrderTotal` (по умолчанию `0.00`) и параметр `promo` в `calculate_total`; проверить, что существующие тесты проходят без изменений
- [ ] 3.2 Реализовать участие строк, размер скидки, раскладку методом наибольших остатков, налог после скидки, условия заказа; тесты в `tests/test_pricing_promo.py`: сумма скидок строк равна общей, округление, FIXED больше суммы, сертификаты, доставка, минимум

## 4. Заказы

- [ ] 4.1 Расширить `OrderService` (`promos`, `quote`, `place_order`) и `Order.promo_code`: пустой код = нет кода, нет реестра → `UnknownPromoCodeError`, `redeem` только после успешного сохранения; тесты в `tests/test_orders_promo.py` (quote не расходует лимит, неудача не расходует, последнее использование)
- [ ] 4.2 Экспортировать новые имена в `shop/__init__.py` по существующему стилю; проверить импортом

## 5. Проверка

- [ ] 5.1 Запустить `python -m pytest -q`: все старые и новые тесты проходят; `git diff` не затрагивает `shop/cli.py`, `shop/reports.py` и существующие тесты
- [ ] 5.2 Сверить публичный API реализации с proposal и specs (имена модулей, классов, сигнатуры и порядок параметров, поля, значения enum, иерархия ошибок) и исправить расхождения
