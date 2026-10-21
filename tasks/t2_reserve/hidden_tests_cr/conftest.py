from datetime import datetime, timezone

import pytest

from warehouse.clock import ManualClock
from warehouse.inventory import Inventory

T0 = datetime(2026, 3, 1, 10, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock(T0)


@pytest.fixture
def inv(clock: ManualClock) -> Inventory:
    """MAIN: BOLT-M8=10, NUT-M8=5; NORTH: BOLT-M8=4; OIL-5L зарегистрирован, но без остатка."""
    inventory = Inventory(clock=clock)
    inventory.register_sku("BOLT-M8", "Bolt M8")
    inventory.register_sku("NUT-M8", "Nut M8")
    inventory.register_sku("OIL-5L", "Oil 5L", unit="can")
    inventory.receive("MAIN", "BOLT-M8", 10, ref="PO-1")
    inventory.receive("MAIN", "NUT-M8", 5, ref="PO-1")
    inventory.receive("NORTH", "BOLT-M8", 4, ref="PO-2")
    return inventory
