## Purpose

Резервирование физического остатка под заказы: держим товар на время оформления и оплаты,
истечение резерва по часам сервиса, подтверждение с отгрузкой и отмена.

## ADDED Requirements

### Requirement: Reserve holds stock for an order
The system SHALL allow reserving stock for an order by `order_id` across one or more lines.
Each line is `(warehouse, sku, qty)` or a `ReservationLine`. Lines SHALL be stored in the order
they were given, without merging lines of the same warehouse and SKU. A reservation SHALL NOT change
the physical stock. `created_at` SHALL be the current service clock time, `expires_at` SHALL be
`created_at + ttl`, and `ttl` SHALL default to `DEFAULT_RESERVATION_TTL` (15 minutes).

#### Scenario: Reservation across warehouses
- **WHEN** an order reserves `("MAIN", "BOLT-M8", 2)` and `("EAST", "BOLT-M8", 1)`
- **THEN** the reservation is returned with status `ACTIVE` and its lines in the same order
- **AND** the physical stock on both warehouses is unchanged

#### Scenario: Default TTL
- **WHEN** an order is reserved without `ttl`
- **THEN** `expires_at` equals `created_at` plus 15 minutes

#### Scenario: Duplicate SKU lines are checked by their sum
- **WHEN** an order reserves two lines for `("MAIN", "BOLT-M8")` with qty 2 and 3, and `MAIN` has 4 on hand
- **THEN** the reservation fails with `InsufficientStockError` and nothing is reserved

#### Scenario: Insufficient stock
- **WHEN** an order reserves more than `available` for any position
- **THEN** the system raises `InsufficientStockError` and creates no reservation and writes no event

### Requirement: Reserve input validation
The system SHALL reject a reservation with `ValidationError` when the order has no lines or `ttl`
is not a positive `timedelta`. A line with an invalid quantity SHALL raise `InvalidQuantityError`.
A line with an unknown SKU SHALL raise `UnknownSkuError`. `order_id` SHALL follow the same code rules as SKU
and warehouse codes. Validation failures SHALL NOT change state or write events.

#### Scenario: Empty order
- **WHEN** `reserve` is called with no lines
- **THEN** the system raises `ValidationError`

#### Scenario: Non-positive TTL
- **WHEN** `reserve` is called with `ttl` of zero or a negative `timedelta`
- **THEN** the system raises `ValidationError`

### Requirement: Duplicate reservations
The system SHALL raise `DuplicateReservationError` when `reserve` is called for an `order_id` that has
an `ACTIVE` or `CONFIRMED` reservation. A previous reservation that is `EXPIRED` or `CANCELLED` SHALL
be replaced entirely by the new reservation.

#### Scenario: Active reservation exists
- **WHEN** an order with an active reservation is reserved again
- **THEN** the system raises `DuplicateReservationError` and the existing reservation is unchanged

#### Scenario: Expired reservation is replaced
- **WHEN** an order whose reservation has expired is reserved again
- **THEN** the new reservation replaces the old one and is returned with status `ACTIVE`

### Requirement: Reserved and available quantities
The system SHALL report `reserved(warehouse, sku)` as the sum of quantities of lines of `ACTIVE`
reservations (not yet expired) for that position. `available(warehouse, sku)` SHALL be the physical stock minus
`reserved`, never less than 0. Both SHALL raise `UnknownSkuError` for an unregistered SKU and return 0 for
a registered SKU with no stock or reservations.

#### Scenario: Available after reserve
- **WHEN** `MAIN` has 10 on hand and an active reservation holds 4 of `BOLT-M8`
- **THEN** `reserved("MAIN", "BOLT-M8")` is 4 and `available("MAIN", "BOLT-M8")` is 6

#### Scenario: Physical stock below reserved
- **WHEN** stock is adjusted down to 2 while 5 units are actively reserved
- **THEN** `available` is 0, `reserved` is 5, and `on_hand` is 2

### Requirement: Expiration by service clock
A reservation SHALL be `EXPIRED` at the moment `expires_at` is reached or passed, as observed through the
service clock. Expired reservations SHALL NOT count in `reserved` or `available`. Expiration SHALL NOT
write an event to the journal and SHALL NOT change the stored state other than what the clock implies.

#### Scenario: Reservation expires
- **WHEN** the clock reaches `expires_at` of an active reservation
- **THEN** `get_reservation` returns status `EXPIRED`
- **AND** `available` and `reserved` no longer count its lines
- **AND** no event is written

### Requirement: Get reservation
The system SHALL return a snapshot of the reservation for `order_id` with status evaluated at the current
clock time. It SHALL raise `ReservationNotFoundError` when no reservation exists for that order.

#### Scenario: Unknown order
- **WHEN** `get_reservation` is called for an order that was never reserved
- **THEN** the system raises `ReservationNotFoundError`

### Requirement: Confirm turns a reservation into a shipment
The system SHALL confirm an `ACTIVE` reservation by issuing its stock: for each line the physical stock is
reduced by the line quantity, and the reservation becomes `CONFIRMED`. The check SHALL be against physical
stock, summed per warehouse and SKU across the order's own lines, not against `available`. If physical stock is
insufficient for any position, the system SHALL raise `InsufficientStockError`, change nothing, and keep the
reservation `ACTIVE`.

