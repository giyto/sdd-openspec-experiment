# SHOP-412. Промокоды при оформлении заказа

Маркетинг запускает летнюю кампанию с промокодами. Сейчас скидки вручную делает поддержка, и суммы
постоянно расходятся с чеками. Нужно, чтобы код можно было передать при расчёте и при оформлении
заказа, а скидка честно отражалась в итогах и построчно в чеке: бухгалтерия считает налог по строкам.

## Что делаем

Промокод бывает процентный или на фиксированную сумму. Скидка действует только на участвующие
товары. У кода может быть свой список исключённых категорий, кроме того, действуют общие правила
проекта (см. README). Процент считается от суммы участвующих строк и округляется по правилам
проекта. Фиксированная скидка не может быть больше суммы участвующих строк. Скидку раскладываем по
строкам заказа, и сумма по строкам должна в точности совпадать с общей скидкой. Налог строки
считается с её суммы после скидки. На стоимость доставки скидка не распространяется.

У кода могут быть минимальная сумма заказа, срок действия и лимит использований. Использованием
считается только успешно оформленный заказ: `quote`, `calculate_total` и неудачные попытки счётчик
не трогают. Проверяем по порядку: существует ли код, действует ли он сейчас, потом лимит и условия
заказа. Время берём только из внедрённых часов. Покупатели вводят код как попало, так что
обрабатываем его так же, как другие коды, которые вводят люди.

## API

```python
# shop/promo.py
class DiscountKind(StrEnum): PERCENT, FIXED

@dataclass(frozen=True)
class PromoCode:
    code: str                         # непустой
    kind: DiscountKind
    value: Decimal                    # PERCENT: (0, 100]; FIXED: рубли, > 0
    min_order_amount: Decimal = Decimal("0.00")
    starts_at: datetime | None = None
    expires_at: datetime | None = None
    max_uses: int | None = None       # None — без лимита, иначе >= 1
    excluded_categories: frozenset[Category] = frozenset()

class PromoRegistry:
    def __init__(self, clock: Clock): ...
    def add(self, promo: PromoCode) -> None: ...
    def resolve(self, code: str) -> PromoCode: ...  # есть, действует, не исчерпан, иначе исключение
    def uses(self, code: str) -> int: ...

# shop/errors.py: три независимых наследника PromoError
class PromoError(ShopError): ...
class UnknownPromoCodeError(PromoError): ...  # такого кода нет
class PromoExpiredError(PromoError): ...      # вне срока действия
class PromoConditionsError(PromoError): ...   # лимит исчерпан или заказ не подходит

# shop/pricing.py: проверяет только условия заказа, срок и лимит проверяет реестр
def calculate_total(cart, shipping=None, tax=None, *, promo: PromoCode | None = None) -> OrderTotal
LineTotal.discount: Decimal    # Decimal("0.00"), если скидки нет
OrderTotal.discount: Decimal   # total = subtotal - discount + shipping + tax

# shop/orders.py
OrderService(..., promos: PromoRegistry | None = None)  # без реестра любой код неизвестен
OrderService.quote(cart, promo_code: str | None = None)
OrderService.place_order(cart, promo_code: str | None = None)
Order.promo_code: str | None   # нормализованный код или None
```

## Рамки

* Старые вызовы `calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`,
  `place_order(cart)` работают как раньше и дают те же суммы.
* `shop/cli.py` и `shop/reports.py` не трогаем, скидки в CLI и отчётах пойдут отдельным тикетом.
  Существующие тесты не меняем, новые кладём отдельными файлами.
* Новых зависимостей не добавляем. Соглашения проекта описаны в README.

---

## Обсуждение в задаче

**Игорь Ветров (бэкенд), 12.10 11:02**
А если акция ещё не началась, это тоже `PromoExpiredError` или нужно отдельное исключение?

**Ольга Смирнова (маркетинг), 12.10 11:20**
Тоже `PromoExpiredError`, отдельное не нужно.

**Дмитрий Орлов (фронтенд), 13.10 15:05**
Когда поле промокода на форме пустое, приходит `""` или пробелы. Это ведь «без промокода», а не ошибка?

**Анна Лебедева (тимлид), 13.10 15:30**
Да. Пустой или пробельный `promo_code` в `quote`/`place_order` означает, что кода нет. А
`resolve("")` пусть остаётся неизвестным кодом.
