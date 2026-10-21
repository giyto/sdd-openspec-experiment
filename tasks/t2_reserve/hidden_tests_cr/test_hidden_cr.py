"""Приёмочные тесты запроса на изменение WH-231 (доработки резервов).

Фикстуры (conftest.py): MAIN: BOLT-M8=10, NUT-M8=5; NORTH: BOLT-M8=4; OIL-5L без остатка.
Часы стоят на 2026-03-01T10:00:00Z, в журнале уже 3 события RECEIVE.
"""

import importlib
from datetime import datetime, timedelta, timezone

import pytest

import warehouse.errors as errors
import warehouse.models as models
from warehouse import reports
from warehouse.events import parse_line

T0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)
SEC = timedelta(seconds=1)
HOUR = timedelta(hours=1)


def S():
    return models.ReservationStatus


def L(warehouse, sku, qty):
    return models.ReservationLine(warehouse, sku, qty)


def A(warehouse, sku, on_hand, reserved, available):
    return models.Availability(warehouse, sku, on_hand, reserved, available)


def kinds_since(inv, start):
    return [event.kind for event in inv.log.events()[start:]]


# --- C01: пересборка корзины (замена активного резерва) -------------------------


def test_C01_replace_uses_own_reserved_stock(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    assert inv.available("MAIN", "BOLT-M8") == 2
    r = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 10)])
    assert r.status == S().ACTIVE
    assert r.lines == (L("MAIN", "BOLT-M8", 10),)
    assert inv.reserved("MAIN", "BOLT-M8") == 10
    assert inv.available("MAIN", "BOLT-M8") == 0


def test_C01_replacement_is_a_new_reservation(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("MAIN", "NUT-M8", 1)], ttl=10 * MIN)
    clock.advance(4 * MIN)
    r = inv.reserve("SO-1", [("MAIN", "NUT-M8", 2)], ttl=10 * MIN)
    assert r.created_at == T0 + 4 * MIN
    assert r.expires_at == T0 + 14 * MIN
    assert inv.get_reservation("SO-1").lines == (L("MAIN", "NUT-M8", 2),)
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert inv.reserved("MAIN", "NUT-M8") == 2


def test_C01_replace_journal_cancel_then_reserve(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    clock.advance(2 * MIN)
    start = len(inv.log)
    inv.reserve("SO-1", [("MAIN", "NUT-M8", 1), ("NORTH", "BOLT-M8", 2)])
    assert kinds_since(inv, start) == ["RESERVE_CANCEL", "RESERVE", "RESERVE"]
    events = inv.log.events()[start:]
    assert dict(events[0].fields) == {"order": "SO-1"}
    assert events[1].fields["sku"] == "NUT-M8"
    assert events[2].fields["wh"] == "NORTH"


def test_C01_confirmed_order_still_cannot_be_replaced(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.confirm("SO-1")
    start = len(inv.log)
    with pytest.raises(errors.DuplicateReservationError):
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)])
    assert inv.get_reservation("SO-1").status == S().CONFIRMED
    assert len(inv.log) == start


# --- C02: возврат подтверждённого заказа ---------------------------------------


def test_C02_cancel_confirmed_returns_goods(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("NORTH", "BOLT-M8", 1), ("MAIN", "NUT-M8", 2)])
    inv.confirm("SO-1")
    r = inv.cancel("SO-1")
    assert r.status == S().CANCELLED
    assert inv.on_hand("MAIN", "BOLT-M8") == 10
    assert inv.on_hand("NORTH", "BOLT-M8") == 4
    assert inv.on_hand("MAIN", "NUT-M8") == 5
    assert inv.get_reservation("SO-1").status == S().CANCELLED
    assert inv.reserved("MAIN", "BOLT-M8") == 0


def test_C02_return_journal(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("MAIN", "NUT-M8", 2)])
    inv.confirm("SO-1")
    clock.advance(HOUR)
    start = len(inv.log)
    inv.cancel("SO-1")
    events = inv.log.events()[start:]
    assert [event.kind for event in events] == ["RECEIVE", "RECEIVE", "RESERVE_CANCEL"]
    assert dict(events[0].fields) == {"wh": "MAIN", "sku": "BOLT-M8", "qty": "3", "ref": "SO-1"}
    assert dict(events[1].fields) == {"wh": "MAIN", "sku": "NUT-M8", "qty": "2", "ref": "SO-1"}
    assert dict(events[2].fields) == {"order": "SO-1"}