Errors: an `EXPIRED` reservation raises `ReservationExpiredError`; a `CONFIRMED` or `CANCELLED` reservation
raises `ReservationStateError`; no reservation raises `ReservationNotFoundError`.

#### Scenario: Successful confirm with zero available
- **WHEN** `MAIN` has 4 on hand, all 4 reserved by order `SO-1`, and `SO-1` is confirmed
- **THEN** physical stock becomes 0, the reservation is `CONFIRMED`, and the journal contains one `ISSUE`
  per line with `ref=SO-1` followed by `RESERVE_CONFIRM` with `order=SO-1`

#### Scenario: Physical shortage at confirm
- **WHEN** a line of the order is larger than the physical stock at confirm time
- **THEN** the system raises `InsufficientStockError`, no stock changes, no events are written, and the
  reservation stays `ACTIVE`

#### Scenario: Confirm expired reservation
- **WHEN** `confirm` is called after `expires_at`
- **THEN** the system raises `ReservationExpiredError`

#### Scenario: Confirm twice
- **WHEN** `confirm` is called for an already `CONFIRMED` reservation
- **THEN** the system raises `ReservationStateError`

### Requirement: Cancel releases a reservation
The system SHALL cancel an `ACTIVE` reservation, making it `CANCELLED` and writing `RESERVE_CANCEL`
with `order`. Cancelling an already `CANCELLED` reservation, or an `EXPIRED` one, SHALL change nothing and
write nothing; an `EXPIRED` reservation remains `EXPIRED`. Cancelling a `CONFIRMED` reservation SHALL raise
`ReservationStateError`. A missing reservation SHALL raise `ReservationNotFoundError`.

#### Scenario: Cancel active
- **WHEN** an active reservation is cancelled
- **THEN** its status is `CANCELLED`, `available` increases accordingly, and `RESERVE_CANCEL` is written

#### Scenario: Cancel is idempotent
- **WHEN** a cancelled reservation is cancelled again
- **THEN** nothing changes and no event is written

#### Scenario: Cancel expired
- **WHEN** an expired reservation is cancelled
- **THEN** it stays `EXPIRED` and no event is written

#### Scenario: Cancel confirmed
- **WHEN** a confirmed reservation is cancelled
- **THEN** the system raises `ReservationStateError`

### Requirement: Extend an active reservation
The system SHALL extend an `ACTIVE` reservation by `ttl` counted from the current clock time, so the new
`expires_at` is `now + ttl`. `ttl` SHALL be validated as in `reserve`. The expiry SHALL NEVER be shortened: if
`now + ttl` is not later than the current `expires_at`, the reservation SHALL stay unchanged and no event is
written. A successful extension SHALL write `RESERVE_EXTEND` with `order` and `expires`.
Errors: `EXPIRED` raises `ReservationExpiredError`; `CONFIRMED` or `CANCELLED` raises `ReservationStateError`;
missing raises `ReservationNotFoundError`.

#### Scenario: Extend active reservation
- **WHEN** an active reservation with 5 minutes left is extended by 15 minutes
- **THEN** `expires_at` becomes `now + 15 minutes` and `RESERVE_EXTEND` is written

#### Scenario: Extend would not move expiry forward
- **WHEN** `now + ttl` is not later than the current `expires_at`
- **THEN** nothing changes and no event is written

#### Scenario: Extend expired reservation
- **WHEN** `extend` is called after `expires_at`
- **THEN** the system raises `ReservationExpiredError`

### Requirement: Journal events for reservations
The system SHALL write these events, in addition to the existing types: `RESERVE` once per line with fields
`order`, `wh`, `sku`, `qty`, `expires`; `RESERVE_CONFIRM` with `order`; `RESERVE_CANCEL` with `order`;
`RESERVE_EXTEND` with `order` and `expires`. Confirmation writes `ISSUE` per line with `ref` equal to the
order id before `RESERVE_CONFIRM`. Events SHALL use the existing journal line format.

#### Scenario: Reserve events
- **WHEN** an order with two lines is reserved
- **THEN** the journal gets two `RESERVE` events, one per line, in the order of the lines

### Requirement: Stock outflows respect active reservations
`issue` SHALL raise `InsufficientStockError` when the requested quantity is more than `available` for that
position, so it cannot take stock held by active reservations. `transfer` SHALL apply the same check to its
source position. Without any reservations these operations behave as before.

#### Scenario: Issue beyond available
- **WHEN** `MAIN` has 10 on hand with 8 reserved by an active order and `issue` asks for 3
- **THEN** the system raises `InsufficientStockError` and the stock is unchanged

#### Scenario: Issue without reservations
- **WHEN** no reservations exist and `issue` asks for an amount up to the on-hand stock
- **THEN** the issue succeeds as before

### Requirement: Snapshots and existing API
The system SHALL return `Reservation` snapshots whose `lines` preserve the input order. `on_hand` and
`stock_levels` SHALL keep returning physical stock. `receive`, `adjust`, and existing journal formats SHALL keep
their current behavior.

#### Scenario: Snapshot is immutable
- **WHEN** a caller holds a reservation snapshot and the reservation is later confirmed
- **THEN** the caller's snapshot still shows the status it had when returned
