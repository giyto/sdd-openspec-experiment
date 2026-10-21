# promo-codes Specification

## Purpose
Промокоды магазина: процентные и фиксированные коды со сроком действия и лимитом использований, которые
проверяются при расчёте и оформлении заказа. Код, введённый покупателем, нормализуется так же, как
другие коды, которые вводят люди.

## Requirements

### Requirement: Promo code definition
The system SHALL represent a promo code as an immutable `PromoCode` with a code, a discount kind
(`PERCENT` or `FIXED`), a value, an optional minimum order amount (default `0.00`), an optional start and
end of validity, an optional maximum number of uses, and a set of excluded categories (default empty).
The system MUST reject a `PromoCode` that violates these invariants with a `ValidationError`:
- the code is empty after removing surrounding spaces;
- a `PERCENT` value is not in the interval `(0, 100]`;
- a `FIXED` value is not a positive amount in rubles with at most two fractional digits;
- the value or the minimum order amount is not a `Decimal`, or the minimum is negative or has more than two fractional digits;
- `max_uses` is neither `None` nor an integer `>= 1`;
- `starts_at` or `expires_at` is naive (has no timezone), or `starts_at` is not earlier than `expires_at` when both are set;
- an excluded category is not a `Category`.

#### Scenario: Code is normalized
- **WHEN** a promo code is created with the code `"  summer10 "`
- **THEN** its code is `"SUMMER10"`

#### Scenario: Percent value out of range
- **WHEN** a promo code of kind `PERCENT` is created with value `0` or `150`
- **THEN** the system raises `ValidationError`

#### Scenario: Naive validity bound
- **WHEN** a promo code is created with `starts_at` set to a naive datetime
- **THEN** the system raises `ValidationError`

### Requirement: Promo code lookup is case- and space-insensitive
The system SHALL look up a code by its normalized form: surrounding spaces are removed and letters are
upper-cased, the same way as when the code was added. The system MUST treat codes as case-insensitive
and space-insensitive when they are added to the registry and when they are resolved.

#### Scenario: Lookup with different spacing and case
- **WHEN** a promo code `"SUMMER10"` is registered and the customer enters `" summer10\t"`
- **THEN** the registry resolves it to the `SUMMER10` promo code

#### Scenario: Duplicate code
- **WHEN** a promo code is added whose normalized code is already registered
- **THEN** the system raises `ValidationError` and the registry is unchanged

### Requirement: Unknown promo code
The system SHALL raise `UnknownPromoCodeError` when a code is not registered. This includes an empty
code and a code that consists only of spaces, since no registered code can be empty. Unknown codes
MUST be reported before the validity and limit checks are made.

#### Scenario: Code is not registered
- **WHEN** the customer resolves the code `"NOPE"` that is not registered
- **THEN** the system raises `UnknownPromoCodeError`

#### Scenario: Empty code resolution
- **WHEN** the code passed to `resolve` is `""`
- **THEN** the system raises `UnknownPromoCodeError`

#### Scenario: Uses of an unknown code
- **WHEN** `uses` is asked for a code that is not registered
- **THEN** the system raises `UnknownPromoCodeError`

### Requirement: Validity period
The system SHALL treat a promo code as valid at a moment `t` when `starts_at <= t < expires_at`, where a
`None` bound means no limit on that side. The moment `t` is always taken from the injected clock, never
from the system time directly. When the code is not valid at the current time, the system SHALL raise
`PromoExpiredError`. This applies both to a code that has not started yet and to a code that has already
expired.

#### Scenario: Code before its start
- **WHEN** the current time is earlier than `starts_at` of a registered code
- **THEN** resolving the code raises `PromoExpiredError`

#### Scenario: Code at its end
- **WHEN** the current time equals `expires_at` of a registered code
- **THEN** resolving the code raises `PromoExpiredError`

#### Scenario: Code at its start
- **WHEN** the current time equals `starts_at` of a registered code and the code has no use limit exhausted
- **THEN** the code resolves successfully

### Requirement: Usage limit
The system SHALL count a use of a promo code only when an order with that code is successfully placed.
Quoting a total, calculating a total, and failed attempts to place an order MUST NOT change the count.
A code with `max_uses` set SHALL NOT resolve once its count has reached `max_uses`; in that case the
system raises `PromoConditionsError`. A code with `max_uses` of `None` has no limit.

#### Scenario: Quote does not consume a use
- **WHEN** a code with `max_uses` of `1` is used in a quote
- **THEN** `uses` for that code is still `0`

#### Scenario: Exhausted code
- **WHEN** a code with `max_uses` of `1` has one successful order and the customer resolves it again
- **THEN** the system raises `PromoConditionsError`

#### Scenario: Unlimited code
- **WHEN** a code with `max_uses` of `None` is used in many orders
- **THEN** every resolve succeeds

### Requirement: Return of a use on cancellation
The system SHALL return the use of a promo code when an order that used it is cancelled. The count of
that code decreases by one and never becomes negative. The cancelled order keeps its promo code.

#### Scenario: Cancelled order frees a use
- **WHEN** a code with `max_uses` of `1` was used by an order that is then cancelled
- **THEN** the count for that code is `0` and the code resolves successfully again

### Requirement: Resolution check order
The registry SHALL check a code in this order: the code exists, the code is valid at the current time,
the usage limit is not exhausted. The first failed check determines the error. Order conditions (minimum
amount, eligible lines) are checked by the pricing rules, as described in the `checkout-discounts`
capability.

#### Scenario: Expired and exhausted code
- **WHEN** a code is both expired and has its usage limit exhausted
- **THEN** resolving it raises `PromoExpiredError`
