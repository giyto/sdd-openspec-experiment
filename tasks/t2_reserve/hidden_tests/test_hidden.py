"""Приёмочные тесты: резервирование товара под заказы с TTL (WH-214).

Новые имена импортируются внутри тестов, чтобы тесты обратной совместимости
(test_API_*) собирались и на коде без резервов.
"""

import importlib
import io
import json
from datetime import datetime, timedelta, timezone

import pytest

import warehouse.errors as errors
import warehouse.models as models
from warehouse import reports
from warehouse.clock import ManualClock, SystemClock
from warehouse.events import EventLog, parse_line, parse_timestamp
from warehouse.inventory import Inventory
from warehouse.storage import InMemoryStore

T0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)
MIN = timedelta(minutes=1)
SEC = timedelta(seconds=1)


def S():
    return models.ReservationStatus


def L(warehouse, sku, qty):
    return models.ReservationLine(warehouse, sku, qty)


def new_events(inv, start):
    return inv.log.events()[start:]


# --- R01: резервирование заказа ------------------------------------------------


def test_R01_reserve_returns_active_snapshot(inv):
    r = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("NORTH", "BOLT-M8", 1)], ttl=10 * MIN)
    assert r.order_id == "SO-1"
    assert r.status == S().ACTIVE
    assert r.status == "active"
    assert r.created_at == T0
    assert r.expires_at == T0 + 10 * MIN
    assert r.lines == (L("MAIN", "BOLT-M8", 3), L("NORTH", "BOLT-M8", 1))
    assert inv.on_hand("MAIN", "BOLT-M8") == 10
    assert inv.on_hand("NORTH", "BOLT-M8") == 4


def test_R01_default_ttl_is_15_minutes(inv):
    module = importlib.import_module("warehouse.reservations")
    assert module.DEFAULT_RESERVATION_TTL == timedelta(minutes=15)
    r = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)])
    assert r.expires_at == T0 + timedelta(minutes=15)


def test_R01_accepts_reservation_line_objects(inv):
    r = inv.reserve("SO-1", [L("MAIN", "NUT-M8", 2), ("MAIN", "BOLT-M8", 1)])
    assert r.lines == (L("MAIN", "NUT-M8", 2), L("MAIN", "BOLT-M8", 1))
    assert inv.reserved("MAIN", "NUT-M8") == 2


@pytest.mark.parametrize("ttl", [timedelta(0), timedelta(minutes=-5), 600])
def test_R01_rejects_bad_ttl(inv, ttl):
    start = len(inv.log)
    with pytest.raises(errors.ValidationError):
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=ttl)
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert len(inv.log) == start


def test_R01_rejects_bad_order_id_and_empty_lines(inv):
    for order_id in ["", "SO 1"]:
        with pytest.raises(errors.ValidationError):
            inv.reserve(order_id, [("MAIN", "BOLT-M8", 1)])
    with pytest.raises(errors.ValidationError):
        inv.reserve("SO-1", [])
    assert inv.reserved("MAIN", "BOLT-M8") == 0


# --- R02: всё или ничего -------------------------------------------------------


def test_R02_shortage_reserves_nothing(inv):
    start = len(inv.log)
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("MAIN", "NUT-M8", 6)])
    exc = info.value
    assert (exc.warehouse, exc.sku, exc.requested, exc.available) == ("MAIN", "NUT-M8", 6, 5)
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert inv.available("MAIN", "BOLT-M8") == 10
    assert len(inv.log) == start


def test_R02_unknown_sku_reserves_nothing(inv):
    start = len(inv.log)
    with pytest.raises(errors.UnknownSkuError):
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("MAIN", "NOPE", 1)])
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert len(inv.log) == start


def test_R02_bad_quantity_reserves_nothing(inv):
    with pytest.raises(errors.InvalidQuantityError):
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("MAIN", "NUT-M8", 0)])
    assert inv.reserved("MAIN", "BOLT-M8") == 0


