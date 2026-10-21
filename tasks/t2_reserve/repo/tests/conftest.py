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
    inventory = Inventory(clock=clock)
    inventory.register_sku("BOLT-M8", "Болт М8")
    inventory.register_sku("NUT-M8", "Гайка М8")
    inventory.register_sku("OIL-5L", "Масло 5 л", unit="can")
    return inventory
