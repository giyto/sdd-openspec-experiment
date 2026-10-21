"""Acceptance tests for promo codes (ticket t1_promo).

New names are imported inside the tests so that the backward compatibility tests
(test_API_*) can run against a code base without promo support.
"""

import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shop.catalog import Category, Product
from shop.errors import ShopError, ValidationError
from shop.orders import OrderService, OrderStore
from shop.pricing import ShippingPolicy, TaxPolicy, calculate_total

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)  # same moment as the clock fixture

D = Decimal


def _promo(code="SUMMER10", kind="PERCENT", value="10", **kwargs):
    from shop.promo import DiscountKind, PromoCode

    return PromoCode(code=code, kind=getattr(DiscountKind, kind), value=D(value), **kwargs)


def _registry(clock, *promos):
    from shop.promo import PromoRegistry

    registry = PromoRegistry(clock)
    for promo in promos:
        registry.add(promo)
    return registry


def _errors():
    from shop import errors

    return errors


def _product(sku, price, category=Category.ELECTRONICS):
    return Product(sku, sku.title(), D(price), category)


# --------------------------------------------------------------------------- API


def test_API_calculate_total_positional_arguments(p, make_cart):
    cart = make_cart(p["laptop"], p["book"])
    total = calculate_total(cart, ShippingPolicy(free_threshold=None), TaxPolicy())
    assert total.subtotal == D("3100.00")
    assert total.tax == D("560.00")
    assert total.shipping == D("299.00")
    assert total.total == D("3959.00")


def test_API_calculate_total_old_call_values(p, make_cart):
    cart = make_cart(p["laptop"], p["book"], p["gift"])
    total = calculate_total(cart)
    assert [line.tax for line in total.lines] == [D("500.00"), D("60.00"), D("0.00")]
    assert total.shipping == D("0.00")
    assert total.total == D("4660.00")


def test_API_order_service_old_usage(p, make_cart, clock):
    service = OrderService(OrderStore(), clock=clock, shipping=None, tax=None)
    cart = make_cart(p["book"])
    assert service.quote(cart).total == D("959.00")
    order = service.place_order(cart)
    assert order.order_id == "ORD-000001"
    assert order.created_at == NOW
    assert order.total.total == D("959.00")


# --------------------------------------------------------------------------- R01