def test_R02_failed_reserve_leaves_no_order(inv):
    with pytest.raises(errors.InsufficientStockError):
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("NORTH", "BOLT-M8", 5)])
    with pytest.raises(errors.ReservationNotFoundError):
        inv.get_reservation("SO-1")
    r = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("NORTH", "BOLT-M8", 4)])
    assert r.status == S().ACTIVE


# --- R03: одинаковые позиции суммируются ---------------------------------------


def test_R03_duplicate_positions_summed_on_reserve(inv):
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.reserve("SO-1", [("MAIN", "NUT-M8", 3), ("MAIN", "NUT-M8", 3)])
    assert info.value.requested == 6
    assert info.value.available == 5
    assert inv.reserved("MAIN", "NUT-M8") == 0


def test_R03_duplicate_positions_fit_when_sum_fits(inv):
    r = inv.reserve("SO-1", [("MAIN", "NUT-M8", 2), ("MAIN", "NUT-M8", 3)])
    assert len(r.lines) == 2
    assert inv.reserved("MAIN", "NUT-M8") == 5
    assert inv.available("MAIN", "NUT-M8") == 0


def test_R03_confirm_checks_sum_of_lines(inv):
    inv.reserve("SO-1", [("MAIN", "NUT-M8", 2), ("MAIN", "NUT-M8", 2)])
    inv.adjust("MAIN", "NUT-M8", 3, "recount")
    with pytest.raises(errors.InsufficientStockError):
        inv.confirm("SO-1")
    assert inv.on_hand("MAIN", "NUT-M8") == 3
    assert inv.get_reservation("SO-1").status == S().ACTIVE


def test_R03_same_sku_in_different_warehouses_is_not_merged(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 10), ("NORTH", "BOLT-M8", 4)])
    assert inv.available("MAIN", "BOLT-M8") == 0
    assert inv.available("NORTH", "BOLT-M8") == 0


# --- R04: доступный остаток ----------------------------------------------------


def test_R04_available_is_on_hand_minus_active_reservations(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 2)])
    assert inv.reserved("MAIN", "BOLT-M8") == 5
    assert inv.available("MAIN", "BOLT-M8") == 5
    assert inv.on_hand("MAIN", "BOLT-M8") == 10
    assert inv.available("NORTH", "BOLT-M8") == 4


def test_R04_reserve_checks_available_not_on_hand(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.reserve("SO-2", [("MAIN", "BOLT-M8", 3)])
    assert info.value.available == 2
    inv.reserve("SO-3", [("MAIN", "BOLT-M8", 2)])
    assert inv.available("MAIN", "BOLT-M8") == 0


def test_R04_unknown_sku(inv):
    with pytest.raises(errors.UnknownSkuError):
        inv.available("MAIN", "NOPE")
    with pytest.raises(errors.UnknownSkuError):
        inv.reserved("MAIN", "NOPE")


def test_R04_registered_sku_without_stock(inv):
    assert inv.available("MAIN", "OIL-5L") == 0
    assert inv.reserved("MAIN", "OIL-5L") == 0
    with pytest.raises(errors.InsufficientStockError):
        inv.reserve("SO-1", [("MAIN", "OIL-5L", 1)])


# --- R05: TTL, ленивое истечение, окончательные статусы ------------------------


def test_R05_active_until_just_before_expiry(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=10 * MIN)
    clock.advance(10 * MIN - SEC)
    assert inv.get_reservation("SO-1").status == S().ACTIVE
    assert inv.reserved("MAIN", "BOLT-M8") == 3
    assert inv.available("MAIN", "BOLT-M8") == 7


def test_R05_expired_exactly_at_expires_at(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=10 * MIN)
    clock.advance(10 * MIN)
    assert inv.get_reservation("SO-1").status == S().EXPIRED
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert inv.available("MAIN", "BOLT-M8") == 10


def test_R05_expiry_writes_no_events(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=5 * MIN)
    start = len(inv.log)
    clock.advance(timedelta(hours=1))
    inv.available("MAIN", "BOLT-M8")
    inv.get_reservation("SO-1")
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 10)])
    kinds = [event.kind for event in new_events(inv, start)]
    assert kinds == ["RESERVE"]