def test_C02_returned_stock_is_available_again(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 10)])
    inv.confirm("SO-1")
    with pytest.raises(errors.InsufficientStockError):
        inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)])
    inv.cancel("SO-1")
    assert inv.available("MAIN", "BOLT-M8") == 10
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 10)])


# --- C03: TTL по умолчанию 20 минут --------------------------------------------


def test_C03_default_ttl_constant():
    module = importlib.import_module("warehouse.reservations")
    assert module.DEFAULT_RESERVATION_TTL == timedelta(minutes=20)


def test_C03_reserve_without_ttl_lives_20_minutes(inv, clock):
    r = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 4)])
    assert r.expires_at == T0 + 20 * MIN
    clock.advance(20 * MIN - SEC)
    assert inv.get_reservation("SO-1").status == S().ACTIVE
    clock.advance(SEC)
    assert inv.get_reservation("SO-1").status == S().EXPIRED


def test_C03_default_ttl_written_to_journal(inv):
    start = len(inv.log)
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)])
    assert inv.log.events()[start].fields["expires"] == "2026-03-01T10:20:00Z"


# --- C04: предельный срок резерва ----------------------------------------------


def test_C04_max_lifetime_constant():
    module = importlib.import_module("warehouse.reservations")
    assert module.MAX_RESERVATION_LIFETIME == timedelta(hours=2)


def test_C04_reserve_ttl_over_limit_rejected(inv):
    r = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=2 * HOUR)
    assert r.expires_at == T0 + 2 * HOUR
    start = len(inv.log)
    with pytest.raises(errors.ValidationError):
        inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)], ttl=2 * HOUR + SEC)
    with pytest.raises(errors.ReservationNotFoundError):
        inv.get_reservation("SO-2")
    assert len(inv.log) == start


def test_C04_extend_is_capped_at_limit(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=90 * MIN)
    clock.advance(HOUR)
    start = len(inv.log)
    r = inv.extend("SO-1", 3 * HOUR)
    assert r.expires_at == T0 + 2 * HOUR
    assert inv.log.lines()[start:] == [
        "000005 2026-03-01T11:00:00Z RESERVE_EXTEND expires=2026-03-01T12:00:00Z order=SO-1"
    ]


def test_C04_extend_at_limit_changes_nothing(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=30 * MIN)
    clock.advance(20 * MIN)
    inv.extend("SO-1", 5 * HOUR)
    clock.advance(HOUR)
    start = len(inv.log)
    r = inv.extend("SO-1", 30 * MIN)
    assert r.expires_at == T0 + 2 * HOUR
    assert len(inv.log) == start
    clock.advance(40 * MIN)
    assert inv.get_reservation("SO-1").status == S().EXPIRED


# --- C05: список резервов ------------------------------------------------------


def test_C05_reservations_sorted_by_created_then_order(inv, clock):
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)])
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)])
    clock.advance(MIN)
    inv.reserve("SO-0", [("MAIN", "NUT-M8", 1)])
    assert [r.order_id for r in inv.reservations()] == ["SO-1", "SO-2", "SO-0"]


def test_C05_reservations_filter_uses_current_status(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)], ttl=30 * MIN)
    inv.reserve("SO-3", [("MAIN", "BOLT-M8", 1)], ttl=30 * MIN)
    inv.confirm("SO-3")
    clock.advance(5 * MIN)
    assert [r.order_id for r in inv.reservations(S().EXPIRED)] == ["SO-1"]
    assert [r.order_id for r in inv.reservations(S().ACTIVE)] == ["SO-2"]
    assert [r.order_id for r in inv.reservations(S().CONFIRMED)] == ["SO-3"]
    assert inv.reservations(S().CANCELLED) == []
    assert {r.order_id: r.status for r in inv.reservations()} == {
        "SO-1": S().EXPIRED, "SO-2": S().ACTIVE, "SO-3": S().CONFIRMED,
    }