def test_R01_no_promo_means_zero_discount(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"]))
    assert total.discount == D("0.00")
    assert [line.discount for line in total.lines] == [D("0.00"), D("0.00")]
    assert total.total == total.subtotal + total.shipping + total.tax


def test_R01_promo_is_optional_keyword_only():
    param = inspect.signature(calculate_total).parameters["promo"]
    assert param.kind is inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_R01_place_order_without_code_with_registry(p, make_cart, clock):
    registry = _registry(clock, _promo())
    service = OrderService(clock=clock, promos=registry)
    order = service.place_order(make_cart(p["book"]))
    assert order.promo_code is None
    assert order.total.discount == D("0.00")
    assert order.total.total == D("959.00")
    assert registry.uses("SUMMER10") == 0


# --------------------------------------------------------------------------- R02


def test_R02_code_is_normalized_on_creation():
    assert _promo(code="  summer10 ").code == "SUMMER10"


def test_R02_percent_must_be_in_range():
    assert _promo(value="100").value == D("100")
    for bad in ("0", "-5", "100.01"):
        with pytest.raises(ValidationError):
            _promo(value=bad)


def test_R02_fixed_must_be_positive():
    with pytest.raises(ValidationError):
        _promo(kind="FIXED", value="0")
    with pytest.raises(ValidationError):
        _promo(kind="FIXED", value="-100")


def test_R02_invalid_code_window_and_uses():
    with pytest.raises(ValidationError):
        _promo(code="   ")
    with pytest.raises(ValidationError):
        _promo(starts_at=NOW, expires_at=NOW)
    with pytest.raises(ValidationError):
        _promo(starts_at=NOW, expires_at=NOW - timedelta(days=1))
    with pytest.raises(ValidationError):
        _promo(max_uses=0)


# --------------------------------------------------------------------------- R03


def test_R03_percent_of_qualifying_subtotal(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"], p["gift"]), promo=_promo())
    assert total.discount == D("310.00")
    assert total.subtotal == D("4100.00")


def test_R03_percent_rounds_half_up(p, make_cart):
    total = calculate_total(make_cart(p["tea"]), promo=_promo())
    # 10 % of 12.25 = 1.225 -> 1.23 (banker's rounding would give 1.22)
    assert total.discount == D("1.23")
    assert total.lines[0].discount == D("1.23")


def test_R03_fractional_percent(p, make_cart):
    total = calculate_total(make_cart(p["book"], p["tea"]), promo=_promo(value="12.5"))
    # 612.25 * 12.5 % = 76.53125
    assert total.discount == D("76.53")


def test_R03_percent_of_sum_not_sum_of_rounded_lines(make_cart):
    cart = make_cart(_product("A-1", "1.05"), _product("B-1", "1.05"), _product("C-1", "1.05"))
    total = calculate_total(cart, promo=_promo())
    # 10 % of 3.15 = 0.315 -> 0.32; rounding every line (0.105 -> 0.11) would give 0.33
    assert total.discount == D("0.32")
    assert [line.discount for line in total.lines] == [D("0.11"), D("0.11"), D("0.10")]


# --------------------------------------------------------------------------- R04


def test_R04_fixed_discount(p, make_cart):
    total = calculate_total(make_cart(p["laptop"]), promo=_promo(kind="FIXED", value="500"))
    assert total.discount == D("500.00")
    assert total.tax == D("400.00")
    assert total.shipping == D("299.00")
    assert total.total == D("2699.00")


def test_R04_fixed_capped_by_qualifying_lines(p, make_cart):
    total = calculate_total(make_cart(p["book"], p["gift"]), promo=_promo(kind="FIXED", value="1000"))
    assert total.discount == D("600.00")
    assert [line.discount for line in total.lines] == [D("600.00"), D("0.00")]
    assert total.total == D("1299.00")


def test_R04_hundred_percent_leaves_gift_cards_paid(p, make_cart):
    total = calculate_total(make_cart(p["gift"], p["tea"]), promo=_promo(value="100"))
    assert total.discount == D("12.25")
    assert total.tax == D("0.00")
    assert total.total == D("1299.00")


# --------------------------------------------------------------------------- R05


def test_R05_gift_cards_never_discounted(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["gift"]), promo=_promo())
    assert total.discount == D("250.00")
    assert [line.discount for line in total.lines] == [D("250.00"), D("0.00")]


def test_R05_code_specific_excluded_categories(p, make_cart):
    promo = _promo(excluded_categories=frozenset({Category.BOOKS}))
    total = calculate_total(make_cart(p["book"], p["laptop"], p["gift"]), promo=promo)
    assert total.discount == D("250.00")
    assert [line.discount for line in total.lines] == [D("0.00"), D("250.00"), D("0.00")]


def test_R05_excluded_lines_keep_full_tax(p, make_cart):
    promo = _promo(excluded_categories=frozenset({Category.BOOKS}))
    total = calculate_total(make_cart(p["book"], p["laptop"]), promo=promo)
    assert [line.tax for line in total.lines] == [D("60.00"), D("450.00")]


# --------------------------------------------------------------------------- R06


def test_R06_min_order_counts_only_qualifying_lines(p, make_cart):
    errors = _errors()
    promo = _promo(min_order_amount=D("1000"))
    with pytest.raises(errors.PromoConditionsError):
        calculate_total(make_cart(p["book"], p["gift"]), promo=promo)


def test_R06_min_order_ignores_code_excluded_categories(p, make_cart):
    errors = _errors()
    promo = _promo(min_order_amount=D("1000"), excluded_categories=frozenset({Category.ELECTRONICS}))
    with pytest.raises(errors.PromoConditionsError):
        calculate_total(make_cart(p["laptop"], p["book"]), promo=promo)


def test_R06_min_order_is_inclusive_and_before_discount(p, make_cart):
    cart = make_cart(p["laptop"], p["book"])
    assert calculate_total(cart, promo=_promo(min_order_amount=D("3100"))).discount == D("310.00")
    fixed = _promo(kind="FIXED", value="500", min_order_amount=D("3000"))
    assert calculate_total(cart, promo=fixed).discount == D("500.00")


def test_R06_min_order_without_tax_and_shipping(p, make_cart):
    errors = _errors()
    # 600 of goods, but 660 with tax and 959 with shipping
    with pytest.raises(errors.PromoConditionsError):
        calculate_total(make_cart(p["book"]), promo=_promo(min_order_amount=D("650")))


def test_R06_no_qualifying_lines(p, make_cart):
    errors = _errors()
    with pytest.raises(errors.PromoConditionsError):
        calculate_total(make_cart(p["gift"]), promo=_promo())
    with pytest.raises(errors.PromoConditionsError):
        calculate_total(
            make_cart(p["book"]), promo=_promo(excluded_categories=frozenset({Category.BOOKS}))
        )


# --------------------------------------------------------------------------- R07


def _windowed():
    return _promo(starts_at=NOW, expires_at=NOW + timedelta(days=1))


def test_R07_start_is_inclusive(clock):
    registry = _registry(clock, _windowed())
    assert registry.resolve("SUMMER10").code == "SUMMER10"


def test_R07_not_started_is_expired_error(clock):
    errors = _errors()
    clock.set(NOW - timedelta(seconds=1))
    registry = _registry(clock, _windowed())
    with pytest.raises(errors.PromoExpiredError):
        registry.resolve("SUMMER10")


def test_R07_end_is_exclusive(clock):
    errors = _errors()
    registry = _registry(clock, _windowed())
    clock.set(NOW + timedelta(days=1) - timedelta(microseconds=1))
    registry.resolve("SUMMER10")
    clock.set(NOW + timedelta(days=1))
    with pytest.raises(errors.PromoExpiredError):
        registry.resolve("SUMMER10")


def test_R07_place_order_checks_window_with_injected_clock(p, make_cart, clock):
    errors = _errors()
    registry = _registry(clock, _windowed())
    service = OrderService(clock=clock, promos=registry)
    cart = make_cart(p["book"])
    service.place_order(cart, "SUMMER10")
    clock.advance(timedelta(days=2))
    with pytest.raises(errors.PromoExpiredError):
        service.place_order(cart, "SUMMER10")
    assert len(service.store) == 1


# --------------------------------------------------------------------------- R08


def test_R08_resolve_ignores_case_and_surrounding_spaces(clock):
    registry = _registry(clock, _promo())
    assert registry.resolve("  summer10\t").code == "SUMMER10"
    assert registry.uses(" Summer10 ") == 0


def test_R08_duplicate_codes_rejected(clock):
    registry = _registry(clock, _promo(code="summer"))
    with pytest.raises(ValidationError):
        registry.add(_promo(code=" SUMMER "))


def test_R08_order_stores_normalized_code(p, make_cart, clock):
    service = OrderService(clock=clock, promos=_registry(clock, _promo()))
    order = service.place_order(make_cart(p["book"]), " summer10 ")
    assert order.promo_code == "SUMMER10"
    assert order.total.discount == D("60.00")


def test_R08_blank_code_means_no_promo(p, make_cart, clock):
    registry = _registry(clock, _promo())
    service = OrderService(clock=clock, promos=registry)
    cart = make_cart(p["book"])
    assert service.quote(cart, "").discount == D("0.00")
    order = service.place_order(cart, "   ")
    assert order.promo_code is None
    assert order.total.total == D("959.00")


# --------------------------------------------------------------------------- R09


def test_R09_error_hierarchy():
    errors = _errors()
    for name in ("UnknownPromoCodeError", "PromoExpiredError", "PromoConditionsError"):
        cls = getattr(errors, name)
        assert issubclass(cls, errors.PromoError)
    assert issubclass(errors.PromoError, ShopError)
    distinct = [errors.UnknownPromoCodeError, errors.PromoExpiredError, errors.PromoConditionsError]
    for a in distinct:
        for b in distinct:
            if a is not b:
                assert not issubclass(a, b)


def test_R09_unknown_code(p, make_cart, clock):
    errors = _errors()
    registry = _registry(clock, _promo())
    with pytest.raises(errors.UnknownPromoCodeError):
        registry.resolve("WINTER")
    service = OrderService(clock=clock, promos=registry)
    with pytest.raises(errors.UnknownPromoCodeError):
        service.place_order(make_cart(p["book"]), "winter")
    assert len(service.store) == 0


def test_R09_service_without_registry_knows_no_codes(p, make_cart, clock):
    errors = _errors()
    with pytest.raises(errors.UnknownPromoCodeError):
        OrderService(clock=clock).place_order(make_cart(p["book"]), "SUMMER10")


def test_R09_expired_wins_over_unmet_conditions(p, make_cart, clock):
    errors = _errors()
    promo = _promo(min_order_amount=D("100000"), expires_at=NOW)
    service = OrderService(clock=clock, promos=_registry(clock, promo))
    with pytest.raises(errors.PromoExpiredError):
        service.place_order(make_cart(p["book"]), "SUMMER10")


def test_R09_expired_wins_over_exhausted_limit(p, make_cart, clock):
    errors = _errors()
    promo = _promo(max_uses=1, expires_at=NOW + timedelta(hours=1))
    service = OrderService(clock=clock, promos=_registry(clock, promo))
    service.place_order(make_cart(p["book"]), "SUMMER10")
    clock.advance(timedelta(hours=1))
    with pytest.raises(errors.PromoExpiredError):
        service.place_order(make_cart(p["book"]), "SUMMER10")


# --------------------------------------------------------------------------- R10


def test_R10_quote_does_not_consume_uses(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses=1))
    service = OrderService(clock=clock, promos=registry)
    cart = make_cart(p["book"])
    service.quote(cart, "SUMMER10")
    service.quote(cart, "SUMMER10")
    calculate_total(cart, promo=registry.resolve("SUMMER10"))
    assert registry.uses("SUMMER10") == 0
    service.place_order(cart, "SUMMER10")
    assert registry.uses("SUMMER10") == 1