def test_R05_terminal_statuses_survive_ttl(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=5 * MIN)
    inv.reserve("SO-2", [("MAIN", "NUT-M8", 1)], ttl=5 * MIN)
    inv.confirm("SO-1")
    inv.cancel("SO-2")
    clock.advance(timedelta(hours=1))
    assert inv.get_reservation("SO-1").status == S().CONFIRMED
    assert inv.get_reservation("SO-2").status == S().CANCELLED


def test_R05_expired_reservation_frees_stock_for_new_order(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 10)])
    with pytest.raises(errors.InsufficientStockError):
        inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)])
    clock.advance(timedelta(minutes=15))
    r = inv.reserve("SO-2", [("MAIN", "BOLT-M8", 10)])
    assert r.status == S().ACTIVE


# --- R06: подтверждение --------------------------------------------------------


def test_R06_confirm_ships_all_lines(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("NORTH", "BOLT-M8", 1), ("MAIN", "NUT-M8", 2)])
    r = inv.confirm("SO-1")
    assert r.status == S().CONFIRMED
    assert r.order_id == "SO-1"
    assert inv.on_hand("MAIN", "BOLT-M8") == 7
    assert inv.on_hand("NORTH", "BOLT-M8") == 3
    assert inv.on_hand("MAIN", "NUT-M8") == 3
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert inv.get_reservation("SO-1").status == S().CONFIRMED


def test_R06_confirm_works_when_everything_is_reserved(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 10)])
    assert inv.available("MAIN", "BOLT-M8") == 0
    inv.confirm("SO-1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 0


def test_R06_confirmed_reservation_is_not_double_counted(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 6)])
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 4)])
    inv.confirm("SO-1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 4
    assert inv.reserved("MAIN", "BOLT-M8") == 4
    assert inv.available("MAIN", "BOLT-M8") == 0
    inv.confirm("SO-2")
    assert inv.on_hand("MAIN", "BOLT-M8") == 0
    assert inv.available("MAIN", "BOLT-M8") == 0


def test_R06_confirm_just_before_expiry(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 2)], ttl=5 * MIN)
    clock.advance(5 * MIN - SEC)
    assert inv.confirm("SO-1").status == S().CONFIRMED
    assert inv.on_hand("MAIN", "BOLT-M8") == 8


# --- R07: ошибки подтверждения -------------------------------------------------


def test_R07_confirm_expired_raises_and_changes_nothing(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 2)])
    clock.advance(timedelta(minutes=15))
    start = len(inv.log)
    with pytest.raises(errors.ReservationExpiredError) as info:
        inv.confirm("SO-1")
    assert info.value.order_id == "SO-1"
    assert isinstance(info.value, errors.ReservationError)
    assert inv.on_hand("MAIN", "BOLT-M8") == 10
    assert len(inv.log) == start
    assert inv.get_reservation("SO-1").status == S().EXPIRED


def test_R07_confirm_twice_ships_once(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 2)])
    inv.confirm("SO-1")
    with pytest.raises(errors.ReservationStateError):
        inv.confirm("SO-1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 8


def test_R07_confirm_cancelled_rejected(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 2)])
    inv.cancel("SO-1")
    with pytest.raises(errors.ReservationStateError):
        inv.confirm("SO-1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 10


def test_R07_confirm_unknown_order(inv):
    with pytest.raises(errors.ReservationNotFoundError) as info:
        inv.confirm("SO-404")
    assert info.value.order_id == "SO-404"
    assert isinstance(info.value, errors.ReservationError)
    assert isinstance(info.value, errors.WarehouseError)


# --- R08: отмена ---------------------------------------------------------------


def test_R08_cancel_releases_stock(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 7)])
    r = inv.cancel("SO-1")
    assert r.status == S().CANCELLED
    assert inv.available("MAIN", "BOLT-M8") == 10
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert inv.on_hand("MAIN", "BOLT-M8") == 10


