from datetime import timedelta

import pytest

from warehouse.errors import (
    DuplicateSkuError,
    InsufficientStockError,
    InvalidQuantityError,
    UnknownSkuError,
    ValidationError,
    WarehouseError,
)
from warehouse.models import StockLevel


def test_receive_increases_on_hand(inv):
    assert inv.receive("MAIN", "BOLT-M8", 10) == 10
    assert inv.receive("MAIN", "BOLT-M8", 5, ref="PO-1") == 15
    assert inv.on_hand("MAIN", "BOLT-M8") == 15


def test_on_hand_is_per_warehouse(inv):
    inv.receive("MAIN", "BOLT-M8", 10)
    assert inv.on_hand("NORTH", "BOLT-M8") == 0


def test_on_hand_unknown_sku(inv):
    with pytest.raises(UnknownSkuError):
        inv.on_hand("MAIN", "NOPE")


def test_register_duplicate_sku(inv):
    with pytest.raises(DuplicateSkuError):
        inv.register_sku("BOLT-M8", "again")


@pytest.mark.parametrize("qty", [0, -1, 1.5, True, "3"])
def test_receive_rejects_bad_quantity(inv, qty):
    with pytest.raises(InvalidQuantityError):
        inv.receive("MAIN", "BOLT-M8", qty)


def test_issue_decreases_on_hand(inv):
    inv.receive("MAIN", "BOLT-M8", 10)
    assert inv.issue("MAIN", "BOLT-M8", 4, ref="SO-1") == 6


def test_issue_more_than_on_hand(inv):
    inv.receive("MAIN", "BOLT-M8", 3)
    with pytest.raises(InsufficientStockError) as info:
        inv.issue("MAIN", "BOLT-M8", 4)
    assert (info.value.requested, info.value.available) == (4, 3)
    assert inv.on_hand("MAIN", "BOLT-M8") == 3
    assert len(inv.log) == 1


def test_issue_unknown_sku_is_warehouse_error(inv):
    with pytest.raises(WarehouseError):
        inv.issue("MAIN", "NOPE", 1)


def test_bad_ref_changes_nothing(inv):
    inv.receive("MAIN", "BOLT-M8", 3)
    with pytest.raises(ValidationError):
        inv.issue("MAIN", "BOLT-M8", 1, ref="SO 1")
    assert inv.on_hand("MAIN", "BOLT-M8") == 3
    assert len(inv.log) == 1


def test_transfer_moves_stock(inv):
    inv.receive("MAIN", "OIL-5L", 8)
    inv.transfer("MAIN", "NORTH", "OIL-5L", 3)
    assert inv.on_hand("MAIN", "OIL-5L") == 5
    assert inv.on_hand("NORTH", "OIL-5L") == 3


def test_transfer_insufficient(inv):
    inv.receive("MAIN", "OIL-5L", 2)
    with pytest.raises(InsufficientStockError):
        inv.transfer("MAIN", "NORTH", "OIL-5L", 3)
    assert inv.on_hand("NORTH", "OIL-5L") == 0


def test_transfer_same_warehouse(inv):
    inv.receive("MAIN", "OIL-5L", 2)
    with pytest.raises(ValidationError):
        inv.transfer("MAIN", "MAIN", "OIL-5L", 1)


def test_adjust_sets_counted_quantity(inv, clock):
    inv.receive("MAIN", "NUT-M8", 10)
    clock.advance(timedelta(hours=1))
    assert inv.adjust("MAIN", "NUT-M8", 7, "recount") == 7
    event = inv.log.events("ADJUST")[0]
    assert event.fields["delta"] == "-3"


def test_adjust_rejects_negative(inv):
    with pytest.raises(ValidationError):
        inv.adjust("MAIN", "NUT-M8", -1, "recount")


def test_stock_levels_sorted_and_filtered(inv):
    inv.receive("NORTH", "BOLT-M8", 1)
    inv.receive("MAIN", "NUT-M8", 2)
    inv.receive("MAIN", "BOLT-M8", 3)
    assert inv.stock_levels() == [
        StockLevel("MAIN", "BOLT-M8", 3),
        StockLevel("MAIN", "NUT-M8", 2),
        StockLevel("NORTH", "BOLT-M8", 1),
    ]
    assert inv.stock_levels("NORTH") == [StockLevel("NORTH", "BOLT-M8", 1)]


def test_zero_positions_disappear(inv):
    inv.receive("MAIN", "BOLT-M8", 2)
    inv.issue("MAIN", "BOLT-M8", 2)
    assert inv.stock_levels() == []