def test_C05_reservations_one_per_order(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)])
    clock.advance(MIN)
    inv.reserve("SO-1", [("MAIN", "NUT-M8", 2)])
    snapshots = inv.reservations()
    assert len(snapshots) == 1
    assert snapshots[0].lines == (L("MAIN", "NUT-M8", 2),)
    assert snapshots[0] == inv.get_reservation("SO-1")


# --- C06: доступность по позициям ----------------------------------------------


def test_C06_availability_rows(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("NORTH", "BOLT-M8", 4)])
    assert inv.availability() == [
        A("MAIN", "BOLT-M8", 10, 3, 7),
        A("MAIN", "NUT-M8", 5, 0, 5),
        A("NORTH", "BOLT-M8", 4, 4, 0),
    ]
    assert inv.availability("NORTH") == [A("NORTH", "BOLT-M8", 4, 4, 0)]


def test_C06_availability_ignores_expired_and_confirmed(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=5 * MIN)
    inv.reserve("SO-2", [("MAIN", "NUT-M8", 2)], ttl=30 * MIN)
    inv.confirm("SO-2")
    clock.advance(5 * MIN)
    assert inv.availability("MAIN") == [
        A("MAIN", "BOLT-M8", 10, 0, 10),
        A("MAIN", "NUT-M8", 3, 0, 3),
    ]


def test_C06_availability_after_recount_below_reservations(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    inv.adjust("MAIN", "BOLT-M8", 5, "recount")
    row = [a for a in inv.availability() if (a.warehouse, a.sku) == ("MAIN", "BOLT-M8")][0]
    assert row == A("MAIN", "BOLT-M8", 5, 8, 0)
    assert row.available == inv.available("MAIN", "BOLT-M8")


def test_C06_availability_includes_reserved_position_without_stock(inv):
    inv.reserve("SO-1", [("MAIN", "NUT-M8", 5)])
    inv.adjust("MAIN", "NUT-M8", 0, "lost")
    assert A("MAIN", "NUT-M8", 0, 5, 0) in inv.availability()
    inv.cancel("SO-1")
    assert all(a.sku != "NUT-M8" for a in inv.availability())


# --- C07: журнал истечений -----------------------------------------------------


def test_C07_sweep_returns_expired_in_expiry_order(inv, clock):
    inv.reserve("SO-B", [("MAIN", "BOLT-M8", 1)], ttl=10 * MIN)
    inv.reserve("SO-A", [("MAIN", "BOLT-M8", 1)], ttl=10 * MIN)
    inv.reserve("SO-0", [("MAIN", "BOLT-M8", 1)], ttl=12 * MIN)
    inv.reserve("SO-Z", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    inv.reserve("SO-L", [("MAIN", "BOLT-M8", 1)], ttl=30 * MIN)
    clock.advance(15 * MIN)
    assert inv.sweep_expired() == ["SO-Z", "SO-A", "SO-B", "SO-0"]


def test_C07_sweep_writes_once(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)], ttl=10 * MIN)
    clock.advance(5 * MIN)
    start = len(inv.log)
    assert inv.sweep_expired() == ["SO-1"]
    assert inv.sweep_expired() == []
    clock.advance(5 * MIN)
    assert inv.sweep_expired() == ["SO-2"]
    assert inv.sweep_expired() == []
    assert kinds_since(inv, start) == ["RESERVE_EXPIRE", "RESERVE_EXPIRE"]


def test_C07_sweep_changes_no_state(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 4)], ttl=5 * MIN)
    clock.advance(6 * MIN)
    before = (inv.on_hand("MAIN", "BOLT-M8"), inv.available("MAIN", "BOLT-M8"))
    inv.sweep_expired()
    assert inv.get_reservation("SO-1").status == S().EXPIRED
    assert (inv.on_hand("MAIN", "BOLT-M8"), inv.available("MAIN", "BOLT-M8")) == before


def test_C07_sweep_with_nothing_expired(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    clock.advance(5 * MIN - SEC)
    start = len(inv.log)
    assert inv.sweep_expired() == []
    assert len(inv.log) == start


# --- C08: замена резерва и «всё или ничего» ------------------------------------


def test_C08_failed_replacement_keeps_old_reservation(inv, clock):
    old = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=10 * MIN)
    clock.advance(MIN)
    start = len(inv.log)
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 2), ("MAIN", "NUT-M8", 6)])
    assert info.value.sku == "NUT-M8"
    assert inv.get_reservation("SO-1") == old
    assert inv.reserved("MAIN", "BOLT-M8") == 3
    assert len(inv.log) == start