def test_R10_limit_reached(p, make_cart, clock):
    errors = _errors()
    registry = _registry(clock, _promo(max_uses=2))
    service = OrderService(clock=clock, promos=registry)
    cart = make_cart(p["book"])
    service.place_order(cart, "SUMMER10")
    service.place_order(cart, "summer10")
    with pytest.raises(errors.PromoConditionsError):
        service.place_order(cart, "SUMMER10")
    with pytest.raises(errors.PromoConditionsError):
        registry.resolve("SUMMER10")
    assert registry.uses("SUMMER10") == 2
    assert len(service.store) == 2


def test_R10_failed_order_does_not_consume(p, make_cart, clock):
    errors = _errors()
    registry = _registry(clock, _promo(max_uses=1, min_order_amount=D("1000")))
    service = OrderService(clock=clock, promos=registry)
    with pytest.raises(errors.PromoConditionsError):
        service.place_order(make_cart(p["book"]), "SUMMER10")
    assert registry.uses("SUMMER10") == 0
    assert len(service.store) == 0
    order = service.place_order(make_cart(p["laptop"]), "SUMMER10")
    assert order.total.discount == D("250.00")


def test_R10_cancel_returns_use(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses=1))
    service = OrderService(clock=clock, promos=registry)
    order = service.place_order(make_cart(p["book"]), "SUMMER10")
    service.cancel(order.order_id)
    assert registry.uses("SUMMER10") == 0
    again = service.place_order(make_cart(p["book"]), "SUMMER10")
    assert again.promo_code == "SUMMER10"
    assert registry.uses("SUMMER10") == 1


