# WH-214: Резервирование товара под заказы

**Автор:** Анна Белова · 12.10.2026 10:05

## Зачем

Сейчас товар списывается только при отгрузке. Пока покупатель оформляет и оплачивает заказ,
тот же товар успевают продать второй раз, и потом склад звонит клиенту с извинениями. Хотим
резервировать товар под заказ в момент оформления. Если заказ не оплатили, резерв должен сам
перестать действовать через TTL. Фоновых задач у нас нет и не будет, поэтому истёк резерв или нет,
решаем по часам сервиса в момент обращения.

## Что сделать

Резервы делаем в `Inventory`, по соглашениям из README. Публичный API:

```python
# warehouse/models.py
class ReservationStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"

@dataclass(frozen=True)
class ReservationLine:
    warehouse: str
    sku: str
    qty: int

@dataclass(frozen=True)
class Reservation:                        # снимок, статус — на текущий момент
    order_id: str
    lines: tuple[ReservationLine, ...]    # как передали, в том же порядке
    created_at: datetime
    expires_at: datetime
    status: ReservationStatus

# warehouse/errors.py — у всех атрибут order_id
class ReservationError(WarehouseError): ...
class ReservationNotFoundError(ReservationError): ...
class ReservationExpiredError(ReservationError): ...
class ReservationStateError(ReservationError): ...    # операция недопустима в этом статусе
class DuplicateReservationError(ReservationError): ...

# warehouse/reservations.py
DEFAULT_RESERVATION_TTL: timedelta

# новые методы Inventory
def reserve(self, order_id: str, lines: Iterable[tuple[str, str, int] | ReservationLine],
            ttl: timedelta | None = None) -> Reservation: ...
def confirm(self, order_id: str) -> Reservation: ...
def cancel(self, order_id: str) -> Reservation: ...
def extend(self, order_id: str, ttl: timedelta) -> Reservation: ...
def get_reservation(self, order_id: str) -> Reservation: ...
def available(self, warehouse: str, sku: str) -> int: ...
def reserved(self, warehouse: str, sku: str) -> int: ...
```

Как должно работать:

- `reserve` держит товар под заказ сразу по всем строкам, строки могут быть на разных складах.
  Физический остаток не меняется. `created_at` — текущее время по часам сервиса,
  `expires_at = created_at + ttl`, TTL по умолчанию 30 минут. `ttl` — положительный `timedelta`,
  иначе `ValidationError`; заказ без строк — тоже `ValidationError`. `order_id` — такой же код,
  как SKU и склады. Не хватает товара — `InsufficientStockError`.
- `reserved` — сумма активных резервов по позиции, `available` — физический остаток минус она.
  Резервировать можно только из доступного.
- Истёкший резерв получает статус `EXPIRED` и в `available`/`reserved` не учитывается.
  Само истечение в журнал не пишем.
- `confirm` превращает активный резерв в отгрузку: физический остаток уменьшается по каждой строке,
  статус `CONFIRMED`. Товар зарезервирован именно под этот заказ, так что нулевой `available`
  подтверждению не мешает. Истёкший резерв — `ReservationExpiredError`, уже подтверждённый или
  отменённый — `ReservationStateError`.
- `cancel` освобождает резерв (`CANCELLED`). Отмена идемпотентна: повторная отмена ничего
  не делает и ничего не пишет. Подтверждённый отменить нельзя — `ReservationStateError`.
- `extend` продлевает активный резерв на `ttl`. `ttl` проверяем как в `reserve`, ошибки
  по статусам такие же, как у `confirm`.
- Если резерва по `order_id` нет, `confirm`, `cancel`, `extend` и `get_reservation` бросают
  `ReservationNotFoundError`.
- `issue` не должен забирать товар из чужих активных резервов: просят больше доступного —
  `InsufficientStockError`.
- События пишем в журнал как обычно: `RESERVE` на каждую строку (`order`, `wh`, `sku`, `qty`,
  `expires`); при `confirm` — обычный `ISSUE` на каждую строку с `ref` = номер заказа, затем
  `RESERVE_CONFIRM` (`order`); `RESERVE_CANCEL` (`order`); `RESERVE_EXTEND` (`order`, `expires`).

## Рамки

- Старый API `Inventory` не ломаем: конструктор, `receive/issue/transfer/adjust/on_hand/stock_levels`
  для кода без резервов работают как раньше; `on_hand` и `stock_levels` показывают физический остаток.
- `warehouse/cli.py` и `warehouse/reports.py` не трогаем, существующие тесты не меняем,
  новых зависимостей не добавляем.

---

## Обсуждение в задаче

**Ольга Смирнова** · 12.10.2026 11:20
Про корзины: одна и та же позиция (склад + SKU) иногда приходит двумя строками, когда товар
добавили дважды. Наличие проверяем по сумме таких строк, при `confirm` тоже. Склеивать строки
в резерве не надо, храним как пришли.

**Анна Белова** · 13.10.2026 16:10
UPD: маркетинг попросил TTL по умолчанию 15 минут, а не 30.
`DEFAULT_RESERVATION_TTL = timedelta(minutes=15)`.

**Дмитрий Козлов** · 14.10.2026 10:15
А что показывает снимок подтверждённого заказа, когда время резерва уже прошло? EXPIRED?

**Анна Белова** · 14.10.2026 10:32
Нет, `CONFIRMED` и `CANCELLED` окончательные, истечение их не меняет.
