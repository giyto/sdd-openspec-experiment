# checkout-discounts Specification

## Purpose
Применение промокода при расчёте итогов и оформлении заказа: какие строки участвуют, как считаются скидка,
налог и доставка, как скидка раскладывается по строкам чека и как работают `quote`, `place_order` и `cancel`.

## Requirements

### Requirement: Participating lines
A promo code SHALL apply only to participating lines. A line participates when its category is not
`GIFT_CARD` and its category is not in the code's excluded categories. Non-participating lines
MUST have a discount of `0.00`. The base of the discount and of the minimum order amount is the sum of
participating lines before the discount, without shipping and tax.

#### Scenario: Gift card line is excluded
- **WHEN** a cart holds a gift card line of `1000.00` and a book line of `450.00`, and a `PERCENT` code of `10` is applied
- **THEN** the discount is `45.00`, the gift card line has discount `0.00`, and the book line has discount `45.00`

#### Scenario: Excluded category
- **WHEN** a code excludes `ELECTRONICS` and the cart holds a phone of `2500.00` and a T-shirt of `999.00`, with a `PERCENT` code of `10`
- **THEN** the discount is `99.90`, all of it on the T-shirt line

### Requirement: No participating lines
When the cart has no participating lines, the system SHALL raise `PromoConditionsError`, even if the
code has no minimum order amount.

#### Scenario: Only gift cards in the cart
- **WHEN** the cart holds only gift card lines and a promo code is applied
- **THEN** the system raises `PromoConditionsError`

### Requirement: Minimum order amount
A code with a minimum order amount SHALL apply only when the sum of participating lines before discount
is greater than or equal to that minimum. The comparison MUST exclude shipping and tax. A sum exactly equal
to the minimum qualifies.

#### Scenario: Exactly at the minimum
- **WHEN** a code has minimum `1000.00`, and participating lines sum to `1000.00`
- **THEN** the code applies

#### Scenario: Below the minimum
- **WHEN** a code has minimum `1000.00`, and participating lines sum to `999.99`
- **THEN** the system raises `PromoConditionsError`

#### Scenario: Minimum ignores gift cards
- **WHEN** a code has minimum `1000.00`, and the cart holds a gift card of `1000.00` and a book of `450.00`
- **THEN** the system raises `PromoConditionsError`

### Requirement: Discount amount
For a `PERCENT` code the discount SHALL be the participating sum multiplied by the percent value, divided
by 100, and rounded to kopecks with the project's commercial rounding (`ROUND_HALF_UP`). For a `FIXED` code the
discount SHALL be the fixed amount, but never more than the participating sum. The discount is always
non-negative.

#### Scenario: Percent rounding
- **WHEN** participating lines sum to `199.90` and the code is `PERCENT` of `15`
- **THEN** the discount is `29.99` (`199.90 × 0.15 = 29.985`, rounded half up)

#### Scenario: Fixed amount above the base
- **WHEN** participating lines sum to `300.00` and the code is `FIXED` of `500.00`
- **THEN** the discount is `300.00` and the total of the lines is not negative

### Requirement: Distribution of the discount across lines
The system SHALL distribute the order discount across participating lines so that the sum of line discounts
equals the order discount exactly. For each participating line, the base share is the order discount
multiplied by the line amount divided by the participating sum, rounded down to kopecks. The remaining
kopecks SHALL be given one kopeck at a time to the participating lines with the largest discarded remainder.
When remainders are equal, the line that appears earlier in the cart (first added) receives the kopeck.

#### Scenario: Tie on remainder goes to the earlier line
- **WHEN** a discount of `0.01` is distributed over two participating lines of `100.00` each
- **THEN** the first line receives `0.01` and the second line receives `0.00`

#### Scenario: Largest remainder wins over larger line
- **WHEN** a discount of `0.02` is distributed over participating lines of `1.00` (first in cart) and `2.00` (second in cart)
- **THEN** the base shares are `0.00` and `0.01`, the remaining kopeck goes to the first line (remainder `0.00666…` against `0.00333…`), and the line discounts are `0.01` and `0.01`

#### Scenario: Sum equals order discount
- **WHEN** any valid promo code is applied to any cart
- **THEN** the sum of line discounts equals the order discount exactly

