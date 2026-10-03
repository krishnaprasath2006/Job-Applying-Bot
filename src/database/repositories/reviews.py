"""Review lifecycle: one open question per posting, with an answer slot.

The queue itself reads from ``job_matches`` - a verdict needing a human is
a property of the match. This repository owns the *other* half: that a
human looked, what they were shown, and when the doubt stopped being
open. One row per ``job_id`` + ``candidate_id``, because a posting either
waits for this candidate or it does not.

The transition rules live in :meth:`record` and :meth:`resolve`:

* No row - open one with the current doubt.
* An ``OPEN`` row - refresh the doubt (decision, reasons, supporting
  facts); it stays open, ``updated_at`` moves.
* A ``RESOLVED`` row whose doubt is *unchanged* - stays resolved. A
  re-match that repeats the question someone already answered is not a
  new question.
* A ``RESOLVED`` row whose doubt *changed* - reopens: the new doubt has
  no answer yet, and pretending otherwise would hide it.
* Nothing to capture - :meth:`clear` closes an open row if one exists,
  so a doubt the analysis no longer raises does not linger.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence, Union

from core.enums import MatchDecision, ReviewReason
from core.logging_config import get_logger
from database.repositories.base import (
    BaseRepository,
    from_json_text,
    to_json_text,
)

__all__ = ["ReviewRepository"]

log = get_logger(__name__)

ReviewId = str


class ReviewRepository(BaseRepository):
    """The ``job_reviews`` table: capture, resolve, and read back."""

    table = "job_reviews"
    id_prefix = "review"

    # -- capture ------------------------------------------------------------
    def record(
        self,
        *,
        job_id: str,
        candidate_id: str,
        decision: Union[MatchDecision, str],
        reasons: Sequence[Union[ReviewReason, str]],
        supporting: Optional[Mapping[str, Any]] = None,
    ) -> ReviewId:
        """Open or refresh the review for one posting.

        Returns:
            The review row's id. Whether it was inserted, refreshed, or
            reopened is logged, not returned - callers care that the
            doubt is on record, not which branch wrote it.
        """
        decision_value = (
            decision.value if isinstance(decision, MatchDecision) else str(decision)
        )
        reason_values = [
            reason.value if isinstance(reason, ReviewReason) else str(reason)
            for reason in reasons
        ]
        supporting_json = to_json_text(dict(supporting or {})) or "{}"
        existing = self.find(job_id, candidate_id)
        now = self.now()

        if existing is None:
            review_id = self.new_id()
            self.insert(
                {
                    "id": review_id,
                    "job_id": job_id,
                    "candidate_id": candidate_id,
                    "decision": decision_value,
                    "reasons": to_json_text(reason_values),
                    "supporting": supporting_json,
                    "status": "OPEN",
                    "created_at": now,
                    "updated_at": now,
                    "resolved_at": None,
                    "resolution": None,
                }
            )
            log.info(
                "review opened",
                extra={"job": {"id": job_id}, "review": {"id": review_id}},
            )
            return review_id

        same_doubt = (
            existing.get("decision") == decision_value
            and from_json_text(existing.get("reasons"), []) == reason_values
        )
        if existing.get("status") == "RESOLVED" and same_doubt:
            # The question was asked, answered, and nothing about it moved.
            return str(existing["id"])

        if existing.get("status") == "RESOLVED":
            self.update(
                str(existing["id"]),
                {
                    "decision": decision_value,
                    "reasons": to_json_text(reason_values),
                    "supporting": supporting_json,
                    "status": "OPEN",
                    "updated_at": now,
                    "resolved_at": None,
                    "resolution": None,
                },
            )
            log.info(
                "review reopened with a new doubt",
                extra={"job": {"id": job_id}, "review": {"id": existing["id"]}},
            )
            return str(existing["id"])

        self.update(
            str(existing["id"]),
            {
                "decision": decision_value,
                "reasons": to_json_text(reason_values),
                "supporting": supporting_json,
                "updated_at": now,
            },
        )
        return str(existing["id"])

    def clear(
        self, job_id: str, candidate_id: str, *, note: str
    ) -> bool:
        """Resolve the open review, if one exists - the doubt is gone.

        Returns:
            ``True`` when an open row was closed, ``False`` when there
            was nothing open to close (never a review, or already
            resolved). A resolved row is never rewritten by a clean
            re-match: its answer stands.
        """
        existing = self.find(job_id, candidate_id)
        if existing is None or existing.get("status") != "OPEN":
            return False
        now = self.now()
        self.update(
            str(existing["id"]),
            {
                "status": "RESOLVED",
                "updated_at": now,
                "resolved_at": now,
                "resolution": note,
            },
        )
        log.info(
            "review closed: the doubt is gone",
            extra={"job": {"id": job_id}, "review": {"id": existing["id"]}},
        )
        return True

    # -- resolve ------------------------------------------------------------
    def resolve(self, job_id: str, candidate_id: str, *, note: str = "") -> bool:
        """Mark the open review resolved with a human's note.

        Returns:
            ``True`` when an open row transitioned; ``False`` when there
            was no row or it was already resolved - a resolution is a
            fact about a decision, and re-stating it is not a change.
        """
        existing = self.find(job_id, candidate_id)
        if existing is None or existing.get("status") != "OPEN":
            return False
        now = self.now()
        self.update(
            str(existing["id"]),
            {
                "status": "RESOLVED",
                "updated_at": now,
                "resolved_at": now,
                "resolution": note or "resolved",
            },
        )
        log.info(
            "review resolved",
            extra={"job": {"id": job_id}, "review": {"id": existing["id"]}},
        )
        return True

    # -- read ---------------------------------------------------------------
    def find(self, job_id: str, candidate_id: str) -> Optional[dict[str, Any]]:
        """The review row for one posting and candidate, or ``None``."""
        row = self.db.query_one(
            "SELECT * FROM job_reviews WHERE job_id = ? AND candidate_id = ?",
            (job_id, candidate_id),
        )
        if row is None:
            return None
        decoded = dict(row)
        decoded["reasons"] = from_json_text(row.get("reasons"), [])
        decoded["supporting"] = from_json_text(row.get("supporting"), {})
        return decoded

    def statuses_for(
        self, job_ids: Sequence[str], candidate_id: str
    ) -> dict[str, str]:
        """``{job_id: status}`` for the given postings, missing ones absent."""
        if not job_ids:
            return {}
        rows = self.db.query(
            "SELECT job_id, status FROM job_reviews "
            f"WHERE candidate_id = ? AND job_id IN {self._in_clause(job_ids)}",  # noqa: S608
            (candidate_id, *job_ids),
        )
        return {str(row["job_id"]): str(row["status"]) for row in rows}

    def open_reviews(self, candidate_id: str) -> list[dict[str, Any]]:
        """Open reviews newest-activity first, joined to their postings.

        The join is here, not in the caller, because every reader of an
        open review wants the posting's identity beside it - a review
        nobody can locate is not a review.
        """
        rows = self.db.query(
            "SELECT r.id, r.job_id, r.candidate_id, r.decision, r.reasons, "
            "       r.supporting, r.status, r.created_at, r.updated_at, "
            "       j.title, j.company, j.canonical_url "
            "FROM job_reviews r "
            "JOIN jobs j ON j.id = r.job_id "
            "WHERE r.status = 'OPEN' AND r.candidate_id = ? "
            "ORDER BY r.updated_at DESC",
            (candidate_id,),
        )
        decoded = []
        for row in rows:
            item = dict(row)
            item["reasons"] = from_json_text(row.get("reasons"), [])
            item["supporting"] = from_json_text(row.get("supporting"), {})
            decoded.append(item)
        return decoded

    def count_open(self, candidate_id: Optional[str] = None) -> int:
        """How many doubts are still waiting, optionally for one candidate."""
        if candidate_id is None:
            return int(
                self.db.scalar(
                    "SELECT COUNT(*) FROM job_reviews WHERE status = 'OPEN'"
                )
                or 0
            )
        return int(
            self.db.scalar(
                "SELECT COUNT(*) FROM job_reviews "
                "WHERE status = 'OPEN' AND candidate_id = ?",
                (candidate_id,),
            )
            or 0
        )
