import datetime as dt
from decimal import Decimal

import pytest

from ledger.errors import StorageError
from ledger.models import Transaction
from ledger.storage import JsonFileStore, MemoryStore


def _tx(desc="Кофе", amount="-100.00", day=1):
    return Transaction(dt.date(2026, 3, day), Decimal(amount), desc)


def test_memory_store_assigns_ids():
    store = MemoryStore()
    a = store.add(_tx("a"))
    b, c = store.add_many([_tx("b"), _tx("c")])
    assert [a.id, b.id, c.id] == [1, 2, 3]
    assert [t.description for t in store.all()] == ["a", "b", "c"]
    assert store.get(2).description == "b"


def test_add_many_is_all_or_nothing():
    store = MemoryStore()
    store.add(_tx("a"))
    with pytest.raises(StorageError):
        store.add_many([_tx("b"), "not a transaction"])
    assert [t.description for t in store.all()] == ["a"]


def test_add_rejects_transaction_with_id():
    store = MemoryStore()
    stored = store.add(_tx())
    with pytest.raises(StorageError):
        store.add(stored)


def test_json_store_persists_and_reloads(tmp_path):
    path = tmp_path / "ledger.json"
    store = JsonFileStore(path)
    store.add_many([_tx("a"), _tx("b", "250.50")])
    reloaded = JsonFileStore(path)
    assert [(t.id, t.description, t.amount) for t in reloaded.all()] == [
        (1, "a", Decimal("-100.00")),
        (2, "b", Decimal("250.50")),
    ]
    assert reloaded.add(_tx("c")).id == 3


def test_json_store_corrupted_file(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StorageError):
        JsonFileStore(path)


def test_update_category(tmp_path):
    store = JsonFileStore(tmp_path / "ledger.json")
    tx = store.add(_tx())
    store.update_category(tx.id, "food")
    assert JsonFileStore(tmp_path / "ledger.json").get(tx.id).category == "food"
    with pytest.raises(StorageError):
        store.update_category(999, "food")
