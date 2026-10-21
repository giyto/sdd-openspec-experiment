## MODIFIED Requirements

### Requirement: Reserve holds stock for an order
The system SHALL allow reserving stock for an order by `order_id` across one or more lines.
Each line is `(warehouse, sku, qty)` or a `ReservationLine`. Lines SHALL be stored in the order
they were given, without merging lines of the same warehouse and SKU. A reservation SHALL NOT change
the physical stock. `created_at` SHALL be the current service clock time, `expires_at` SHALL be
`created_at + ttl`, and `ttl` SHALL default to `DEFAULT_RESERVATION_TTL` (20 minutes).

#### Scenario: Reservation across warehouses
- **WHEN** an order reserves `("MAIN", "BOLT-M8", 2)` and `("EAST", "BOLT-M8", 1)`
- **THEN** the reservation is returned with status `ACTIVE` and its lines in the same order
- **AND** the physical stock on both warehouses is unchanged

#### Scenario: Default TTL
- **WHEN** an order is reserved without `ttl`
- **THEN** `expires_at` equals `created_at` plus 20 minutes

#### Scenario: Duplicate SKU lines are checked by their sum
- **WHEN** an order reserves two lines for `("MAIN", "BOLT-M8")` with qty 2 and 3, and `MAIN` has 4 on hand
- **THEN** the reservation fails with `InsufficientStockError` and nothing is reserved

#### Scenario: Insufficient stock
- **WHEN** an order reserves more than `available` for any position
- **THEN** the system raises `InsufficientStockError` and creates no reservation and writes no event

### Requirement: Reserve input validation
The system SHALL reject a reservation with `ValidationError` when the order has no lines, when `ttl`
is not a positive `timedelta`, or when `ttl` is greater than `MAX_RESERVATION_LIFETIME`. A line with an
invalid quantity SHALL raise `InvalidQuantityError`. A line with an unknown SKU SHALL raise `UnknownSkuError`.
`order_id` SHALL follow the same code rules as SKU and warehouse codes. Validation failures SHALL NOT change
state or write events.

#### Scenario: Empty order
- **WHEN** `reserve` is called with no lines
- **THEN** the system raises `ValidationError`

#### Scenario: Non-positive TTL
- **WHEN** `reserve` is called with `ttl` of zero or a negative `timedelta`
- **THEN** the system raises `ValidationError`

#### Scenario: TTL above the lifetime limit
- **WHEN** `reserve` is called with `ttl` greater than `MAX_RESERVATION_LIFETIME`
- **THEN** the system raises `ValidationError` and the existing reservation of the order, if any, is unchanged

#### Scenario: TTL equal to the lifetime limit
- **WHEN** `reserve` is called with `ttl` equal to `MAX_RESERVATION_LIFETIME`
- **THEN** the reservation is created with `expires_at` equal to `created_at` plus `MAX_RESERVATION_LIFETIME`

### Requirement: Duplicate reservations
The system SHALL raise `DuplicateReservationError` when `reserve` is called for an `order_id` that has a
`CONFIRMED` reservation. When the order has an `ACTIVE` reservation, `reserve` SHALL replace it: the new
reservation is a new reservation in its entirety, with its own `created_at` and `expires_at` counted from the
moment of replacement. A previous reservation that is `EXPIRED` or `CANCELLED` SHALL be replaced entirely by
the new reservation without any event for the previous one.

When an `ACTIVE` reservation is replaced, the availability check SHALL treat the quantities of the replaced
reservation as free. If the new lines do not fit, the system SHALL raise `InsufficientStockError` and the
existing reservation SHALL remain unchanged. On success the journal SHALL contain `RESERVE_CANCEL` with `order`
for the replaced reservation, followed by one `RESERVE` per line of the new reservation.

#### Scenario: Confirmed reservation cannot be replaced
- **WHEN** an order with a `CONFIRMED` reservation is reserved again
- **THEN** the system raises `DuplicateReservationError` and the confirmed reservation is unchanged