# --------------------------------------------------------------------------- R11


def test_R11_line_discounts_sum_exactly(make_cart):
    cart = make_cart(_product("A-1", "100.00"), _product("B-1", "100.00"), _product("C-1", "100.00"))
    total = calculate_total(cart, promo=_promo(kind="FIXED", value="100"))
    assert [line.discount for line in total.lines] == [D("33.34"), D("33.33"), D("33.33")]
    assert sum(line.discount for line in total.lines) == total.discount == D("100.00")


def test_R11_leftover_goes_to_largest_remainder(make_cart):
    # shares: 4.2, 1.4, 1.4 kopecks -> floors 4, 1, 1 -> leftover kopeck to the first 0.4
    cart = make_cart((_product("A-1", "1.00"), 3), _product("B-1", "1.00"), _product("C-1", "1.00"))
    total = calculate_total(cart, promo=_promo(kind="FIXED", value="0.07"))
    assert [line.discount for line in total.lines] == [D("0.04"), D("0.02"), D("0.01")]


def test_R11_line_discount_never_exceeds_line_amount(make_cart):
    cart = make_cart(_product("A-1", "10.00"), _product("B-1", "0.01"), _product("C-1", "0.01"))
    total = calculate_total(cart, promo=_promo(kind="FIXED", value="10.01"))
    assert [line.discount for line in total.lines] == [D("9.99"), D("0.01"), D("0.01")]


def test_R11_excluded_lines_skipped_ties_by_cart_order(p, make_cart):
    cart = make_cart(p["gift"], _product("X-1", "1.00"), _product("Y-1", "1.00"), _product("Z-1", "1.00"))
    cart.set_quantity("X-1", 1)
    total = calculate_total(cart, promo=_promo(kind="FIXED", value="0.10"))
    assert [line.discount for line in total.lines] == [D("0.00"), D("0.04"), D("0.03"), D("0.03")]