def test_R08_cancel_is_idempotent(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 7)])
    inv.cancel("SO-1")
    start = len(inv.log)
    r = inv.cancel("SO-1")
    assert r.status == S().CANCELLED
    assert len(inv.log) == start
    assert len(inv.log.events("RESERVE_CANCEL")) == 1


def test_R08_cancel_expired_is_noop(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 7)], ttl=5 * MIN)
    clock.advance(5 * MIN)
    start = len(inv.log)
    r = inv.cancel("SO-1")
    assert r.status == S().EXPIRED
    assert inv.get_reservation("SO-1").status == S().EXPIRED
    assert len(inv.log) == start


def test_R08_cancel_confirmed_rejected(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 2)])
    inv.confirm("SO-1")
    with pytest.raises(errors.ReservationStateError):
        inv.cancel("SO-1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 8
    assert inv.get_reservation("SO-1").status == S().CONFIRMED


def test_R08_cancel_unknown_order(inv):
    with pytest.raises(errors.ReservationNotFoundError):
        inv.cancel("SO-404")


# --- R09: продление ------------------------------------------------------------


def test_R09_extend_counts_from_now(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=10 * MIN)
    clock.advance(8 * MIN)
    r = inv.extend("SO-1", 10 * MIN)
    assert r.expires_at == T0 + 18 * MIN
    assert r.status == S().ACTIVE
    clock.advance(10 * MIN - SEC)
    assert inv.get_reservation("SO-1").status == S().ACTIVE
    clock.advance(SEC)
    assert inv.get_reservation("SO-1").status == S().EXPIRED


def test_R09_extend_never_shortens(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=30 * MIN)
    clock.advance(MIN)
    start = len(inv.log)
    r = inv.extend("SO-1", 5 * MIN)
    assert r.expires_at == T0 + 30 * MIN
    assert inv.get_reservation("SO-1").expires_at == T0 + 30 * MIN
    assert len(inv.log) == start


def test_R09_extend_expired_rejected(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=10 * MIN)
    clock.advance(10 * MIN)
    start = len(inv.log)
    with pytest.raises(errors.ReservationExpiredError):
        inv.extend("SO-1", 10 * MIN)
    assert inv.get_reservation("SO-1").status == S().EXPIRED
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert len(inv.log) == start


def test_R09_extend_confirmed_or_cancelled_rejected(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)])
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)])
    inv.confirm("SO-1")
    inv.cancel("SO-2")
    for order_id in ["SO-1", "SO-2"]:
        with pytest.raises(errors.ReservationStateError):
            inv.extend(order_id, 10 * MIN)
    with pytest.raises(errors.ReservationNotFoundError):
        inv.extend("SO-404", 10 * MIN)


def test_R09_extend_bad_ttl(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)], ttl=10 * MIN)
    for ttl in [timedelta(0), -MIN]:
        with pytest.raises(errors.ValidationError):
            inv.extend("SO-1", ttl)
    assert inv.get_reservation("SO-1").expires_at == T0 + 10 * MIN


# --- R10: повторный reserve на тот же заказ ------------------------------------


def test_R10_duplicate_active_rejected(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    start = len(inv.log)
    with pytest.raises(errors.DuplicateReservationError) as info:
        inv.reserve("SO-1", [("MAIN", "NUT-M8", 1)])
    assert info.value.order_id == "SO-1"
    assert inv.get_reservation("SO-1").lines == (L("MAIN", "BOLT-M8", 3),)
    assert inv.reserved("MAIN", "BOLT-M8") == 3
    assert inv.reserved("MAIN", "NUT-M8") == 0
    assert len(inv.log) == start


def test_R10_duplicate_confirmed_rejected(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.confirm("SO-1")
    with pytest.raises(errors.DuplicateReservationError):
        inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    assert inv.get_reservation("SO-1").status == S().CONFIRMED
    assert inv.reserved("MAIN", "BOLT-M8") == 0


def test_R10_reserve_again_after_expiry_replaces(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)], ttl=5 * MIN)
    clock.advance(5 * MIN)
    r = inv.reserve("SO-1", [("MAIN", "NUT-M8", 2)], ttl=5 * MIN)
    assert r.status == S().ACTIVE
    assert r.created_at == T0 + 5 * MIN
    assert r.expires_at == T0 + 10 * MIN
    assert r.lines == (L("MAIN", "NUT-M8", 2),)
    assert inv.get_reservation("SO-1").lines == (L("MAIN", "NUT-M8", 2),)
    assert inv.reserved("MAIN", "BOLT-M8") == 0
    assert inv.reserved("MAIN", "NUT-M8") == 2


