"""SQLite connection management.

Phase 2 tables, created in migration 001:

* ``schema_migrations``   - applied migration records
* ``documents``           - any source document (resume, profile, job text)
* ``candidate_profiles``  - one row per profile
* ``candidate_facts``     - one row per fact, with evidence columns
* ``evidence``            - one row per evidence record
* ``resumes``             - one row per ingested resume
* ``resume_sections``     - structured sections extracted from a resume
* ``model_runs``          - AI call metadata

Future tables (jobs, job_requirements, job_matches, applications,
application_answers, application_events, application_reviews,
question_memory) are **not** created. The migration mechanism is here so that
adding them later is a numbered file and not a redesign.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Optional

from core.errors import DatabaseError, MigrationError
from core.hashing import utc_now
from core.logging_config import get_logger, log_event

log = get_logger(__name__)

__all__ = ["Database", "connect", "row_to_dict"]

_log = get_logger("database.connection")

_MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[dict[str, Any]]:
    """Convert a ``sqlite3.Row`` to a plain dict."""
    return None if row is None else {k: row[k] for k in row.keys()}


class Database:
    """A thin, explicit wrapper over ``sqlite3``.

    Deliberately not an ORM. Phase 2 needs five tables and precise control over
    foreign keys; an ORM would add a dependency and a layer of indirection
    without removing any of the work.

    Thread safety: SQLite connections are bound to the creating thread, so this
    class serialises access with a lock and hands out per-thread connections.
    """

    def __init__(
        self,
        path: Path | str,
        *,
        enable_wal: bool = True,
        busy_timeout_seconds: float = 5.0,
        enable_foreign_keys: bool = True,
    ) -> None:
        self.path = Path(path)
        self.enable_wal = enable_wal
        self.busy_timeout_seconds = busy_timeout_seconds
        self.enable_foreign_keys = enable_foreign_keys
        self._local = threading.local()
        self._write_lock = threading.RLock()
        self._all_connections: list[sqlite3.Connection] = []

    # -- connection lifecycle ------------------------------------------------
    def _configure(self, conn: sqlite3.Connection) -> sqlite3.Connection:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON" if self.enable_foreign_keys else "PRAGMA foreign_keys = OFF")
        conn.execute(f"PRAGMA busy_timeout = {int(self.busy_timeout_seconds * 1000)}")
        if self.enable_wal and self.path != Path(":memory:"):
            try:
                conn.execute("PRAGMA journal_mode = WAL")
            except sqlite3.DatabaseError as exc:
                # WAL is a durability/concurrency optimisation, not a
                # correctness requirement. Some filesystems (network shares,
                # FAT, read-only mounts) refuse it. Log it and continue on the
                # default journal rather than refusing to open the database.
                log.warning(
                    "could not enable WAL journal mode, continuing with the default",
                    extra={"database": {"path": str(self.path), "error": str(exc)}},
                )
        return conn

    @property
    def connection(self) -> sqlite3.Connection:
        """Return this thread's connection, creating it on first use."""
        existing = getattr(self._local, "conn", None)
        if existing is not None:
            return existing
        if str(self.path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            # isolation_level=None puts the connection in autocommit mode, so a
            # single INSERT via execute() is durable immediately. Multi-statement
            # work is wrapped in the explicit transaction() context manager.
            conn = sqlite3.connect(str(self.path), timeout=self.busy_timeout_seconds, isolation_level=None)
        except sqlite3.Error as exc:
            raise DatabaseError("could not open database", path=str(self.path), cause=str(exc)) from exc
        self._configure(conn)
        self._local.conn = conn
        self._all_connections.append(conn)
        return conn

    def close(self) -> None:
        """Close every connection this instance created."""
        errors: list[str] = []
        for conn in self._all_connections:
            try:
                conn.close()
            except sqlite3.Error as exc:  # pragma: no cover - close rarely fails
                errors.append(str(exc))
        self._all_connections.clear()
        self._local = threading.local()
        if errors:
            # Report the failures instead of dropping them on the floor.
            log.warning(
                "some database connections failed to close cleanly",
                extra={"database": {"closed_with_errors": len(errors), "errors": errors}},
            )

    def __enter__(self) -> "Database":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- primitives ----------------------------------------------------------
    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        """Run one statement.

        Raises:
            DatabaseError: If the statement fails. The original
                ``sqlite3`` error is attached as the cause.
        """
        with self._write_lock:
            try:
                return self.connection.execute(sql, params)
            except sqlite3.Error as exc:
                raise DatabaseError(
                    "statement failed",
                    sql=sql.strip().split("\n")[0][:120],
                    cause=str(exc),
                ) from exc

    def executemany(self, sql: str, seq_of_params: Any) -> sqlite3.Cursor:
        with self._write_lock:
            try:
                return self.connection.executemany(sql, seq_of_params)
            except sqlite3.Error as exc:
                raise DatabaseError("bulk statement failed", cause=str(exc)) from exc

    def query(self, sql: str, params: Any = ()) -> list[dict[str, Any]]:
        """Run a SELECT and return all rows as dicts."""
        with self._write_lock:
            try:
                cur = self.connection.execute(sql, params)
                return [dict(r) for r in cur.fetchall()]
            except sqlite3.Error as exc:
                raise DatabaseError("query failed", cause=str(exc)) from exc

    def query_one(self, sql: str, params: Any = ()) -> Optional[dict[str, Any]]:
        with self._write_lock:
            try:
                cur = self.connection.execute(sql, params)
                row = cur.fetchone()
                return None if row is None else {k: row[k] for k in row.keys()}
            except sqlite3.Error as exc:
                raise DatabaseError("query failed", cause=str(exc)) from exc

    def scalar(self, sql: str, params: Any = ()) -> Any:
        """Return the first column of the first row, or ``None``."""
        with self._write_lock:
            try:
                cur = self.connection.execute(sql, params)
                row = cur.fetchone()
                return None if row is None else row[0]
            except sqlite3.Error as exc:
                raise DatabaseError("scalar query failed", cause=str(exc)) from exc

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Context manager wrapping statements in a single transaction.

        Every exit path either commits or rolls back, and the original
        exception is always re-raised so a failed write never looks successful.

        Raises:
            DatabaseError: If the body raises a SQLite error, or the commit fails.
        """
        conn = self.connection
        with self._write_lock:
            try:
                conn.execute("BEGIN")
                yield conn
                conn.commit()
            except sqlite3.Error as exc:
                self._safe_rollback(conn, context="sqlite failure")
                raise DatabaseError("transaction failed", cause=str(exc)) from exc
            except BaseException:
                self._safe_rollback(conn, context="body raised")
                raise

    def _safe_rollback(self, conn: sqlite3.Connection, *, context: str) -> None:
        """Roll back, never letting a rollback failure hide the real error."""
        try:
            conn.rollback()
        except sqlite3.Error as exc:  # pragma: no cover - rollback rarely fails
            log.error(
                "rollback failed while handling a transaction failure",
                extra={"database": {"context": context, "error": str(exc)}},
            )

    # -- migrations ----------------------------------------------------------
    def initialize(self, *, migrations_dir: Path | None = None) -> list[str]:
        """Create the schema if absent and apply pending migrations.

        Idempotent: safe to call on every startup.

        Returns:
            Names of the migrations applied during this call, empty when the
            database was already current.

        Raises:
            MigrationError: If any migration fails.
        """
        started = utc_now()
        directory = migrations_dir or _MIGRATIONS_DIR
        applied = self._apply_migrations(directory)
        log_event(
            _log,
            "database.initialized",
            duration_ms=int((utc_now() - started).total_seconds() * 1000),
            path=str(self.path),
            applied=applied,
        )
        return applied

    def _apply_migrations(self, directory: Path) -> list[str]:
        bootstrap = (
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "  version TEXT PRIMARY KEY,"
            "  applied_at TEXT NOT NULL"
            ")"
        )
        self.execute(bootstrap)

        already = {row["version"] for row in self.query("SELECT version FROM schema_migrations")}
        pending = [f for f in sorted(directory.glob("*.sql")) if f.stem not in already]
        applied: list[str] = []

        for sql_file in pending:
            try:
                script = sql_file.read_text(encoding="utf-8")
                with self._write_lock:
                    # executescript() issues its own COMMIT before running, so it
                    # cannot live inside our transaction(). Run it on its own, then
                    # record the version in a separate explicit transaction.
                    self.connection.executescript(self._guard_add_columns(script))
                with self.transaction() as conn:
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)",
                        (sql_file.stem, utc_now().isoformat()),
                    )
            except Exception as exc:
                raise MigrationError(
                    "migration failed",
                    version=sql_file.stem,
                    cause=str(exc),
                ) from exc
            applied.append(sql_file.stem)
        return applied

    _ADD_COLUMN = re.compile(
        r"^\s*ALTER\s+TABLE\s+(?P<table>[\w.\"`]+)\s+ADD\s+COLUMN\s+(?P<column>[\w.\"`]+)",
        re.IGNORECASE,
    )

    def _guard_add_columns(self, script: str) -> str:
        """Skip ``ALTER TABLE ... ADD COLUMN`` for columns that already exist.

        SQLite has no ``ADD COLUMN IF NOT EXISTS``. A migration file is applied
        exactly once, so this only matters for two real cases: a development
        database where a column was added by hand, and a database created after
        001 was patched in place. Skipping an already-present column keeps both
        cases from failing with "duplicate column name" while still applying
        every statement that has real work to do.

        No statement is dropped silently: each skip is logged with the column
        name so the migration log shows exactly what happened.
        """
        existing: dict[str, set[str]] = {}
        out: list[str] = []
        for line in script.splitlines(keepends=True):
            match = self._ADD_COLUMN.match(line)
            if match:
                table = match.group("table").strip('"`')
                column = match.group("column").strip('"`')
                if table not in existing:
                    existing[table] = {
                        str(c).strip('"`') for c in self.column_names(table)
                    }
                if column in existing[table]:
                    log.info(
                        "migration column already present, skipping ADD COLUMN",
                        extra={"database": {"table": table, "column": column}},
                    )
                    continue
                existing[table].add(column)
            out.append(line)
        return "".join(out)

    def table_names(self) -> list[str]:
        """Return user table names, excluding SQLite internals."""
        rows = self.query(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        return [r["name"] for r in rows]

    def column_names(self, table: str) -> list[str]:
        """Return column names for ``table``.

        Raises:
            DatabaseError: If the table does not exist.
        """
        rows = self.query(f"PRAGMA table_info({table})")  # noqa: S608 - table name is internal
        return [r["name"] for r in rows]

    def count(self, table: str) -> int:
        return int(self.scalar(f"SELECT COUNT(*) FROM {table}") or 0)  # noqa: S608


def connect(
    path: Path | str,
    *,
    enable_wal: bool = True,
    busy_timeout_seconds: float = 5.0,
    enable_foreign_keys: bool = True,
) -> Database:
    """Open (and migrate) a database.

    Raises:
        DatabaseError: If the database cannot be opened or migrated.
    """
    db = Database(
        path,
        enable_wal=enable_wal,
        busy_timeout_seconds=busy_timeout_seconds,
        enable_foreign_keys=enable_foreign_keys,
    )
    db.initialize()
    return db