#### Scenario: Active reservation is replaced
- **WHEN** an order with an `ACTIVE` reservation of `("MAIN", "BOLT-M8", 4)` is reserved again with `("MAIN", "BOLT-M8", 3)`
- **THEN** the new reservation is returned with status `ACTIVE`, its own `created_at`, and `expires_at` equal to the replacement time plus the TTL
- **AND** `reserved("MAIN", "BOLT-M8")` is 3
- **AND** the journal contains `RESERVE_CANCEL` with `order` for the old reservation followed by one `RESERVE` for the new line

#### Scenario: Replacement frees the old quantities
- **WHEN** `MAIN` has 4 `BOLT-M8` on hand, an order holds 4 actively, and the same order is reserved again with 4
- **THEN** the replacement succeeds

#### Scenario: Replacement that does not fit keeps the old reservation
- **WHEN** an order holds 2 `BOLT-M8` at `MAIN` actively, `MAIN` has 3 on hand, and the order is reserved again with 4
- **THEN** the system raises `InsufficientStockError`, the old reservation remains `ACTIVE` with its original `expires_at`, and no event is written

#### Scenario: Expired reservation is replaced
- **WHEN** an order whose reservation has expired is reserved again
- **THEN** the new reservation replaces the old one and is returned with status `ACTIVE`
- **AND** no `RESERVE_CANCEL` is written for the expired reservation

### Requirement: Cancel releases a reservation
The system SHALL cancel an `ACTIVE` reservation, making it `CANCELLED` and writing `RESERVE_CANCEL`
with `order`. Cancelling a `CONFIRMED` reservation SHALL be a return: for each line, in the order of the
lines, the physical stock of the line's warehouse and SKU SHALL increase by the line quantity, a `RECEIVE`
event SHALL be written with `ref` equal to the order id, and after all lines the reservation SHALL become
`CANCELLED` with a `RESERVE_CANCEL` event with `order`. Cancelling an already `CANCELLED` reservation,
or an `EXPIRED` one, SHALL change nothing and write nothing; an `EXPIRED` reservation remains `EXPIRED`.
A missing reservation SHALL raise `ReservationNotFoundError`.

#### Scenario: Cancel active
- **WHEN** an active reservation is cancelled
- **THEN** its status is `CANCELLED`, `available` increases accordingly, and `RESERVE_CANCEL` is written

#### Scenario: Cancel is idempotent
- **WHEN** a cancelled reservation is cancelled again
- **THEN** nothing changes and no event is written

#### Scenario: Cancel expired
- **WHEN** an expired reservation is cancelled
- **THEN** it stays `EXPIRED` and no event is written

#### Scenario: Cancel confirmed is a return
- **WHEN** `MAIN` has 0 `BOLT-M8` on hand after `SO-1` with `("MAIN", "BOLT-M8", 2)` and `("EAST", "BOLT-M8", 1)` was confirmed, and `SO-1` is cancelled
- **THEN** `on_hand` of `MAIN` is 2 and of `EAST` is 1, the reservation is `CANCELLED`
- **AND** the journal contains `RECEIVE` with `ref=SO-1` and `wh=MAIN` followed by `RECEIVE` with `ref=SO-1` and `wh=EAST`, then `RESERVE_CANCEL` with `order=SO-1`

#### Scenario: Cancel of a returned reservation is idempotent
- **WHEN** a reservation that was cancelled as a return is cancelled again
- **THEN** nothing changes and no event is written

### Requirement: Extend an active reservation
The system SHALL extend an `ACTIVE` reservation by `ttl` counted from the current clock time, so the new
`expires_at` is `now + ttl`. `ttl` SHALL be validated as in `reserve`, except that a `ttl` greater than
`MAX_RESERVATION_LIFETIME` is not an error. The expiry SHALL NEVER be shortened and SHALL NEVER be later than
`created_at + MAX_RESERVATION_LIFETIME`: the new `expires_at` SHALL be `min(now + ttl, created_at + MAX_RESERVATION_LIFETIME)`.
If that value is not later than the current `expires_at`, the reservation SHALL stay unchanged and no event is
written. A successful extension SHALL write `RESERVE_EXTEND` with `order` and `expires`.
Errors: `EXPIRED` raises `ReservationExpiredError`; `CONFIRMED` or `CANCELLED` raises `ReservationStateError`;
missing raises `ReservationNotFoundError`.

