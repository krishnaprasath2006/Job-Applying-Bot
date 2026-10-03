"""SQLite infrastructure for the assistant.

Phase 2 creates the evidence backbone, profile storage, resume storage, and the
AI run audit trail. Job and application tables arrive in later phases, as
numbered migrations, when something actually uses them.
"""

from database.connection import Database, connect, row_to_dict

__all__ = ["Database", "connect", "row_to_dict"]
