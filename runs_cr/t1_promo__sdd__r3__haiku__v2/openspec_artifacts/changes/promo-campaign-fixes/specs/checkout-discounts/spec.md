## MODIFIED Requirements

### Requirement: Discount amount
For a `PERCENT` code the discount SHALL be the participating sum multiplied by the percent value, divided
by 100, and rounded to kopecks with the project's commercial rounding (`ROUND_HALF_UP`). If the code has a
`max_discount`, the percent discount SHALL NOT exceed it. For a `FIXED` code the discount SHALL be the fixed
amount, but never more than 50 % of the participating sum; this 50 % cap is calculated and rounded to kopecks with
`ROUND_HALF_UP` in the same way as any money amount. For a `FREE_SHIPPING` code the order discount SHALL be
`0.00`. The discount is always non-negative.

#### Scenario: Percent rounding
- **WHEN** participating lines sum to `199.90` and the code is `PERCENT` of `15`
- **THEN** the discount is `29.99` (`199.90 × 0.15 = 29.985`, rounded half up)

#### Scenario: Fixed amount above the base
- **WHEN** participating lines sum to `300.00` and the code is `FIXED` of `500.00`
- **THEN** the discount is `150.00` (50 % of `300.00`), and the total of the lines is not negative

#### Scenario: Fixed amount cap is rounded half up
- **WHEN** participating lines sum to `999.99` and the code is `FIXED` of `1000.00`
- **THEN** the discount is `500.00` (`999.99 × 0.5 = 499.995`, rounded half up)

#### Scenario: Fixed amount below the cap
- **WHEN** participating lines sum to `1000.00` and the code is `FIXED` of `300.00`
- **THEN** the discount is `300.00`

#### Scenario: Percent discount reaches the ceiling
- **WHEN** participating lines sum to `2000.00` and the code is `PERCENT` of `10` with `max_discount` of `150.00`
- **THEN** the discount is `150.00` (`200.00` before the ceiling)

#### Scenario: Percent discount below the ceiling
- **WHEN** participating lines sum to `1000.00` and the code is `PERCENT` of `10` with `max_discount` of `150.00`
- **THEN** the discount is `100.00`

#### Scenario: Free shipping code gives no goods discount
- **WHEN** a `FREE_SHIPPING` code is applied to a cart with participating lines of `1000.00`
- **THEN** the order discount is `0.00` and every line has discount `0.00`

### Requirement: Distribution of the discount across lines
The system SHALL distribute the order discount across participating lines so that the sum of line discounts
equals the order discount exactly. For each participating line, the base share is the order discount
multiplied by the line amount divided by the participating sum, rounded down to kopecks. The remaining
kopecks SHALL be given one kopeck at a time to the participating lines with the largest discarded remainder.
When remainders are equal, the line with the larger line amount receives the kopeck. When the remainders and the
line amounts are equal, the line that appears earlier in the cart (first added) receives the kopeck.

#### Scenario: Tie on remainder goes to the earlier line
- **WHEN** a discount of `0.01` is distributed over two participating lines of `100.00` each
- **THEN** the first line receives `0.01` and the second line receives `0.00`

#### Scenario: Tie on remainder goes to the larger line
- **WHEN** a discount of `0.02` is distributed over participating lines of `1.00` (first in cart) and `3.00` (second in cart)
- **THEN** the base shares are `0.00` and `0.01`, both remainders are `0.005`, the remaining kopeck goes to the second line (larger amount), and the line discounts are `0.00` and `0.02`

#### Scenario: Largest remainder wins over larger line
- **WHEN** a discount of `0.02` is distributed over participating lines of `1.00` (first in cart) and `2.00` (second in cart)
- **THEN** the base shares are `0.00` and `0.01`, the remaining kopeck goes to the first line (remainder `0.00666…` against `0.00333…`), and the line discounts are `0.01` and `0.01`

#### Scenario: Sum equals order discount
- **WHEN** any valid promo code is applied to any cart
- **THEN** the sum of line discounts equals the order discount exactly

### Requirement: Shipping and free shipping threshold
Shipping SHALL NOT be reduced by a `PERCENT` or `FIXED` promo code. The free shipping threshold SHALL be compared
with the sum of participating and non-participating lines before the order discount (the goods sum before discount),
so that the discount does not change whether the threshold is reached. A `FREE_SHIPPING` promo code SHALL set shipping
to `0.00` for an order that needs delivery. Shipping is not taxed.

#### Scenario: Discount reaches the free shipping threshold
- **WHEN** goods sum to `3100.00` before discount, the discount is `200.00`, and the threshold is `3000.00`
- **THEN** shipping is `0.00`

#### Scenario: Discount keeps goods below the threshold
- **WHEN** goods sum to `2990.00` before discount, the discount is `100.00`, and the threshold is `3000.00`
- **THEN** shipping is `299.00`

#### Scenario: Discount does not reduce shipping fee
- **WHEN** goods sum to `2500.00` before discount, the discount is `100.00`, and shipping applies
- **THEN** shipping is `299.00`

#### Scenario: Free shipping code sets shipping to zero
- **WHEN** goods sum to `2500.00` before discount, a `FREE_SHIPPING` code is applied, and shipping applies
- **THEN** shipping is `0.00`

### Requirement: Order totals
The order total SHALL equal the subtotal of lines before discount, minus the order discount, plus shipping,
plus tax. `OrderTotal.discount` SHALL be `0.00` when no promo code applies. `OrderTotal.shipping_discount` SHALL be the
shipping cost the customer saved because of a promo code: for a `FREE_SHIPPING` code it is the shipping cost that
would have applied without the code, and it is `0.00` for every other case, including a code of another kind, no
code, and a cart whose shipping was already zero.

