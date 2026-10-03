"""Shared repository plumbing.

Keeps SQL and JSON encoding in one place so each repository deals only in
domain objects. Row mapping is explicit rather than reflective: a column added
to a migration should not silently change the shape of a model.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Iterable, Optional, Sequence

from core.errors import DatabaseError
from core.hashing import utc_now
from database.connection import Database

__all__ = [
    "BaseRepository",
    "from_json_text",
    "new_id",
    "row_get",
    "to_json_text",
]


def row_get(row: Any, key: str, default: Any = None) -> Any:
    """Read ``key`` from a ``sqlite3.Row`` without raising if the column is absent.

    Migrations add columns over time, so a row read from an older database file
    can legitimately lack a column that the current model has. ``sqlite3.Row``
    has no ``.get``, so this keeps that case explicit and defaulted instead of
    turning it into a ``KeyError``.
    """
    if row is None:
        return default
    try:
        value = row[key]
    except (KeyError, IndexError):
        return default
    return default if value is None else value


def new_id(prefix: str = "") -> str:
    """Return a fresh identifier, optionally prefixed.

    Prefixed ids (``resume-...``, ``evidence-...``) make log lines and SQL
    foreign-key debugging readable without a lookup.
    """
    token = uuid.uuid4().hex
    return f"{prefix}-{token}" if prefix else token


def to_json_text(value: Any) -> Optional[str]:
    """Serialise a Python value for a TEXT column.

    Returns ``None`` for ``None`` so that "no value" and "the string null" stay
    distinguishable.
    """
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, default=str)


def from_json_text(raw: Optional[str], default: Any = None) -> Any:
    """Deserialise a TEXT column written by :func:`to_json_text`."""
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise DatabaseError("could not decode JSON column", cause=str(exc)) from exc


class BaseRepository:
    """Common helpers for table access.

    Attributes:
        db: The :class:`~database.connection.Database` this repository uses.
        table: The table this repository owns.
        id_prefix: Prefix used by :meth:`new_id`.
    """

    table: str = ""
    id_prefix: str = ""

    def __init__(self, db: Database) -> None:
        self.db = db

    def new_id(self) -> str:
        return new_id(self.id_prefix)

    def now(self) -> str:
        return utc_now().isoformat()

    def insert(self, values: dict[str, Any]) -> str:
        """Insert one row and return its id.

        Raises:
            DatabaseError: If the insert fails.
        """
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        sql = (
            f"INSERT INTO {self.table} ({', '.join(columns)}) VALUES ({placeholders})"  # noqa: S608
        )
        self.db.execute(sql, tuple(values[c] for c in columns))
        return str(values[self.primary_key])

    def update(self, row_id: str, values: dict[str, Any]) -> None:
        """Update the named columns of one row.

        Raises:
            DatabaseError: If the update fails.
        """
        if not values:
            return
        assignments = ", ".join(f"{c} = ?" for c in values)
        sql = f"UPDATE {self.table} SET {assignments} WHERE {self.primary_key} = ?"  # noqa: S608
        self.db.execute(sql, (*values.values(), row_id))

    primary_key: str = "id"

    def get(self, row_id: str) -> Optional[dict[str, Any]]:
        """Fetch one row by primary key, or ``None``."""
        return self.db.query_one(
            f"SELECT * FROM {self.table} WHERE {self.primary_key} = ?",  # noqa: S608
            (row_id,),
        )

    def delete(self, row_id: str) -> int:
        """Delete one row, returning how many were removed."""
        cursor = self.db.execute(
            f"DELETE FROM {self.table} WHERE {self.primary_key} = ?",  # noqa: S608
            (row_id,),
        )
        return cursor.rowcount

    def exists(self, row_id: str) -> bool:
        return (
            self.db.scalar(
                f"SELECT 1 FROM {self.table} WHERE {self.primary_key} = ? LIMIT 1",  # noqa: S608
                (row_id,),
            )
            is not None
        )

    def count(self) -> int:
        return self.db.count(self.table)

    def all(self, limit: Optional[int] = None) -> list[dict[str, Any]]:
        sql = f"SELECT * FROM {self.table} ORDER BY rowid"  # noqa: S608
        if limit:
            sql += f" LIMIT {int(limit)}"
        return self.db.query(sql)

    def upsert(self, values: dict[str, Any], conflict_column: str) -> None:
        """Insert, or update the non-key columns when the row already exists.

        ``table`` and ``conflict_column`` must be named explicitly by the
        caller. A repository may own several tables (a profile writes to both
        ``candidate_profiles`` and ``candidate_facts``), so neither can be
        inferred from ``self.table`` alone.

        Raises:
            DatabaseError: If the statement fails.
        """
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != conflict_column)
        sql = (
            f"INSERT INTO {self.table} ({', '.join(columns)}) VALUES ({placeholders}) "  # noqa: S608
            f"ON CONFLICT({conflict_column}) DO UPDATE SET {updates}"
        )
        self.db.execute(sql, tuple(values[c] for c in columns))

    def upsert_into(
        self, table: str, values: dict[str, Any], *, conflict_column: str = "id"
    ) -> None:
        """Insert or update a row in ``table``, keyed on ``conflict_column``.

        Use this for the secondary tables a repository owns, where the
        repository's own ``table`` attribute does not apply.
        """
        columns = list(values)
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != conflict_column)
        sql = (
            f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders}) "  # noqa: S608
            f"ON CONFLICT({conflict_column}) DO UPDATE SET {updates}"
        )
        self.db.execute(sql, tuple(values[c] for c in columns))

    def _placeholders(self, count: int) -> str:
        return ", ".join("?" for _ in range(count))

    def _in_clause(self, ids: Sequence[str]) -> str:
        if not ids:
            return "(NULL)"
        return "(" + self._placeholders(len(ids)) + ")"