#### Scenario: Extend active reservation
- **WHEN** an active reservation with 5 minutes left is extended by 15 minutes
- **THEN** `expires_at` becomes `now + 15 minutes` and `RESERVE_EXTEND` is written

#### Scenario: Extend would not move expiry forward
- **WHEN** `now + ttl` is not later than the current `expires_at`
- **THEN** nothing changes and no event is written

#### Scenario: Extend capped by the lifetime limit
- **WHEN** an active reservation created at `T` is extended by `ttl` such that `now + ttl` is later than `T + MAX_RESERVATION_LIFETIME`
- **THEN** no error is raised, `expires_at` becomes exactly `T + MAX_RESERVATION_LIFETIME`, and `RESERVE_EXTEND` is written

#### Scenario: Extend at the lifetime limit
- **WHEN** an active reservation already has `expires_at` equal to `created_at + MAX_RESERVATION_LIFETIME` and is extended
- **THEN** nothing changes and no event is written

#### Scenario: Extend expired reservation
- **WHEN** `extend` is called after `expires_at`
- **THEN** the system raises `ReservationExpiredError`

### Requirement: Journal events for reservations
The system SHALL write these events, in addition to the existing types: `RESERVE` once per line with fields
`order`, `wh`, `sku`, `qty`, `expires`; `RESERVE_CONFIRM` with `order`; `RESERVE_CANCEL` with `order`;
`RESERVE_EXTEND` with `order` and `expires`; `RESERVE_EXPIRE` with `order` and `expires`. Confirmation writes
`ISSUE` per line with `ref` equal to the order id before `RESERVE_CONFIRM`. Cancelling a `CONFIRMED`
reservation writes `RECEIVE` per line with `ref` equal to the order id before `RESERVE_CANCEL`. Replacement
of an `ACTIVE` reservation writes `RESERVE_CANCEL` before the `RESERVE` events of the new reservation.
Events SHALL use the existing journal line format.

#### Scenario: Reserve events
- **WHEN** an order with two lines is reserved
- **THEN** the journal gets two `RESERVE` events, one per line, in the order of the lines

## ADDED Requirements

### Requirement: Maximum reservation lifetime
The system SHALL define `MAX_RESERVATION_LIFETIME` as 2 hours. For every reservation, `expires_at` SHALL NOT be
later than `created_at + MAX_RESERVATION_LIFETIME`. The limit SHALL be enforced by `reserve` (through validation
of `ttl`) and by `extend` (through capping), and SHALL NOT be enforced by changing an existing reservation in any other way.

#### Scenario: Limit value
- **WHEN** the limit is read
- **THEN** `MAX_RESERVATION_LIFETIME` equals 2 hours

### Requirement: List reservations
The system SHALL return `reservations(status=None)` as a list of `Reservation` snapshots, one per order, holding the
current reservation of each order. Each snapshot SHALL carry the status evaluated at the current clock time. The list
SHALL be sorted by `created_at` and then by `order_id`. When `status` is given, the list SHALL contain only snapshots
whose evaluated status equals `status`. With no `status`, the list SHALL contain reservations of every status.
The method SHALL NOT write events and SHALL NOT change stored state.

#### Scenario: Expired reservation is reported as expired
- **WHEN** an order's reservation has passed `expires_at` and `reservations(status=ReservationStatus.EXPIRED)` is called
- **THEN** the list contains that order's reservation with status `EXPIRED`

#### Scenario: Ordering
- **WHEN** orders `SO-2` created at `10:00` and `SO-1` created at `10:00` and `SO-3` created at `09:00` exist
- **THEN** `reservations()` returns `SO-3`, `SO-1`, `SO-2`

#### Scenario: One snapshot per order after replacement
- **WHEN** an order is reserved, its active reservation is replaced, and `reservations()` is called
- **THEN** the list contains exactly one entry for that order, the replacement