#### Scenario: Total with discount
- **WHEN** subtotal is `2500.00`, discount `100.00`, shipping `299.00`, and tax `240.00`
- **THEN** total is `2939.00`

#### Scenario: Shipping saving of a free shipping code
- **WHEN** a `FREE_SHIPPING` code is applied to a cart whose shipping would be `299.00`
- **THEN** `shipping` is `0.00`, `shipping_discount` is `299.00`, and `discount` is `0.00`

#### Scenario: Free shipping code with no saving
- **WHEN** a `FREE_SHIPPING` code is applied to a cart whose goods sum before discount reaches the threshold
- **THEN** `shipping_discount` is `0.00`

#### Scenario: Other code kinds give no shipping saving
- **WHEN** a `PERCENT` code is applied to a cart whose shipping would be `299.00`
- **THEN** `shipping_discount` is `0.00`

### Requirement: Quote with promo code
`OrderService.quote(cart, promo_code, *, customer_id=None)` SHALL resolve the code through the registry (existence,
validity period, usage limits, including the per-customer limit for the given `customer_id`) and apply the order
conditions. It SHALL NOT change the usage count and SHALL NOT store any order.

#### Scenario: Quote with valid code
- **WHEN** a valid `PERCENT` code of `10` is passed to `quote`
- **THEN** the returned total has the discount applied and the code's uses are unchanged

#### Scenario: Quote without a registry
- **WHEN** `OrderService` is created without a promo registry and `quote` is called with a non-blank code
- **THEN** the system raises `UnknownPromoCodeError`

#### Scenario: Quote with a per-customer limit and no customer
- **WHEN** a code with `max_uses_per_customer` of `1` is passed to `quote` without `customer_id`
- **THEN** the system raises `PromoConditionsError`

#### Scenario: Quote for a customer who reached the limit
- **WHEN** a code with `max_uses_per_customer` of `1` was used by customer `"c-1"` and `quote` is called with `customer_id` `"c-1"`
- **THEN** the system raises `PromoConditionsError` and the uses are unchanged

### Requirement: Placing an order with promo code
`OrderService.place_order(cart, promo_code, *, customer_id=None)` SHALL perform the same checks as `quote`. On success
it SHALL store an order whose `promo_code` is the normalized code, whose `customer_id` is the given `customer_id`, and
whose total includes the discount, and it SHALL increase the usage count of that code by one, and, when `customer_id`
is given, the per-customer count of that customer by one. When any check fails, no order is stored and the usage counts
are unchanged.

#### Scenario: Successful order consumes a use
- **WHEN** a code with `max_uses` of `2` is used to place an order
- **THEN** the stored order has `promo_code` equal to the normalized code and the code's uses are `1`

#### Scenario: Failed order does not consume a use
- **WHEN** a code with `max_uses` of `2` is used to place an order whose participating sum is below the minimum
- **THEN** the system raises `PromoConditionsError`, no order is stored, and the code's uses are `0`

#### Scenario: Order without code
- **WHEN** `place_order` is called without a promo code or with a blank code
- **THEN** the stored order has `promo_code` equal to `None`

#### Scenario: Order remembers the customer
- **WHEN** `place_order` is called with `customer_id` `"c-1"` and a code with `max_uses_per_customer` of `2`
- **THEN** the stored order has `customer_id` equal to `"c-1"` and the code's uses for `"c-1"` are `1`

#### Scenario: Order without customer
- **WHEN** `place_order` is called without `customer_id`
- **THEN** the stored order has `customer_id` equal to `None`

### Requirement: Cancelling an order returns the promo use
`OrderService.cancel(order_id)` SHALL return the usage of the order's promo code, decreasing its count by one, only when
the cancellation happens strictly less than 24 hours after the order's `created_at`, measured with the service clock.
Otherwise the use is spent and no count changes. The order SHALL keep its `promo_code` and its `customer_id`. An order
without a promo code is cancelled as before.

#### Scenario: Cancellation restores the count
- **WHEN** an order with promo code `SUMMER10` is cancelled 2 hours after it was placed
- **THEN** the usage count of `SUMMER10` decreases by one

#### Scenario: Cancellation after 24 hours keeps the count
- **WHEN** an order with promo code `SUMMER10` is cancelled 25 hours after it was placed
- **THEN** the usage count of `SUMMER10` does not change and the order is cancelled

#### Scenario: Cancellation of an order without code
- **WHEN** an order without a promo code is cancelled
- **THEN** no usage count changes

## ADDED Requirements

### Requirement: Free shipping promo code
A `FREE_SHIPPING` promo code SHALL NOT give a discount on goods, and its value SHALL be `Decimal("0")`. It SHALL apply
to the cart under the same order conditions as other codes: participating lines (at least one), minimum order amount, and
the code's validity and usage limits. Its effect is limited to shipping, as described in "Shipping and free shipping
threshold" and "Order totals". The threshold and shipping rules for other codes are unchanged.

#### Scenario: Free shipping code on goods
- **WHEN** a `FREE_SHIPPING` code is applied to a cart with a book line of `450.00`
- **THEN** the book line has discount `0.00` and the tax of the line is computed from `450.00`

#### Scenario: Free shipping code on a cart without participating lines
- **WHEN** a `FREE_SHIPPING` code is applied to a cart that holds only gift cards
- **THEN** the system raises `PromoConditionsError`

#### Scenario: Free shipping code below the minimum order amount
- **WHEN** a `FREE_SHIPPING` code has minimum `1000.00` and participating lines sum to `999.99`
- **THEN** the system raises `PromoConditionsError`