def test_C08_invalid_replacement_keeps_old_reservation(inv):
    old = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    start = len(inv.log)
    with pytest.raises(errors.UnknownSkuError):
        inv.reserve("SO-1", [("MAIN", "NOPE", 1)])
    with pytest.raises(errors.ValidationError):
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=timedelta(0))
    assert inv.get_reservation("SO-1") == old
    assert len(inv.log) == start


def test_C08_replacement_sums_duplicate_lines(inv):
    inv.reserve("SO-1", [("MAIN", "NUT-M8", 4)])
    inv.reserve("SO-2", [("MAIN", "NUT-M8", 1)])
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.reserve("SO-1", [("MAIN", "NUT-M8", 3), ("MAIN", "NUT-M8", 2)])
    assert (info.value.requested, info.value.available) == (5, 4)
    inv.reserve("SO-1", [("MAIN", "NUT-M8", 2), ("MAIN", "NUT-M8", 2)])
    assert inv.reserved("MAIN", "NUT-M8") == 5


def test_C08_replacement_does_not_free_other_orders(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 4)])
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 5)])
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 6)])
    assert info.value.available == 5
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 5)])
    assert inv.available("MAIN", "BOLT-M8") == 0


# --- C09: возврат и прежние правила --------------------------------------------


def test_C09_return_allowed_after_reservation_time_passed(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=5 * MIN)
    inv.confirm("SO-1")
    clock.advance(3 * HOUR)
    assert inv.cancel("SO-1").status == S().CANCELLED
    assert inv.on_hand("MAIN", "BOLT-M8") == 10


def test_C09_second_cancel_after_return_is_noop(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.confirm("SO-1")
    inv.cancel("SO-1")
    start = len(inv.log)
    assert inv.cancel("SO-1").status == S().CANCELLED
    assert inv.on_hand("MAIN", "BOLT-M8") == 10
    assert len(inv.log) == start


def test_C09_order_can_be_reserved_again_after_return(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.confirm("SO-1")
    inv.cancel("SO-1")
    r = inv.reserve("SO-1", [("MAIN", "NUT-M8", 2)])
    assert r.status == S().ACTIVE
    assert inv.reserved("MAIN", "NUT-M8") == 2


def test_C09_return_counts_in_movement_summary(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.confirm("SO-1")
    inv.cancel("SO-1")
    summary = reports.movement_summary(inv.log)
    assert summary["BOLT-M8"].issued == 3
    assert summary["BOLT-M8"].received == 14 + 3
    for line in inv.log.lines():
        assert parse_line(line).format() == line


# --- C10: журнал истечений и прежние правила -----------------------------------


def test_C10_expire_event_line_format(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=7 * MIN)
    clock.advance(30 * MIN)
    start = len(inv.log)
    inv.sweep_expired()
    assert inv.log.lines()[start:] == [
        "000005 2026-03-01T10:30:00Z RESERVE_EXPIRE expires=2026-03-01T10:07:00Z order=SO-1"
    ]


def test_C10_expired_exactly_at_expires_at_is_swept(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=7 * MIN)
    clock.advance(7 * MIN)
    assert inv.sweep_expired() == ["SO-1"]


def test_C10_confirmed_and_cancelled_are_not_swept(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    inv.reserve("SO-3", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    inv.confirm("SO-1")
    inv.cancel("SO-2")
    clock.advance(HOUR)
    assert inv.sweep_expired() == ["SO-3"]
    start = len(inv.log)
    inv.cancel("SO-3")
    assert inv.get_reservation("SO-3").status == S().EXPIRED
    assert len(inv.log) == start


def test_C10_reserved_again_and_expired_again_is_swept_again(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=5 * MIN)
    clock.advance(5 * MIN)
    assert inv.sweep_expired() == ["SO-1"]
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 2)], ttl=5 * MIN)
    assert inv.sweep_expired() == []
    clock.advance(5 * MIN)
    assert inv.sweep_expired() == ["SO-1"]
    expires = [e.fields["expires"] for e in inv.log.events("RESERVE_EXPIRE")]
    assert expires == ["2026-03-01T10:05:00Z", "2026-03-01T10:10:00Z"]