### Requirement: Availability by position
The system SHALL return `availability(warehouse=None)` as a list of `Availability` records, one per position
`(warehouse, sku)` that has physical stock greater than 0 or quantity held by `ACTIVE` reservations (not yet expired).
Each record SHALL carry `on_hand`, `reserved`, and `available` with the same values that `on_hand`, `reserved`, and
`available` return for that position. The list SHALL be sorted by warehouse and then by SKU, and SHALL be filtered by
warehouse when `warehouse` is given, as `stock_levels` does. Positions with reserved quantity but zero physical stock
SHALL be included with `on_hand` 0 and `available` 0.

#### Scenario: Position with reservation and stock
- **WHEN** `MAIN` has 10 `BOLT-M8` on hand and an active reservation holds 4 of them
- **THEN** `availability()` contains `Availability("MAIN", "BOLT-M8", on_hand=10, reserved=4, available=6)`

#### Scenario: Reserved position without stock
- **WHEN** `EAST` has 0 `BOLT-M8` on hand and an active reservation holds 1 of it
- **THEN** `availability()` contains `Availability("EAST", "BOLT-M8", on_hand=0, reserved=1, available=0)`

#### Scenario: Warehouse filter
- **WHEN** `availability("MAIN")` is called
- **THEN** only records with warehouse `MAIN` are returned

### Requirement: Sweep expired reservations
The system SHALL provide `sweep_expired()`, which finds every reservation whose evaluated status is `EXPIRED` at the
current clock time and that has not yet been reported by an earlier sweep. For each such reservation it SHALL write one
`RESERVE_EXPIRE` event with `order` and `expires` (the reservation's `expires_at`). Each reservation SHALL be reported at
most once. A reservation is identified by its own creation, not by its order: if an order's expired reservation is replaced
by a new reservation that also expires, the new reservation SHALL be reported separately. The method SHALL return the
`order_id` of each newly reported reservation, sorted by `expires_at` and then by `order_id`. The method SHALL NOT change
statuses, stock, or existing reservations, and SHALL NOT need to be called for expiry to take effect.

#### Scenario: Expired reservation is reported once
- **WHEN** an active reservation for `SO-1` expires and `sweep_expired()` is called twice
- **THEN** the first call writes one `RESERVE_EXPIRE` with `order=SO-1` and returns `["SO-1"]`
- **AND** the second call writes nothing and returns `[]`

#### Scenario: Ordering of reported reservations
- **WHEN** `SO-2` expires at `10:20` and `SO-1` expires at `10:20` and `SO-3` expires at `10:15`, and then `sweep_expired()` is called
- **THEN** the call returns `["SO-3", "SO-1", "SO-2"]` and writes three `RESERVE_EXPIRE` events in the same order

#### Scenario: Expired reservation replaced before the sweep is still reported
- **WHEN** `SO-1` expires, is reserved again before any sweep, and `sweep_expired()` is called
- **THEN** the expired reservation is reported with its own `expires` value, and the current reservation is not reported

#### Scenario: Replacement that expires is reported again
- **WHEN** `SO-1` expired and was reported by a sweep, `SO-1` was reserved again, the new reservation expired, and `sweep_expired()` is called
- **THEN** the call returns `["SO-1"]` and writes one `RESERVE_EXPIRE` with the expiry of the new reservation

#### Scenario: Active and confirmed reservations are not reported
- **WHEN** `sweep_expired()` is called and no reservation has passed `expires_at`
- **THEN** nothing is written and the result is `[]`

#### Scenario: Sweep does not change state
- **WHEN** `sweep_expired()` reports an expired reservation
- **THEN** its status stays as evaluated, `available` and `reserved` are unchanged, and stock is unchanged

## MODIFIED Requirements

### Requirement: Expiration by service clock
A reservation SHALL be `EXPIRED` at the moment `expires_at` is reached or passed, as observed through the
service clock. Expired reservations SHALL NOT count in `reserved` or `available`. Expiration SHALL NOT
write an event to the journal at the moment it happens and SHALL NOT change the stored state other than what the
clock implies. A `RESERVE_EXPIRE` event MAY be written later by `sweep_expired`, as specified below.

#### Scenario: Reservation expires
- **WHEN** the clock reaches `expires_at` of an active reservation
- **THEN** `get_reservation` returns status `EXPIRED`
- **AND** `available` and `reserved` no longer count its lines
- **AND** no event is written