def test_R10_reserve_again_after_cancel_replaces(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.cancel("SO-1")
    r = inv.reserve("SO-1", [("MAIN", "BOLT-M8", 9)])
    assert r.status == S().ACTIVE
    assert inv.reserved("MAIN", "BOLT-M8") == 9
    inv.confirm("SO-1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 1


# --- R11: журнал ---------------------------------------------------------------


def test_R11_reserve_event_lines_exact(inv):
    start = len(inv.log)
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("NORTH", "BOLT-M8", 1)])
    assert inv.log.lines()[start:] == [
        "000004 2026-03-01T10:00:00Z RESERVE expires=2026-03-01T10:15:00Z order=SO-1 qty=3 sku=BOLT-M8 wh=MAIN",
        "000005 2026-03-01T10:00:00Z RESERVE expires=2026-03-01T10:15:00Z order=SO-1 qty=1 sku=BOLT-M8 wh=NORTH",
    ]


def test_R11_confirm_writes_issue_per_line_then_confirm(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3), ("MAIN", "NUT-M8", 2)])
    clock.advance(2 * MIN)
    start = len(inv.log)
    inv.confirm("SO-1")
    events = new_events(inv, start)
    assert [event.kind for event in events] == ["ISSUE", "ISSUE", "RESERVE_CONFIRM"]
    assert dict(events[0].fields) == {"wh": "MAIN", "sku": "BOLT-M8", "qty": "3", "ref": "SO-1"}
    assert dict(events[1].fields) == {"wh": "MAIN", "sku": "NUT-M8", "qty": "2", "ref": "SO-1"}
    assert dict(events[2].fields) == {"order": "SO-1"}
    assert all(event.ts == T0 + 2 * MIN for event in events)


def test_R11_cancel_and_extend_events(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1)])
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 1)])
    clock.advance(5 * MIN)
    start = len(inv.log)
    inv.cancel("SO-1")
    inv.extend("SO-2", 20 * MIN)
    lines = inv.log.lines()[start:]
    assert lines == [
        "000006 2026-03-01T10:05:00Z RESERVE_CANCEL order=SO-1",
        "000007 2026-03-01T10:05:00Z RESERVE_EXTEND expires=2026-03-01T10:25:00Z order=SO-2",
    ]


def test_R11_all_lines_parse_back(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 1), ("MAIN", "NUT-M8", 1)], ttl=7 * MIN)
    clock.advance(MIN)
    inv.extend("SO-1", 30 * MIN)
    inv.confirm("SO-1")
    for line in inv.log.lines():
        event = parse_line(line)
        assert event.format() == line
        if "expires" in event.fields:
            assert parse_timestamp(event.fields["expires"]).tzinfo is not None
    expires = [parse_line(line).fields["expires"] for line in inv.log.lines() if "RESERVE_EXTEND" in line]
    assert expires == ["2026-03-01T10:31:00Z"]


