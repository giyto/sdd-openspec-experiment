## Context

Мотивация и объём — в `proposal.md`, требования — в `specs/`. Текущее состояние: `calculate_total` — чистая функция без скидок; `OrderService` хранит заказы в `OrderStore` и не знает про промокоды; `normalize_key` в `shop/catalog.py` — единственная нормализация вводимых людьми кодов; `FixedClock` — способ управлять временем в тестах. Ограничения проекта (README): `Decimal` и `quantize_money` (`ROUND_HALF_UP`), только наследники `ShopError`, никакого `datetime.now()`, frozen-датаклассы с инвариантами в `__post_init__`, полуоткрытые интервалы, только стандартная библиотека. Публичный API из тикета не меняется, только дополняется.

## Goals / Non-Goals

**Goals:**
- Скидка считается один раз в `calculate_total`, а `LineTotal`/`OrderTotal` несут итоговые цифры, по которым строятся налог и чек.
- Счётчик использований меняется только при успешном `place_order` и откате в `cancel`.
- Вызовы без промокода дают побайтно прежние результаты.

**Non-Goals:**
- Скидки в `shop/cli.py` и `shop/reports.py` (отдельный тикет; они продолжают работать, так как новые поля имеют значения по умолчанию).
- Потокобезопасность, персистентность счётчиков, комбинирование нескольких кодов.

## Decisions

1. **Нормализация кода** — через `normalize_key` из `shop/catalog.py` в `PromoCode.__post_init__` (через `object.__setattr__`, как в `Product`), в `add`, `resolve`, `uses`, `consume`, `release`. Пустой после нормализации код в `PromoCode` — `ValidationError`; в `resolve("")` — просто не найден → `UnknownPromoCodeError`. Пустой ввод «без кода» обрабатывается в `OrderService`, а не в реестре. Альтернатива (своя нормализация) отвергнута: README требует единую.

2. **Проверки реестра** в `resolve` строго по порядку: поиск → интервал `starts_at <= now < expires_at` (иначе `PromoExpiredError`, в том числе «ещё не началась») → `uses >= max_uses` (`PromoConditionsError`). Время только `self._clock.now()`. Проверки условий заказа живут в `calculate_total`, которому реестр не нужен (чистая функция, `promo` передаётся объектом).

3. **Учёт использований** — реестр хранит `dict[str, int]`. Помимо заданных `add/resolve/uses` добавлены `consume(code)` и `release(code)` (вынужденное дополнение: `OrderService` должен менять счётчик, а публичного способа в API нет). `resolve` и `uses` счётчик не трогают. Альтернатива — считать использования по `OrderStore`: отвергнуто, потому что лимит принадлежит реестру, а у `OrderService` может быть общий реестр и разные хранилища.

4. **Транзакционность `place_order`**: порядок — `quote` (resolve + расчёт; любое исключение ничего не меняет) → `store.next_id()` → `store.add(order)` → `registry.consume(code)`. Счётчик увеличивается последним, после того как заказ сохранён. Повторный `resolve` между `quote` и `consume` не нужен в однопоточном режиме (допущение: потокобезопасности нет, как и у `OrderStore`). Заметим: `next_id()` вызывается только после успешного `quote`, чтобы неудачные попытки не «съедали» номера.

5. **`cancel`**: сначала существующая логика (`InvalidOrderStateError` для не-`PLACED`), затем `store.save(cancelled)`, затем `release(order.promo_code)`, если у заказа есть код и у сервиса есть реестр. `release` не опускает счётчик ниже 0 и не проверяет срок действия.

6. **Алгоритм скидки в `calculate_total`** (всё в `Decimal`, без `float`):
   - участвующие строки: `category is not GIFT_CARD and category not in promo.excluded_categories`;
   - `base = sum_money(amount участвующих)`; если участвующих нет или `base < promo.min_order_amount` — `PromoConditionsError`;
   - `PERCENT`: `quantize_money(base * value / 100)`; `FIXED`: `min(value, base)`;
   - раскладка методом наибольшего остатка в целых копейках: `share_i = D_kop * a_i // S_kop`, остаток `D_kop * a_i % S_kop`; недостающие `D_kop - sum(share_i)` копеек получают строки по убыванию остатка, при равенстве — по возрастанию индекса в корзине (`sorted(..., key=(-rem, idx))`). Целочисленная арифметика исключает ошибки округления; скидка строки не превышает её сумму, сумма скидок строк равна общей;
   - налог строки: `tax.tax_for(category, amount - discount)`;
   - доставка: `shipping.cost_for(subtotal - discount, needs_delivery=...)`; сама `cost_for` не меняется;
   - `total = subtotal - discount + shipping + tax`.
   Альтернатива — округлять долю каждой строки `HALF_UP` и править последнюю: отвергнута, не совпадает с учётом бухгалтерии.

7. **Форма данных**: `LineTotal.discount: Decimal = ZERO` и `OrderTotal.discount: Decimal = ZERO` добавлены последними полями с значением по умолчанию — существующие конструкторы и `cli`/`reports` не ломаются. `Order.promo_code: str | None = None` — последнее поле. `amount` и `subtotal` остаются до скидки (чек показывает «сумма, скидка, налог»).

8. **Валидация `PromoCode`** — в `__post_init__`, только `ValidationError`: `value` должен быть `Decimal` (конечный); `PERCENT` — `0 < value <= 100`; `FIXED` — `value > 0` и `to_money(value) == value` (допущение: фиксированная скидка в копейках); `min_order_amount >= 0` и ровно копейки (допущение); `max_uses` — `int`, не `bool`, `>= 1`; `starts_at`/`expires_at` — aware; при обеих границах `starts_at < expires_at`; `excluded_categories` — набор `Category` (не-frozenset приводится к `frozenset`). Дробный процент (например `12.5`) допускается.

9. **Допущения по неоднозначностям** (решение принято без уточнения):
   - `uses(unknown)` → `UnknownPromoCodeError` (а не `0`), единообразно с `resolve`.
   - Пустая корзина → `EmptyCartError` до проверки кода.
   - Нестроковый `promo_code` (не `None`) → `ValidationError` из `normalize_key`.
   - Порог бесплатной доставки для корзины со скидкой считается по `subtotal - discount`, включая стоимость сертификатов в корзине (как и раньше сертификаты входят в `subtotal`).
   - Код с `excluded_categories`, содержащим `GIFT_CARD`, допустим (сертификаты и так не участвуют).
   - Лимит проверяется в момент `quote`/`place_order` (`uses >= max_uses` → ошибка), поэтому `quote` может сообщить об исчерпании, как и оформление.

## Risks / Trade-offs

- [Между `quote` и `consume` другой поток может исчерпать лимит] → вне объёма (нет потокобезопасности в проекте); отмечено как допущение.
- [`place_order` падает после `store.add`, до `consume`] → `consume` — простое увеличение счётчика в памяти, исключений не бросает, поэтому окно практически отсутствует.
- [Отмена заказа с кодом, который реестр не знает (другой экземпляр реестра)] → `release` для неизвестного кода в `cancel` игнорируется (с записью в лог), отмена не должна падать.
- [Дополнительные методы `consume`/`release` расширяют публичный API] → осознанное дополнение; заданные сигнатуры не изменены.
