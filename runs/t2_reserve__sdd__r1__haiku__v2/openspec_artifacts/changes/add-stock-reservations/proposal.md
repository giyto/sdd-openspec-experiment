## Why

Товар сейчас списывается только при отгрузке. Пока покупатель оформляет и оплачивает заказ,
тот же товар можно продать повторно, и склад потом извиняется перед клиентом. Нужно резервировать
товар под заказ в момент оформления. Неоплаченный резерв должен сам перестать действовать по TTL.
Фоновых задач в сервисе нет и не будет, поэтому истечение определяется по часам сервиса в момент
обращения, без записи в журнал.

## What Changes

- Новые методы `Inventory`: `reserve`, `confirm`, `cancel`, `extend`, `get_reservation`,
  `available`, `reserved`. Резерв держит товар по всем строкам заказа (строки могут быть на разных
  складах), физический остаток при этом не меняется.
- Срок резерва `expires_at = created_at + ttl`, TTL по умолчанию `DEFAULT_RESERVATION_TTL` = 15 минут.
  По достижении `expires_at` резерв считается `EXPIRED` и не учитывается в `available`/`reserved`.
- `confirm` превращает активный резерв в отгрузку: списывает физический остаток по строкам
  (события `ISSUE` с `ref` = номер заказа, затем `RESERVE_CONFIRM`).
- `cancel` освобождает резерв; `extend` продлевает активный резерв до `now + ttl` (срок не сокращается).
- Новые модели `ReservationStatus`, `ReservationLine`, `Reservation` в `warehouse/models.py`;
  новые исключения `ReservationError` и наследники в `warehouse/errors.py`;
  константа `DEFAULT_RESERVATION_TTL` в `warehouse/reservations.py`.
- Новые события журнала: `RESERVE`, `RESERVE_CONFIRM`, `RESERVE_CANCEL`, `RESERVE_EXTEND`.
- **BREAKING (для `issue`/`transfer`, только при наличии резервов):** `issue` и `transfer` не могут
  забрать товар, зарезервированный активными резервами других заказов; при нехватке доступного
  остатка бросают `InsufficientStockError`. Для кода без резервов поведение не меняется.

Без изменений: сигнатуры и поведение `receive`, `adjust`, `on_hand`, `stock_levels`, формат строк
журнала, `warehouse/cli.py`, `warehouse/reports.py`, существующие тесты.

## Capabilities

### New Capabilities
- `inventory-reservations`: резервирование товара под заказы — жизненный цикл резерва
  (активный, истёкший, подтверждённый, отменённый), TTL и продление, расчёт `available`/`reserved`,
  подтверждение с физическим списанием, события журнала по резервам.

### Modified Capabilities
<!-- Нет: в openspec/specs/ пока нет существующих спецификаций. Ограничение на issue/transfer
     описано внутри нового capability, отдельного изменяемого capability нет. -->

## Impact

- Код: `warehouse/models.py`, `warehouse/errors.py`, новый `warehouse/reservations.py`,
  `warehouse/inventory.py`, `warehouse/storage.py` (хранение резервов по `order_id`).
- Журнал: четыре новых типа событий; существующие типы и формат строк не меняются.
- Зависимости: новых нет (только стандартная библиотека).
- Документация: `README.md` (дерево модулей) — обновить список модулей.
- Тесты: новые тесты для резервов; существующие тесты не меняются.