def test_R11_failed_operations_write_nothing(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 9)], ttl=5 * MIN)
    start = len(inv.log)
    with pytest.raises(errors.InsufficientStockError):
        inv.reserve("SO-2", [("MAIN", "NUT-M8", 1), ("MAIN", "BOLT-M8", 2)])
    with pytest.raises(errors.DuplicateReservationError):
        inv.reserve("SO-1", [("MAIN", "NUT-M8", 1)])
    with pytest.raises(errors.InsufficientStockError):
        inv.issue("MAIN", "BOLT-M8", 2)
    clock.advance(5 * MIN)
    with pytest.raises(errors.ReservationExpiredError):
        inv.confirm("SO-1")
    with pytest.raises(errors.ReservationExpiredError):
        inv.extend("SO-1", MIN)
    assert len(inv.log) == start
    event = inv.log.events()[-1]
    inv.issue("MAIN", "BOLT-M8", 2, ref="SO-9")
    assert inv.log.events()[-1].seq == event.seq + 1


# --- R12: расход и перемещение уважают резервы ---------------------------------


def test_R12_issue_cannot_take_reserved_stock(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.issue("MAIN", "BOLT-M8", 3)
    assert info.value.available == 2
    assert info.value.requested == 3
    assert inv.on_hand("MAIN", "BOLT-M8") == 10
    assert inv.issue("MAIN", "BOLT-M8", 2) == 8
    assert inv.available("MAIN", "BOLT-M8") == 0
    assert inv.reserved("MAIN", "BOLT-M8") == 8


def test_R12_expired_reservations_do_not_block_issue(inv, clock):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)], ttl=5 * MIN)
    clock.advance(5 * MIN)
    assert inv.issue("MAIN", "BOLT-M8", 10) == 0


def test_R12_transfer_respects_source_reservations(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.transfer("MAIN", "NORTH", "BOLT-M8", 3)
    assert info.value.available == 2
    assert inv.on_hand("MAIN", "BOLT-M8") == 10
    assert inv.on_hand("NORTH", "BOLT-M8") == 4
    inv.transfer("MAIN", "NORTH", "BOLT-M8", 2)
    assert inv.on_hand("NORTH", "BOLT-M8") == 6


def test_R12_reservations_elsewhere_do_not_block(inv):
    inv.reserve("SO-1", [("NORTH", "BOLT-M8", 4), ("MAIN", "NUT-M8", 5)])
    assert inv.issue("MAIN", "BOLT-M8", 10) == 0
    with pytest.raises(errors.InsufficientStockError):
        inv.transfer("NORTH", "MAIN", "BOLT-M8", 1)


# --- R13: инвентаризация ниже резервов -----------------------------------------


def test_R13_adjust_below_reservations_available_is_zero(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    assert inv.adjust("MAIN", "BOLT-M8", 5, "recount") == 5
    assert inv.on_hand("MAIN", "BOLT-M8") == 5
    assert inv.reserved("MAIN", "BOLT-M8") == 8
    assert inv.available("MAIN", "BOLT-M8") == 0


def test_R13_confirm_with_physical_shortage_is_atomic(inv):
    inv.reserve("SO-1", [("MAIN", "NUT-M8", 2), ("MAIN", "BOLT-M8", 8)])
    inv.adjust("MAIN", "BOLT-M8", 5, "recount")
    start = len(inv.log)
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.confirm("SO-1")
    assert info.value.sku == "BOLT-M8"
    assert inv.on_hand("MAIN", "NUT-M8") == 5
    assert inv.on_hand("MAIN", "BOLT-M8") == 5
    assert inv.get_reservation("SO-1").status == S().ACTIVE
    assert inv.reserved("MAIN", "NUT-M8") == 2
    assert len(inv.log) == start


def test_R13_confirm_succeeds_after_restock(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    inv.adjust("MAIN", "BOLT-M8", 5, "recount")
    with pytest.raises(errors.InsufficientStockError):
        inv.confirm("SO-1")
    inv.receive("MAIN", "BOLT-M8", 3)
    assert inv.available("MAIN", "BOLT-M8") == 0
    inv.confirm("SO-1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 0


def test_R13_issue_blocked_when_on_hand_below_reservations(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 8)])
    inv.adjust("MAIN", "BOLT-M8", 5, "recount")
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.issue("MAIN", "BOLT-M8", 1)
    assert info.value.available == 0


# --- R14: отчёты и старые представления с резервами ----------------------------


def test_R14_on_hand_and_stock_levels_stay_physical(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 7), ("NORTH", "BOLT-M8", 4)])
    levels = {(level.warehouse, level.sku): level.on_hand for level in inv.stock_levels()}
    assert levels == {("MAIN", "BOLT-M8"): 10, ("MAIN", "NUT-M8"): 5, ("NORTH", "BOLT-M8"): 4}
    report = reports.stock_report(inv)
    assert "10 pcs" in report
    assert reports.stock_csv(inv).splitlines()[1] == "MAIN,BOLT-M8,10"


