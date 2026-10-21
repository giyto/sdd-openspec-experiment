## Context

Мотивация — в `proposal.md`, требования — в `specs/`. Текущее состояние: `calculate_total` — чистая функция по корзине; `OrderService` хранит заказы в `OrderStore`; соглашения README (Decimal и `quantize_money`, `ShopError`-иерархия, `Clock` через конструктор, frozen-dataclass с проверкой в `__post_init__`, `normalize_key`, полуоткрытые интервалы, только stdlib) обязательны. `OrderTotal`/`LineTotal` вне `pricing.py` напрямую не конструируются, поэтому новые поля с значениями по умолчанию безопасны.

## Goals / Non-Goals

**Goals:**
- Скидка считается в одном месте (`pricing.py`) и одинаково для `quote` и `place_order`.
- Сумма построчных скидок точно равна общей скидке.
- Проверки кода (существование → срок → лимит) — в реестре, условия заказа — в расчёте.

**Non-Goals:**
- `cli.py`, `reports.py`, существующие тесты — не меняются.
- Персистентность счётчиков и распределённая атомарность: реестр in-memory, как `OrderStore`.
- Комбинирование нескольких промокодов в одном заказе.

## Decisions

1. **Нормализация через `normalize_key`.** `PromoCode.__post_init__` нормализует `code` (через `object.__setattr__`, как `Product.sku`) и требует непустоту; реестр нормализует вход в `add`/`resolve`/`uses`. Так `Order.promo_code` — нормализованный код. Альтернатива (свой `.upper()`) отвергнута: расходилась бы с SKU.
2. **`resolve("")` — `UnknownPromoCodeError`**, а не `ValidationError`: после нормализации ключ просто не найден. Пустоту как «нет кода» трактует только `OrderService` (`promo_code` через `normalize_key`, пусто → `None`). Нестроковый `promo_code` → `ValidationError` от `normalize_key`.
3. **Денежные и временные поля `PromoCode`.** `value` для `FIXED` и `min_order_amount` — `Decimal` ровно с 2 знаками (проверка `to_money(x) == x`, как у цены `Product`); `float`/`bool` отвергаются. `PERCENT` допускает дробные значения (`0.5`). `starts_at`/`expires_at` — aware; `starts_at < expires_at`. `max_uses` — `int` не `bool`, `>= 1`. `excluded_categories` — `frozenset[Category]`.
4. **Проверка срока и лимита в реестре; условия заказа в `calculate_total`.** `resolve`: unknown → `starts_at <= now < expires_at` иначе `PromoExpiredError` (включая «ещё не началась») → `uses >= max_uses` → `PromoConditionsError`. Время только `self._clock.now()`.
5. **Фиксация использования — отдельная операция реестра** (имена: `redeem(code) -> PromoCode` и `release(code)`; `uses` их не затрагивает). `redeem` под `threading.Lock` повторно выполняет `resolve`-проверки и инкрементирует; `release` декрементирует не ниже 0 без проверки срока. Lock — stdlib, защищает лимит при многопоточном HTTP-слое; альтернатива «check then increment» в сервисе допускала бы превышение лимита.
6. **Алгоритм скидки в `calculate_total`:**
   - участвующие = категория не `GIFT_CARD` и не в `excluded_categories`;
   - `base = sum(amount участвующих)`; если участвующих нет или `base < min_order_amount` → `PromoConditionsError`;
   - `PERCENT`: `quantize_money(base * value / 100)`; `FIXED`: `min(value, base)`;
   - раскладка методом наибольшего остатка: для каждой участвующей строки `exact = discount * amount / base`, `floor = exact.quantize(CENT, ROUND_DOWN)`, `rem = exact - floor`; остаток копеек `(discount - sum(floor)) / CENT` раздаётся по одной строкам, отсортированным по `(-rem, индекс в корзине)`. Вычисления в `Decimal` без промежуточного округления (`exact` считается из точных значений), контекст с достаточной точностью. Остаток копеек строго меньше числа участвующих строк, поэтому «по одной» достаточно; доля строки не превышает её сумму;
   - `tax = tax.tax_for(category, amount - discount)`;
   - `goods_after = subtotal - discount` передаётся в `shipping.cost_for` (порог); `needs_delivery` без изменений;
   - `total = subtotal - discount + shipping + tax`.
   Альтернатива — пропорциональная скидка с округлением каждой строки и «довеском» в последнюю — отвергнута: не соответствует учёту бухгалтерии.
7. **Модели.** `LineTotal.discount: Decimal = ZERO`, `OrderTotal.discount: Decimal = ZERO` (в конце списка полей — совместимо с позиционными вызовами). `Order.promo_code: str | None = None` после `status`.
8. **Поток `OrderService`.** Общий приватный метод готовит `(promo, total)`: нормализует `promo_code`; пусто/`None` → `None`; иначе при отсутствии реестра — `UnknownPromoCodeError`, иначе `promos.resolve`; затем `calculate_total(..., promo=promo)`. `quote` возвращает `total`. `place_order`: подготовка → `promos.redeem(code)` (повторная проверка под локом) → `store.next_id()` → `store.add`. Фиксация до выделения id, чтобы неудачи не оставляли дыр в нумерации и счётчик не менялся при ошибках расчёта. `cancel`: после `store.save(cancelled)` вызывает `promos.release(order.promo_code)`, если код есть; повторная отмена падает на проверке статуса раньше.
9. **Экспорт.** Новые публичные имена добавляются в `shop/__init__.py` (аддитивно); `__version__` не трогаем без запроса.

## Risks / Trade-offs

- [Отчёты и CLI не показывают скидку] → `reports.py` использует `order.total.total`, который уже учитывает скидку; показ скидки — отдельный тикет.
- [Счётчики живут в памяти и теряются при рестарте] → тот же компромисс, что у `OrderStore`; персистентность вне рамок.
- [Часы реестра и сервиса — разные объекты] → срок кода всегда по часам реестра; в сборке приложения передавать один `Clock`.
- [Ошибка округления при раскладке] → использовать точные `Decimal`-доли и проверять инвариант `sum(line.discount) == discount` property-тестом на разных корзинах.
- [`cancel` после рестарта реестра] → `release` не падает и не уходит ниже 0; для неизвестного кода — игнорируется с `logger.warning`.

## Assumptions (где тикет неоднозначен)

- Новые тесты лежат в отдельных файлах (`tests/test_promo.py`, `tests/test_pricing_promo.py`, `tests/test_orders_promo.py`); существующие не правим.
- `uses` неизвестного кода → `UnknownPromoCodeError` (а не 0).
- Дополнительные методы реестра (`redeem`, `release`) — расширение API тикета, необходимое для учёта использования и возврата; названия можно уточнить при реализации.
- Фиксированная скидка больше суммы участвующих строк не ошибка, а обрезается.
- Процент 100 допустим: участвующие строки обнуляются, доставка и налог по остальным строкам считаются как обычно.
- Скидка не может сделать `amount - discount` отрицательным; налог от нуля — `0.00`.
- Сертификаты в `excluded_categories` разрешены (избыточны, не ошибка).
- Минимальная сумма сравнивается с суммой участвующих строк до скидки, `>=`.
- Если `promo_code` не `str` и не `None` — `ValidationError`.

## Решения при реализации

- `PromoRegistry.__init__` принимает необязательный итерируемый набор кодов и `clock`; `release` для неизвестного кода только пишет `logger.warning` (как в рисках).
- `place_order` с пустой корзиной даёт `EmptyCartError` (расчёт идёт раньше фиксации), счётчик не меняется.
- Тест на потокобезопасность `redeem` добавлен в `tests/test_promo.py`.
