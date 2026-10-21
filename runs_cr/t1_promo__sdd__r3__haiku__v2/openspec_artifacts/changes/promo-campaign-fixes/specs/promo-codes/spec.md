## MODIFIED Requirements

### Requirement: Promo code definition
The system SHALL represent a promo code as an immutable `PromoCode` with a code, a discount kind
(`PERCENT`, `FIXED` or `FREE_SHIPPING`), a value, an optional minimum order amount (default `0.00`), an optional
start and end of validity, an optional maximum number of uses, an optional maximum number of uses per customer,
an optional ceiling of a percent discount (`max_discount`), and a set of excluded categories (default empty).
The system MUST reject a `PromoCode` that violates these invariants with a `ValidationError`:
- the code is empty after removing surrounding spaces;
- a `PERCENT` value is not in the interval `(0, 100]`;
- a `FIXED` value is not a positive amount in rubles with at most two fractional digits;
- a `FREE_SHIPPING` value is not exactly `Decimal("0")`;
- the value or the minimum order amount is not a `Decimal`, or the minimum is negative or has more than two fractional digits;
- `max_uses` is neither `None` nor an integer `>= 1`;
- `max_uses_per_customer` is neither `None` nor an integer `>= 1`;
- `max_discount` is set for a kind other than `PERCENT`, or is not a positive `Decimal` amount in rubles with at most two fractional digits;
- `starts_at` or `expires_at` is naive (has no timezone), or `starts_at` is not earlier than `expires_at` when both are set;
- an excluded category is not a `Category`.

#### Scenario: Code is normalized
- **WHEN** a promo code is created with the code `"  summer10 "`
- **THEN** its code is `"SUMMER10"`

#### Scenario: Percent value out of range
- **WHEN** a promo code of kind `PERCENT` is created with value `0` or `150`
- **THEN** the system raises `ValidationError`

#### Scenario: Free shipping code with a non-zero value
- **WHEN** a promo code of kind `FREE_SHIPPING` is created with value `Decimal("100")`
- **THEN** the system raises `ValidationError`

#### Scenario: Free shipping code with zero value
- **WHEN** a promo code of kind `FREE_SHIPPING` is created with value `Decimal("0")`
- **THEN** the promo code is created

#### Scenario: Ceiling on a fixed code
- **WHEN** a promo code of kind `FIXED` is created with `max_discount` set to `Decimal("100.00")`
- **THEN** the system raises `ValidationError`

#### Scenario: Zero ceiling on a percent code
- **WHEN** a promo code of kind `PERCENT` is created with `max_discount` set to `Decimal("0")`
- **THEN** the system raises `ValidationError`

#### Scenario: Per-customer limit below one
- **WHEN** a promo code is created with `max_uses_per_customer` of `0`
- **THEN** the system raises `ValidationError`

#### Scenario: Naive validity bound
- **WHEN** a promo code is created with `starts_at` set to a naive datetime
- **THEN** the system raises `ValidationError`

### Requirement: Usage limit
The system SHALL count a use of a promo code only when an order with that code is successfully placed.
Quoting a total, calculating a total, and failed attempts to place an order MUST NOT change the count.
A code with `max_uses` set SHALL NOT resolve once its count has reached `max_uses`; in that case the
system raises `PromoConditionsError`. A code with `max_uses` of `None` has no limit. The per-customer count
is checked by the requirement "Per-customer usage limit" and does not replace this total count.

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
The system SHALL return the use of a promo code when an order that used it is cancelled, but only when the
cancellation happens strictly less than 24 hours after the order was placed. The interval is measured between
the order's `created_at` and the current moment of the injected clock of the order service. A cancellation at
exactly 24 hours or later MUST NOT return the use: the use is spent. When the use is returned, the total count
of that code decreases by one and never becomes negative, and the per-customer count of the order's customer
decreases by one when the order has a customer. A cancelled order keeps its promo code and its customer.

#### Scenario: Cancelled order frees a use
- **WHEN** a code with `max_uses` of `1` was used by an order that is cancelled 23 hours 59 minutes after it was placed
- **THEN** the count for that code is `0` and the code resolves successfully again

#### Scenario: Cancellation exactly at 24 hours spends the use
- **WHEN** a code with `max_uses` of `1` was used by an order that is cancelled exactly 24 hours after it was placed
- **THEN** the count for that code stays `1`, the order is cancelled, and the code does not resolve

#### Scenario: Late cancellation spends the use
- **WHEN** a code was used by an order that is cancelled 3 days after it was placed
- **THEN** the count for that code is unchanged and the order keeps its promo code

### Requirement: Resolution check order
The registry SHALL check a code in this order: the code exists, the code is valid at the current time,
the total usage limit is not exhausted, the per-customer usage limit is not exhausted. The first failed check
determines the error. Order conditions (minimum amount, eligible lines, percent ceiling, free shipping) are
checked by the pricing rules, as described in the `checkout-discounts` capability.

#### Scenario: Expired and exhausted code
- **WHEN** a code is both expired and has its usage limit exhausted
- **THEN** resolving it raises `PromoExpiredError`

## ADDED Requirements

### Requirement: Per-customer usage limit
The system SHALL limit the uses of a promo code per customer when the code has `max_uses_per_customer` set. The
customer is identified by `customer_id`, an internal account identifier that the system compares exactly as it is
given, without normalization. `customer_id` `None` means that no customer is known. The registry SHALL accept
`customer_id` in `resolve(code, customer_id=None)` and `uses(code, customer_id=None)`. Each successfully placed order
with a `customer_id` SHALL count one use for that customer and that code, whether or not the code has a per-customer
limit. `uses(code, customer_id)` returns the number of uses of that code by that customer; `uses(code)` without a
customer returns the total count of the code. The system MUST NOT apply a code with `max_uses_per_customer` set when
`customer_id` is `None`: it raises `PromoConditionsError`. When the customer has already used the code
`max_uses_per_customer` times, the system raises `PromoConditionsError`. A code with `max_uses_per_customer` of `None`
has no per-customer limit.

#### Scenario: Code with a per-customer limit and no customer
- **WHEN** a code with `max_uses_per_customer` of `1` is resolved without `customer_id`
- **THEN** the system raises `PromoConditionsError`

#### Scenario: Customer reached the limit
- **WHEN** a code with `max_uses_per_customer` of `1` was used by the order of customer `"c-1"`, and `"c-1"` resolves it again
- **THEN** the system raises `PromoConditionsError`

#### Scenario: Other customer is not limited
- **WHEN** a code with `max_uses_per_customer` of `1` was used by the order of customer `"c-1"`, and `"c-2"` resolves it
- **THEN** the code resolves successfully

#### Scenario: Customer identifiers are compared as given
- **WHEN** a customer `"C-1"` has used a code and the customer `"c-1"` resolves it
- **THEN** the code resolves successfully for `"c-1"`, because the identifiers differ

#### Scenario: Per-customer count with total count
- **WHEN** a code without `max_uses` was used by customer `"c-1"` twice and by customer `"c-2"` once
- **THEN** `uses(code, "c-1")` is `2`, `uses(code, "c-2")` is `1`, and `uses(code)` is `3`

#### Scenario: Unknown code in a per-customer count
- **WHEN** `uses` is asked with a `customer_id` for a code that is not registered
- **THEN** the system raises `UnknownPromoCodeError`