def test_R14_movement_summary_counts_confirmed_orders_as_issued(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 3)])
    inv.reserve("SO-2", [("MAIN", "BOLT-M8", 2)])
    inv.confirm("SO-1")
    summary = reports.movement_summary(inv.log)
    assert summary["BOLT-M8"].issued == 3
    assert summary["BOLT-M8"].received == 14


def test_R14_low_stock_uses_physical_quantities(inv):
    inv.reserve("SO-1", [("MAIN", "BOLT-M8", 9)])
    assert ("MAIN", "BOLT-M8", 10) not in reports.low_stock(inv, 10)
    inv.confirm("SO-1")
    assert ("MAIN", "BOLT-M8", 1) in reports.low_stock(inv, 10)


# --- обратная совместимость ----------------------------------------------------


def test_API_constructor_signature_unchanged():
    store, clock, log = InMemoryStore(), ManualClock(T0), EventLog()
    inventory = Inventory(store, clock, log)
    assert inventory.store is store
    assert inventory.clock is clock
    assert inventory.log is log
    default = Inventory()
    assert isinstance(default.clock, SystemClock)
    assert len(default.log) == 0


def test_API_old_operations_return_values(inv):
    assert inv.receive("MAIN", "OIL-5L", 4, ref="PO-3") == 4
    assert inv.issue("MAIN", "OIL-5L", 1, ref="SO-7") == 3
    assert inv.issue("MAIN", "OIL-5L", 1) == 2
    assert inv.transfer("MAIN", "NORTH", "OIL-5L", 1) is None
    assert inv.adjust("NORTH", "OIL-5L", 0, "damaged") == 0
    assert inv.on_hand("MAIN", "OIL-5L") == 1


def test_API_issue_shortage_without_reservations(inv):
    with pytest.raises(errors.InsufficientStockError) as info:
        inv.issue("MAIN", "NUT-M8", 6)
    assert (info.value.requested, info.value.available) == (6, 5)
    with pytest.raises(errors.InsufficientStockError):
        inv.transfer("NORTH", "MAIN", "BOLT-M8", 5)


def test_API_old_event_lines_unchanged(inv, clock):
    clock.advance(timedelta(minutes=3))
    inv.issue("MAIN", "BOLT-M8", 2, ref="SO-1")
    inv.transfer("MAIN", "NORTH", "NUT-M8", 1)
    assert inv.log.lines()[-2:] == [
        "000004 2026-03-01T10:03:00Z ISSUE qty=2 ref=SO-1 sku=BOLT-M8 wh=MAIN",
        "000005 2026-03-01T10:03:00Z TRANSFER dst=NORTH qty=1 ref=- sku=NUT-M8 src=MAIN",
    ]


def test_API_cli_scenario_still_works(tmp_path):
    from warehouse import cli

    scenario = [
        {"op": "register", "sku": "BOLT-M8", "name": "Bolt"},
        {"op": "receive", "wh": "MAIN", "sku": "BOLT-M8", "qty": 10},
        {"op": "issue", "wh": "MAIN", "sku": "BOLT-M8", "qty": 3, "ref": "SO-1"},
    ]
    path = tmp_path / "scenario.json"
    path.write_text(json.dumps(scenario), encoding="utf-8")
    out = io.StringIO()
    assert cli.main(["run", str(path), "--show", "csv"], out=out) == 0
    assert out.getvalue() == "warehouse,sku,on_hand\nMAIN,BOLT-M8,7\n"