# --------------------------------------------------------------------------- R12


def test_R12_tax_on_discounted_line_amounts(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"], p["gift"]), promo=_promo())
    assert [line.discount for line in total.lines] == [D("250.00"), D("60.00"), D("0.00")]
    assert [line.tax for line in total.lines] == [D("450.00"), D("54.00"), D("0.00")]
    assert total.tax == D("504.00")
    assert total.total == D("4294.00")


def test_R12_tax_follows_allocation_per_category(p, make_cart):
    total = calculate_total(make_cart(p["book"], p["shirt"]), promo=_promo(kind="FIXED", value="160"))
    assert [line.discount for line in total.lines] == [D("60.00"), D("100.00")]
    assert [line.tax for line in total.lines] == [D("54.00"), D("180.00")]
    assert total.tax == D("234.00")


def test_R12_tax_rounded_per_line_after_discount(p, make_cart):
    total = calculate_total(make_cart(p["tea"]), promo=_promo())
    # (12.25 - 1.23) * 10 % = 1.102 -> 1.10
    assert total.tax == D("1.10")
    assert total.total == D("311.12")


# --------------------------------------------------------------------------- R13


def test_R13_free_shipping_threshold_uses_amount_after_discount(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"]), promo=_promo())
    assert total.shipping == D("299.00")
    assert total.total == D("3593.00")


def test_R13_threshold_with_gift_cards_and_discount(p, make_cart):
    # 3000 of shirts + 1000 gift card; after 10 % off shirts goods are 3700 -> still free
    total = calculate_total(make_cart((p["shirt"], 3), p["gift"]), promo=_promo())
    assert total.discount == D("300.00")
    assert total.shipping == D("0.00")
    # without the gift card 2700 < 3000 -> paid shipping
    total = calculate_total(make_cart((p["shirt"], 3)), promo=_promo())
    assert total.shipping == D("299.00")
    assert total.total == D("2700.00") + D("299.00") + D("540.00")


def test_R13_threshold_reached_exactly_after_discount(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"]), promo=_promo(kind="FIXED", value="100"))
    assert [line.discount for line in total.lines] == [D("80.65"), D("19.35")]
    assert total.shipping == D("0.00")
    assert total.tax == D("541.94")
    assert total.total == D("3541.94")


def test_R13_discount_never_reduces_shipping(p, make_cart):
    total = calculate_total(make_cart(p["book"]), promo=_promo(kind="FIXED", value="5000"))
    assert total.discount == D("600.00")
    assert total.shipping == D("299.00")
    assert total.total == D("299.00")


def test_R13_total_formula(p, make_cart):
    total = calculate_total(make_cart(p["shirt"], p["tea"], p["gift"]), promo=_promo(value="15"))
    assert total.subtotal == D("2012.25")
    assert total.total == total.subtotal - total.discount + total.shipping + total.tax


# --------------------------------------------------------------------------- R14


def test_R14_order_keeps_code_and_discount(p, make_cart, clock):
    registry = _registry(clock, _promo())
    service = OrderService(clock=clock, promos=registry)
    order = service.place_order(make_cart(p["laptop"], p["book"], p["gift"]), "SUMMER10")
    assert order.promo_code == "SUMMER10"
    assert order.total.discount == D("310.00")
    assert order.total.total == D("4294.00")
    assert service.store.get(order.order_id).promo_code == "SUMMER10"
    assert registry.uses("SUMMER10") == 1


def test_R14_quote_matches_placed_order(p, make_cart, clock):
    service = OrderService(clock=clock, promos=_registry(clock, _promo(kind="FIXED", value="100")))
    cart = make_cart(p["laptop"], p["book"])
    quoted = service.quote(cart, "summer10")
    assert quoted == service.place_order(cart, "summer10").total
    assert len(service.store) == 1


def test_R14_service_uses_its_shipping_and_tax_policies(p, make_cart, clock):
    service = OrderService(
        clock=clock,
        shipping=ShippingPolicy(free_threshold=None),
        tax=TaxPolicy(rates={}, default_rate=D("0")),
        promos=_registry(clock, _promo()),
    )
    order = service.place_order(make_cart(p["laptop"], p["book"]), "SUMMER10")
    assert order.total.tax == D("0.00")
    assert order.total.shipping == D("299.00")
    assert order.total.total == D("3089.00")
