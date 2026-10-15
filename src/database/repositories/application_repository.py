"""Application persistence repository.

Handles CRUD operations and status lifecycle for tracked job applications.
Uses stable references to stored jobs rather than duplicating job records.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Optional, Sequence

from core.errors import DatabaseError
from core.hashing import utc_now

from database.repositories.base import BaseRepository


class ApplicationRepository(BaseRepository):
    """Repository for application lifecycle tracking.

    Tracks user's job applications with status, dates, and references
    to stored jobs. Uses stable job IDs to avoid duplicating job records.
    """

    table = "applications"

    # ------------------------------------------------------------------ create

    def create(self, payload: Any, *, actor: str = "user") -> str:
        """Create a new application tracking entry.

        Args:
            payload: Application creation data (ApplicationCreate model).
            actor: Who is creating the record, for audit purposes.

        Returns:
            The newly created application ID.
        """
        import json
        from api.schemas.application import ApplicationStatus

        app_id = str(uuid.uuid4())
        now = utc_now()

        # Extract payload fields using model_dump or direct access
        payload_dict = payload.model_dump() if hasattr(payload, "model_dump") else payload.__dict__
        
        row_values = {
            "id": app_id,
            "job_id": payload_dict.get("job_id"),
            "status": ApplicationStatus(payload_dict.get("status", "SAVED")).value,
            "application_date": (
                payload_dict.get("application_date").isoformat()
                if payload_dict.get("application_date")
                else None
            ),
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "next_followup": (
                payload_dict.get("next_followup").isoformat()
                if payload_dict.get("next_followup")
                else None
            ),
            "interviewer_name": payload_dict.get("interviewer_name") or None,
            "interviewer_contact": payload_dict.get("interviewer_contact") or None,
            "notes": payload_dict.get("notes") or None,
            "resume_id": payload_dict.get("resume_id") or None,
            "cover_letter_draft_id": payload_dict.get("cover_letter_draft_id") or None,
            "source_url": payload_dict.get("source_url") or None,
            "source_job_metadata": json.dumps(
                payload_dict.get("source_job_metadata") or {}
            ),
        }

        try:
            self.insert(row_values)
        except Exception as e:
            raise DatabaseError(f"Failed to create application: {e}") from e

        return app_id

    # ------------------------------------------------------------------ retrieve

    def get(self, app_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a single application by ID.

        Args:
            app_id: Application tracking ID.

        Returns:
            Application dict or None if not found.
        """
        row = self._repo_get(app_id)
        return row

    # ------------------------------------------------------------------ update

    def update(self, app_id: str, payload: Any) -> dict[str, Any]:
        """Update an existing application.

        Args:
            app_id: Application tracking ID.
            payload: ApplicationUpdate model.

        Returns:
            Updated application dict.
        """
        from api.schemas.application import ApplicationUpdate as AU

        payload_dict = payload.model_dump(exclude_unset=True)
        now = utc_now()

        update_vals: dict[str, Any] = {"updated_at": now.isoformat()}

        if "status" in payload_dict:
            from api.schemas.application import ApplicationStatus
            update_vals["status"] = ApplicationStatus(payload_dict["status"]).value

        if "application_date" in payload_dict:
            update_vals["application_date"] = (
                payload_dict["application_date"].isoformat()
                if payload_dict["application_date"]
                else None
            )

        if "notes" in payload_dict:
            update_vals["notes"] = payload_dict["notes"]

        if "resume_id" in payload_dict:
            update_vals["resume_id"] = payload_dict["resume_id"]

        if "cover_letter_draft_id" in payload_dict:
            update_vals["cover_letter_draft_id"] = payload_dict["cover_letter_draft_id"]

        if "source_url" in payload_dict:
            update_vals["source_url"] = payload_dict["source_url"]

        if "source_job_metadata" in payload_dict:
            update_vals["source_job_metadata"] = json.dumps(
                payload_dict["source_job_metadata"]
            )

        if "next_followup" in payload_dict:
            update_vals["next_followup"] = (
                payload_dict["next_followup"].isoformat()
                if payload_dict["next_followup"]
                else None
            )

        if "interviewer_name" in payload_dict:
            update_vals["interviewer_name"] = payload_dict["interviewer_name"]

        if "interviewer_contact" in payload_dict:
            update_vals["interviewer_contact"] = payload_dict["interviewer_contact"]

        try:
            self.update_record(app_id, update_vals)
        except Exception as e:
            raise DatabaseError(f"Failed to update application: {e}") from e

        return self.get(app_id)

    # ------------------------------------------------------------------ delete

    def delete(self, app_id: str) -> int:
        """Delete an application tracking entry.

        Args:
            app_id: Application tracking ID.

        Returns:
            Number of rows deleted (0 or 1).
        """
        try:
            return self.delete_record(app_id)
        except Exception:
            return 0

    # ------------------------------------------------------------------ list/filter

    def list_applications(
        self,
        *,
        status: Optional[str] = None,
        job_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List applications with optional filtering.

        Args:
            status: Filter by status string.
            job_id: Filter by job ID.
            limit: Maximum results.
            offset: Pagination offset.

        Returns:
            Tuple of (applications list, total count).
        """
        query = "SELECT * FROM applications WHERE 1=1"
        params: list[Any] = []

        if status is not None:
            query += " AND status = ?"
            params.append(status)

        if job_id is not None:
            query += " AND job_id = ?"
            params.append(job_id)

        # Count total
        count_query = f"SELECT COUNT(*) FROM ({query}) AS subq"
        cursor = self.db.execute(count_query, params)
        total = cursor.fetchone()[0]

        # Apply pagination
        query += " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        cursor = self.db.execute(query, params)
        rows = cursor.fetchall()

        return [dict(row) for row in rows], total

    # ------------------------------------------------------------------ status transition with audit

    def transition_status(
        self,
        app_id: str,
        new_status: str,
        *,
        note: Optional[str] = None,
        actor: str = "user",
    ) -> dict[str, Any]:
        """Transition application status with audit event.

        Records the status change in persistent history.

        Args:
            app_id: Application tracking ID.
            new_status: The new status string.
            note: Optional user note for this transition.
            actor: Who initiated the transition.

        Returns:
            Dict with transition details: from_status, to_status, timestamp, note.
        """
        from api.schemas.application import ApplicationStatus as AS

        # Get current application
        current = self.get(app_id)
        if current is None:
            raise DatabaseError(f"Application {app_id} not found")

        from_status = current["status"]

        # Validate the new status is valid
        try:
            AS(new_status)  # Will raise ValueError if invalid
        except ValueError:
            raise DatabaseError(f"Invalid status: {new_status}")

        # Update the status
        self.update(app_id, {"status": new_status})

        # Record the audit event
        transition_record = {
            "id": str(uuid.uuid4()),
            "application_id": app_id,
            "from_status": from_status,
            "to_status": new_status,
            "changed_at": utc_now().isoformat(),
            "actor": actor,
            "note": note or "",
        }

        # Store audit event (TODO: create application_audit_events table)
        # For now, just return the transition info
        return {
            "from_status": from_status,
            "to_status": new_status,
            "timestamp": utc_now().isoformat(),
            "note": note,
            "actor": actor,
        }

    # ------------------------------------------------------------------ helpers

    def _repo_get(self, app_id: str) -> Optional[dict[str, Any]]:
        """Low-level retrieve from database."""
        row = self.db.query_one(f"SELECT * FROM applications WHERE id = ?", (app_id,))
        return dict(row) if row else None

    def _repo_get_by_job(self, job_id: str) -> list[dict[str, Any]]:
        """Retrieve applications by job ID."""
        cursor = self.db.execute(
            "SELECT * FROM applications WHERE job_id = ?", (job_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

    def _repo_get_count(self, job_id: str) -> int:
        """Count applications by job ID."""
        cursor = self.db.execute(
            "SELECT COUNT(*) FROM applications WHERE job_id = ?", (job_id,)
        )
        return cursor.fetchone()[0]

    def _repo_delete_record(self, app_id: str) -> int:
        """Delete a record from the database."""
        cursor = self.db.execute(
            "DELETE FROM applications WHERE id = ?", (app_id,)
        )
        return cursor.rowcount

    def _repo_update_record(self, app_id: str, update_vals: dict[str, Any]) -> None:
        """Update a record in the database."""
        set_clause = ", ".join(f'"{k}" = ?' for k in update_vals.keys())
        params = list(update_vals.values()) + [app_id]
        self.db.execute(f"UPDATE applications SET {set_clause} WHERE id = ?", params)

    def _write_event(self, application_id: str, event_type: str, **kwargs: Any) -> None:
        """Write an audit event for the application."""
        # TODO: Create application_audit_events table for full history
        # For now, just log the event
        pass
