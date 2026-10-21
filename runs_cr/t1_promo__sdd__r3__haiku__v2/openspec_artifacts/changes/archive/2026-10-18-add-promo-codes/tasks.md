## 1. Errors and promo model

- [x] 1.1 Add `PromoError(ShopError)` and three independent subclasses `UnknownPromoCodeError`, `PromoExpiredError`, `PromoConditionsError` to `shop/errors.py`; verify `issubclass` checks and `except ShopError` catch all of them in a new test file `tests/test_promo_errors.py`
- [x] 1.2 Create `shop/promo.py` with `DiscountKind` and frozen `PromoCode` (normalized code via `normalize_key`, invariants in `__post_init__`); verify each invariant from `specs/promo-codes` "Promo code definition" with tests in `tests/test_promo_code.py`
- [x] 1.3 Add `normalize_promo_input` (None and blank -> `None`, otherwise `normalize_key`); verify with tests for `None`, `""`, `"   "`, `" summer10 "` in `tests/test_promo_code.py`

## 2. Promo registry

- [x] 2.1 Implement `PromoRegistry(clock)` with `add` (duplicate -> `ValidationError`), `resolve` (existence, validity `[starts_at, expires_at)` from the clock, limit -> `PromoConditionsError`) and `uses` (unknown -> `UnknownPromoCodeError`); verify the scenarios of `specs/promo-codes` in `tests/test_promo_registry.py`, including resolve order and `resolve("")`
- [x] 2.2 Add `record_use(code)` and `release_use(code)` (floor at zero) to the registry; verify usage counting, release, and that failed resolves do not change counts in `tests/test_promo_registry.py`

## 3. Discount calculation in pricing

- [x] 3.1 Add `LineTotal.discount` and `OrderTotal.discount` with default `Decimal("0.00")` at the end of the dataclasses; verify `calculate_total(cart)` returns unchanged amounts with zero discount by running the existing `tests/test_pricing.py` unchanged
- [x] 3.2 Implement participating-line selection and the minimum/no-lines checks in `calculate_total(..., *, promo=None)` raising `PromoConditionsError`; verify the scenarios of "Participating lines", "No participating lines", "Minimum order amount" in `tests/test_promo_pricing.py`
- [x] 3.3 Implement the discount amount (percent with `ROUND_HALF_UP`, fixed capped at the base) in `shop/pricing.py`; verify the scenarios of "Discount amount" including `199.90 × 15% = 29.99`
- [x] 3.4 Implement the integer-kopeck distribution of the discount across participating lines (largest remainder, ties to earlier cart line); verify the "Distribution of the discount across lines" scenarios and a property check that line discounts always sum to the order discount for a range of carts in `tests/test_promo_pricing.py`
- [x] 3.5 Compute line tax on `amount - discount`, shipping threshold on `subtotal - discount`, and `total = subtotal - discount + shipping + tax`; verify the "Tax after discount", "Shipping and free shipping threshold" and "Order totals" scenarios in `tests/test_promo_pricing.py`

## 4. Order service integration

- [x] 4.1 Add `promos: PromoRegistry | None = None` to `OrderService` and the `promo_code` parameter to `quote`; blank code -> no code, non-blank code without registry -> `UnknownPromoCodeError`; verify with `tests/test_promo_orders.py`
- [x] 4.2 Add `promo_code` to `place_order`: resolve, price, store the order with the normalized code, then `record_use`; verify that a successful order increments uses and a failed order (below minimum, expired, exhausted) stores nothing and leaves counts unchanged in `tests/test_promo_orders.py`
- [x] 4.3 Add `Order.promo_code: str | None = None` and return the use in `cancel` via `release_use` (skipped when the order has no code); verify a cancelled order frees one use and keeps its code in `tests/test_promo_orders.py`

## 5. Regression and validation

- [x] 5.1 Run the full existing suite with `python -m pytest -q` and verify all previously passing tests still pass without edits to existing test files
- [x] 5.2 Verify that `shop/cli.py` and `shop/reports.py` are unchanged (`git diff --stat -- shop/cli.py shop/reports.py` is empty) and that no new dependency was added
- [x] 5.3 Run `openspec validate add-promo-codes --strict` and verify it reports no errors
