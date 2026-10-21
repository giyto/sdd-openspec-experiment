"""Acceptance tests for the change request SHOP-447 (promo codes after the summer campaign)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from shop.catalog import Category, Product
from shop.errors import PromoConditionsError, PromoExpiredError, ValidationError
from shop.orders import OrderService
from shop.pricing import calculate_total
from shop.promo import DiscountKind, PromoCode, PromoRegistry

NOW = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)  # same moment as the clock fixture

D = Decimal


def _promo(code="SUMMER10", kind="PERCENT", value="10", **kwargs):
    return PromoCode(code=code, kind=getattr(DiscountKind, kind), value=D(value), **kwargs)


def _free_shipping(code="FREE299", **kwargs):
    return _promo(code=code, kind="FREE_SHIPPING", value="0", **kwargs)


def _registry(clock, *promos):
    registry = PromoRegistry(clock)
    for promo in promos:
        registry.add(promo)
    return registry


def _product(sku, price, category=Category.ELECTRONICS):
    return Product(sku, sku.title(), D(price), category)


# --------------------------------------------------------------------------- C01


def test_C01_threshold_uses_amount_before_discount(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"]), promo=_promo())
    assert total.discount == D("310.00")
    assert total.shipping == D("0.00")
    assert total.total == D("3294.00")


def test_C01_threshold_reached_only_before_discount(p, make_cart):
    total = calculate_total(make_cart((p["shirt"], 3)), promo=_promo())
    assert total.shipping == D("0.00")
    assert total.total == D("3240.00")


def test_C01_threshold_counts_gift_cards_before_discount(p, make_cart):
    total = calculate_total(make_cart((p["shirt"], 2), p["gift"]), promo=_promo(kind="FIXED", value="500"))
    assert total.discount == D("500.00")
    assert total.shipping == D("0.00")
    assert total.total == D("2800.00")


# --------------------------------------------------------------------------- C02


def test_C02_fixed_capped_at_half_of_qualifying_items(p, make_cart):
    total = calculate_total(make_cart(p["book"], p["gift"]), promo=_promo(kind="FIXED", value="1000"))
    assert total.discount == D("300.00")
    assert [line.discount for line in total.lines] == [D("300.00"), D("0.00")]
    assert total.total == D("1629.00")


def test_C02_fixed_below_half_unchanged(p, make_cart):
    total = calculate_total(make_cart(p["laptop"]), promo=_promo(kind="FIXED", value="500"))
    assert total.discount == D("500.00")
    assert total.total == D("2699.00")


def test_C02_half_is_rounded_half_up(p, make_cart):
    total = calculate_total(make_cart(p["tea"]), promo=_promo(kind="FIXED", value="10"))
    # half of 12.25 = 6.125 -> 6.13
    assert total.discount == D("6.13")
    assert total.tax == D("0.61")


def test_C02_half_is_taken_from_qualifying_items_only(p, make_cart):
    total = calculate_total(make_cart(p["gift"], p["laptop"]), promo=_promo(kind="FIXED", value="2000"))
    assert total.discount == D("1250.00")


# --------------------------------------------------------------------------- C03


def test_C03_tie_goes_to_larger_line(make_cart):
    cart = make_cart(_product("A-1", "1.00"), _product("B-1", "3.00"))
    total = calculate_total(cart, promo=_promo(kind="FIXED", value="0.02"))
    assert [line.discount for line in total.lines] == [D("0.00"), D("0.02")]


def test_C03_tie_larger_line_uses_line_amount(make_cart):
    # kopeck shares 0.5, 1.5, 2.0 -> floors 0, 1, 2 -> the leftover goes to B (3.00 > 1.00)
    cart = make_cart(_product("A-1", "1.00"), (_product("B-1", "1.50"), 2), _product("C-1", "4.00"))
    total = calculate_total(cart, promo=_promo(kind="FIXED", value="0.04"))
    assert [line.discount for line in total.lines] == [D("0.00"), D("0.02"), D("0.02")]


def test_C03_equal_lines_still_follow_cart_order(p, make_cart):
    cart = make_cart(p["gift"], _product("X-1", "1.00"), _product("Y-1", "1.00"), _product("Z-1", "1.00"))
    total = calculate_total(cart, promo=_promo(kind="FIXED", value="0.10"))
    assert [line.discount for line in total.lines] == [D("0.00"), D("0.04"), D("0.03"), D("0.03")]


# --------------------------------------------------------------------------- C04


def _placed_with_limited_code(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses=1))
    service = OrderService(clock=clock, promos=registry)
    order = service.place_order(make_cart(p["book"]), "SUMMER10")
    return registry, service, order


def test_C04_cancel_within_24h_returns_use(p, make_cart, clock):
    registry, service, order = _placed_with_limited_code(p, make_cart, clock)
    clock.advance(timedelta(hours=24) - timedelta(seconds=1))
    service.cancel(order.order_id)
    assert registry.uses("SUMMER10") == 0
    assert service.place_order(make_cart(p["book"]), "SUMMER10").promo_code == "SUMMER10"


def test_C04_cancel_after_24h_burns_use(p, make_cart, clock):
    registry, service, order = _placed_with_limited_code(p, make_cart, clock)
    clock.advance(timedelta(hours=25))
    service.cancel(order.order_id)
    assert registry.uses("SUMMER10") == 1
    with pytest.raises(PromoConditionsError):
        service.place_order(make_cart(p["book"]), "SUMMER10")


def test_C04_exactly_24h_is_too_late(p, make_cart, clock):
    registry, service, order = _placed_with_limited_code(p, make_cart, clock)
    clock.advance(timedelta(hours=24))
    service.cancel(order.order_id)
    assert registry.uses("SUMMER10") == 1


# --------------------------------------------------------------------------- C05


def test_C05_free_shipping_waives_fee(p, make_cart):
    total = calculate_total(make_cart(p["book"]), promo=_free_shipping())
    assert total.discount == D("0.00")
    assert [line.discount for line in total.lines] == [D("0.00")]
    assert total.shipping == D("0.00")
    assert total.shipping_discount == D("299.00")
    assert total.tax == D("60.00")
    assert total.total == D("660.00")


def test_C05_nothing_to_waive_when_already_free(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"]), promo=_free_shipping())
    assert total.shipping == D("0.00")
    assert total.shipping_discount == D("0.00")
    assert total.total == D("3660.00")


def test_C05_value_must_be_zero():
    assert _free_shipping().value == D("0")
    with pytest.raises(ValidationError):
        _promo(kind="FREE_SHIPPING", value="10")


def test_C05_shipping_discount_zero_for_other_kinds(p, make_cart):
    cart = make_cart(p["book"])
    assert calculate_total(cart).shipping_discount == D("0.00")
    assert calculate_total(cart, promo=_promo()).shipping_discount == D("0.00")


# --------------------------------------------------------------------------- C06


def test_C06_percent_discount_capped(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"]), promo=_promo(max_discount=D("100")))
    assert total.discount == D("100.00")


def test_C06_cap_not_reached(p, make_cart):
    total = calculate_total(make_cart(p["book"]), promo=_promo(max_discount=D("100")))
    assert total.discount == D("60.00")


def test_C06_max_discount_validation():
    with pytest.raises(ValidationError):
        _promo(kind="FIXED", value="100", max_discount=D("50"))
    with pytest.raises(ValidationError):
        _free_shipping(max_discount=D("50"))
    with pytest.raises(ValidationError):
        _promo(max_discount=D("0"))


# --------------------------------------------------------------------------- C07


def test_C07_limit_per_customer(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses_per_customer=1))
    service = OrderService(clock=clock, promos=registry)
    service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    with pytest.raises(PromoConditionsError):
        service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-2")
    assert registry.uses("SUMMER10") == 2
    assert registry.uses("SUMMER10", customer_id="c-1") == 1
    assert registry.uses("SUMMER10", customer_id="c-3") == 0


def test_C07_customer_required_for_per_customer_code(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses_per_customer=2))
    service = OrderService(clock=clock, promos=registry)
    with pytest.raises(PromoConditionsError):
        service.place_order(make_cart(p["book"]), "SUMMER10")
    with pytest.raises(PromoConditionsError):
        service.quote(make_cart(p["book"]), "SUMMER10")
    assert len(service.store) == 0
    assert registry.uses("SUMMER10") == 0


def test_C07_order_keeps_customer_id(p, make_cart, clock):
    service = OrderService(clock=clock, promos=_registry(clock, _promo(max_uses_per_customer=1)))
    order = service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    assert order.customer_id == "c-1"
    assert service.store.get(order.order_id).customer_id == "c-1"
    assert service.place_order(make_cart(p["book"])).customer_id is None


def test_C07_resolve_checks_customer_and_validation(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses_per_customer=1))
    OrderService(clock=clock, promos=registry).place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    with pytest.raises(PromoConditionsError):
        registry.resolve("summer10", customer_id="c-1")
    assert registry.resolve("summer10", customer_id="c-2").code == "SUMMER10"
    with pytest.raises(ValidationError):
        _promo(code="OTHER", max_uses_per_customer=0)


# --------------------------------------------------------------------------- C08


def test_C08_free_shipping_min_order_on_qualifying_items(p, make_cart):
    promo = _free_shipping(min_order_amount=D("1000"))
    with pytest.raises(PromoConditionsError):
        calculate_total(make_cart(p["book"], p["gift"]), promo=promo)
    total = calculate_total(make_cart(p["shirt"]), promo=promo)
    assert total.shipping == D("0.00")
    assert total.shipping_discount == D("299.00")


def test_C08_free_shipping_needs_qualifying_items(p, make_cart):
    with pytest.raises(PromoConditionsError):
        calculate_total(make_cart(p["gift"]), promo=_free_shipping())
    with pytest.raises(PromoConditionsError):
        calculate_total(
            make_cart(p["book"]), promo=_free_shipping(excluded_categories=frozenset({Category.BOOKS}))
        )


def test_C08_free_shipping_limit_window_and_quote(p, make_cart, clock):
    registry = _registry(clock, _free_shipping(max_uses=1, expires_at=NOW + timedelta(hours=1)))
    service = OrderService(clock=clock, promos=registry)
    cart = make_cart(p["book"])
    assert service.quote(cart, "FREE299").shipping == D("0.00")
    assert registry.uses("FREE299") == 0
    service.place_order(cart, "FREE299")
    assert registry.uses("FREE299") == 1
    with pytest.raises(PromoConditionsError):
        service.place_order(cart, "FREE299")
    clock.advance(timedelta(hours=1))
    with pytest.raises(PromoExpiredError):
        service.place_order(cart, "FREE299")


def test_C08_free_shipping_code_input_normalized(p, make_cart, clock):
    service = OrderService(clock=clock, promos=_registry(clock, _free_shipping()))
    order = service.place_order(make_cart(p["book"]), "  free299 ")
    assert order.promo_code == "FREE299"
    assert order.total.shipping == D("0.00")
    assert order.total.total == D("660.00")


# --------------------------------------------------------------------------- C09


def test_C09_quote_and_failed_orders_do_not_consume_customer_uses(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses_per_customer=1, min_order_amount=D("1000")))
    service = OrderService(clock=clock, promos=registry)
    service.quote(make_cart(p["laptop"]), "SUMMER10", customer_id="c-1")
    service.quote(make_cart(p["laptop"]), "SUMMER10", customer_id="c-1")
    with pytest.raises(PromoConditionsError):
        service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    assert registry.uses("SUMMER10", customer_id="c-1") == 0
    order = service.place_order(make_cart(p["laptop"]), "SUMMER10", customer_id="c-1")
    assert order.total.discount == D("250.00")
    assert registry.uses("SUMMER10", customer_id="c-1") == 1


def test_C09_cancel_within_24h_returns_customer_use(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses_per_customer=1))
    service = OrderService(clock=clock, promos=registry)
    order = service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    clock.advance(timedelta(hours=2))
    service.cancel(order.order_id)
    assert registry.uses("SUMMER10", customer_id="c-1") == 0
    service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")


def test_C09_cancel_after_24h_keeps_customer_use(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses_per_customer=1))
    service = OrderService(clock=clock, promos=registry)
    order = service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    clock.advance(timedelta(hours=30))
    service.cancel(order.order_id)
    assert registry.uses("SUMMER10", customer_id="c-1") == 1
    with pytest.raises(PromoConditionsError):
        service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")


def test_C09_expiry_checked_before_customer_limit(p, make_cart, clock):
    registry = _registry(clock, _promo(max_uses_per_customer=1, expires_at=NOW + timedelta(hours=1)))
    service = OrderService(clock=clock, promos=registry)
    service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    clock.advance(timedelta(hours=1))
    with pytest.raises(PromoExpiredError):
        service.place_order(make_cart(p["book"]), "SUMMER10", customer_id="c-1")
    with pytest.raises(PromoExpiredError):
        service.place_order(make_cart(p["book"]), "SUMMER10")


# --------------------------------------------------------------------------- C10


def test_C10_capped_discount_allocated_and_taxed(p, make_cart):
    total = calculate_total(make_cart(p["laptop"], p["book"], p["gift"]), promo=_promo(max_discount=D("100")))
    assert [line.discount for line in total.lines] == [D("80.65"), D("19.35"), D("0.00")]
    assert [line.tax for line in total.lines] == [D("483.87"), D("58.07"), D("0.00")]
    assert total.shipping == D("0.00")
    assert total.total == D("4541.94")


def test_C10_cap_base_excludes_gift_cards(p, make_cart):
    total = calculate_total(make_cart(p["gift"], p["tea"]), promo=_promo(value="100", max_discount=D("5")))
    assert [line.discount for line in total.lines] == [D("0.00"), D("5.00")]
    assert total.tax == D("0.73")
    assert total.total == D("1306.98")


def test_C10_min_order_still_checked_on_qualifying_items(p, make_cart):
    promo = _promo(max_discount=D("50"), min_order_amount=D("1000"))
    with pytest.raises(PromoConditionsError):
        calculate_total(make_cart(p["book"], p["gift"]), promo=promo)