### Requirement: Tax after discount
The tax of each line SHALL be computed from the line amount after its discount, at the rate of the line's
category, and rounded per line. The order tax is the sum of line taxes. Gift card lines remain untaxed.

#### Scenario: Book line tax after discount
- **WHEN** a book line of `450.00` gets discount `45.00` and the book category tax rate is 10%
- **THEN** the line tax is `40.50`

### Requirement: Shipping and free shipping threshold
Shipping SHALL NOT be reduced by a promo code. The free shipping threshold SHALL be compared with the goods
sum after the order discount, so that a discount can bring the order to the threshold. Shipping is not taxed.

#### Scenario: Discount reaches the free shipping threshold
- **WHEN** goods sum to `3100.00` before discount, the discount is `100.00`, and the threshold is `3000.00`
- **THEN** shipping is `0.00`

#### Scenario: Discount keeps goods below the threshold
- **WHEN** goods sum to `3100.00` before discount, the discount is `200.00`, and the threshold is `3000.00`
- **THEN** shipping is `299.00`

#### Scenario: Discount does not reduce shipping fee
- **WHEN** goods sum to `2500.00` before discount, the discount is `100.00`, and shipping applies
- **THEN** shipping is `299.00`

### Requirement: Order totals
The order total SHALL equal the subtotal of lines before discount, minus the order discount, plus shipping,
plus tax. `OrderTotal.discount` SHALL be `0.00` when no promo code applies.

#### Scenario: Total with discount
- **WHEN** subtotal is `2500.00`, discount `100.00`, shipping `299.00`, and tax `240.00`
- **THEN** total is `2939.00`

### Requirement: Calculation without promo code is unchanged
Calls without a promo code (`calculate_total(cart)`, `calculate_total(cart, shipping, tax)`, `quote(cart)`,
`place_order(cart)`, and calls where the promo code is `None`, an empty string, or only spaces) SHALL return
the same amounts as before this change, with `discount` equal to `0.00`.

#### Scenario: Blank code is no code
- **WHEN** `quote` is called with a promo code of `"   "`
- **THEN** the total equals the total without any code and no error is raised

### Requirement: Quote with promo code
`OrderService.quote(cart, promo_code)` SHALL resolve the code through the registry (existence, validity
period, usage limit) and apply the order conditions. It SHALL NOT change the usage count and SHALL NOT store
any order.

#### Scenario: Quote with valid code
- **WHEN** a valid `PERCENT` code of `10` is passed to `quote`
- **THEN** the returned total has the discount applied and the code's uses are unchanged

#### Scenario: Quote without a registry
- **WHEN** `OrderService` is created without a promo registry and `quote` is called with a non-blank code
- **THEN** the system raises `UnknownPromoCodeError`

### Requirement: Placing an order with promo code
`OrderService.place_order(cart, promo_code)` SHALL perform the same checks as `quote`. On success it SHALL
store an order whose `promo_code` is the normalized code and whose total includes the discount, and it SHALL
increase the usage count of that code by one. When any check fails, no order is stored and the usage count is
unchanged.

#### Scenario: Successful order consumes a use
- **WHEN** a code with `max_uses` of `2` is used to place an order
- **THEN** the stored order has `promo_code` equal to the normalized code and the code's uses are `1`

#### Scenario: Failed order does not consume a use
- **WHEN** a code with `max_uses` of `2` is used to place an order whose participating sum is below the minimum
- **THEN** the system raises `PromoConditionsError`, no order is stored, and the code's uses are `0`

#### Scenario: Order without code
- **WHEN** `place_order` is called without a promo code or with a blank code
- **THEN** the stored order has `promo_code` equal to `None`

### Requirement: Cancelling an order returns the promo use
`OrderService.cancel(order_id)` SHALL return the usage of the order's promo code, decreasing its count by one,
and the order SHALL keep its `promo_code`. An order without a promo code is cancelled as before.

#### Scenario: Cancellation restores the count
- **WHEN** an order with promo code `SUMMER10` is cancelled
- **THEN** the usage count of `SUMMER10` decreases by one

#### Scenario: Cancellation of an order without code
- **WHEN** an order without a promo code is cancelled
- **THEN** no usage count changes
