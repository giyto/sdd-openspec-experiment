"""Хранилища транзакций.

MemoryStore держит всё в памяти, JsonFileStore дополнительно сохраняет
состояние в JSON-файл после каждого изменения (атомарно, через временный файл).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Iterable

from ledger.errors import StorageError
from ledger.models import Transaction

logger = logging.getLogger(__name__)


class MemoryStore:
    """Хранилище в памяти."""

    def __init__(self) -> None:
        self._items: list[Transaction] = []
        self._next_id = 1

    def all(self) -> list[Transaction]:
        return list(self._items)

    def get(self, tx_id: int) -> Transaction:
        for tx in self._items:
            if tx.id == tx_id:
                return tx
        raise StorageError(f"transaction {tx_id} not found")

    def add(self, tx: Transaction) -> Transaction:
        """Добавляет одну транзакцию и возвращает её с назначенным id."""
        return self.add_many([tx])[0]

    def add_many(self, txs: Iterable[Transaction]) -> list[Transaction]:
        """Добавляет пачку транзакций целиком: либо все, либо ни одной."""
        batch = list(txs)
        for tx in batch:
            if not isinstance(tx, Transaction):
                raise StorageError(f"not a Transaction: {tx!r}")
            if tx.id is not None:
                raise StorageError(f"transaction already has id {tx.id}")
        stored = []
        next_id = self._next_id
        for tx in batch:
            stored.append(replace(tx, id=next_id))
            next_id += 1
        self._commit(self._items + stored, next_id)
        logger.debug("added %d transactions", len(stored))
        return stored

    def update_category(self, tx_id: int, category: str | None) -> Transaction:
        items = []
        updated = None
        for tx in self._items:
            if tx.id == tx_id:
                updated = replace(tx, category=category)
                items.append(updated)
            else:
                items.append(tx)
        if updated is None:
            raise StorageError(f"transaction {tx_id} not found")
        self._commit(items, self._next_id)
        return updated

    def _commit(self, items: list[Transaction], next_id: int) -> None:
        self._items = items
        self._next_id = next_id


class JsonFileStore(MemoryStore):
    """Хранилище в JSON-файле. Файл создаётся при первой записи."""

    def __init__(self, path: str | os.PathLike[str]) -> None:
        super().__init__()
        self.path = Path(path)
        if self.path.exists():
            self._load()

    def _load(self) -> None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self._items = [Transaction.from_dict(d) for d in data["transactions"]]
            self._next_id = int(data["next_id"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise StorageError(f"cannot read {self.path}: {exc}") from exc
        logger.debug("loaded %d transactions from %s", len(self._items), self.path)

    def _commit(self, items: list[Transaction], next_id: int) -> None:
        payload = {
            "next_id": next_id,
            "transactions": [tx.to_dict() for tx in items],
        }
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".ledger-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, self.path)
        except OSError as exc:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise StorageError(f"cannot write {self.path}: {exc}") from exc
        super()._commit(items, next_id)
