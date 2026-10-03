"""Job persistence.

Responsibilities, in order of how often they matter:

1. **Identity-keyed upsert.** Two runs that discover the same posting produce
   one row. The lookup checks the stored identity first and falls back to the
   external id and the canonical URL, so a job whose identity *strengthens*
   over time (URL first, then a platform id) still lands on one row instead of
   failing a unique constraint.
2. **Explicit state transitions.** A status is never written directly; it goes
   through :meth:`JobRepository.transition`, which validates against the
   transition table and writes an audit event in the same transaction.
3. **Row to model translation.** Callers receive :class:`~jobs.models.Job` and
   :class:`~jobs.models.Requirement` objects, never raw rows.

The cache tables (``job_analyses``, ``job_matches``) are addressed by their
fingerprint columns, which is what makes "same job, same description, same
animator" a database lookup rather than a re-computation.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Optional, Sequence

from core.enums import (
    AnalysisSource,
    ExtractionMethod,
    ExtractionStatus,
    MatchDecision,
    RequirementPriority,
    HardGateStatus,
)
from core.errors import JobNotFoundError
from core.hashing import parse_iso_datetime, utc_now
from core.logging_config import get_logger
from database.repositories.base import (
    BaseRepository,
    from_json_text,
    new_id,
    row_get,
    to_json_text,
)
from jobs.deduplicator import JobIdentity, merge_discovery
from jobs.models import Job, JobStatus, Requirement, RequirementKind
from jobs.normalizer import normalize_company, normalize_title

__all__ = ["JobRepository"]

log = get_logger(__name__)


def _dt(value: Any):
    return parse_iso_datetime(value) if isinstance(value, str) else value


class JobRepository(BaseRepository):
    """Stores jobs, their requirements, analyses, matches and state events."""

    table = "jobs"
    id_prefix = "job"

    # ------------------------------------------------------------------ jobs
    def save(self, job: Job, *, actor: str = "system") -> tuple[str, bool]:
        """Insert or merge a job, keyed on its identity.

        Args:
            job: The discovered job. ``identity_key`` is computed if absent.
            actor: Who performed the write, for the creation event.

        Returns:
            ``(job_id, created)`` where ``created`` is ``False`` when an
            existing row was merged into instead.

        Requirements are persisted when the job carries any. A rediscovery
        that arrives without requirements (the normal case: discovery does not
        analyse) leaves the stored set alone rather than wiping it.

        Raises:
            DatabaseError: If the write fails.
        """
        incoming = job.model_copy(deep=True)
        if not incoming.identity_key:
            incoming.identity_key = JobIdentity.of(incoming).identity_key

        with self.db.transaction():
            existing = self._resolve_existing(incoming)
            if existing is None:
                job_id, created = self._insert_new(incoming, actor=actor), True
            else:
                job_id, created = self._merge_into(existing, incoming, actor=actor), False
            if incoming.requirements:
                self._write_requirements(job_id, incoming.requirements)
        return job_id, created

    def _insert_new(self, job: Job, *, actor: str) -> str:
        if not job.id:
            job.id = self.new_id()
        now = utc_now()
        self.insert(self._row_values(job, created_at=now))
        self._write_event(
            job.id,
            from_state="",
            to_state=job.status,
            actor=actor,
            reason="job created",
        )
        return job.id

    def _merge_into(self, existing: Job, incoming: Job, *, actor: str) -> str:
        merged = merge_discovery(existing, incoming)
        # Recompute from the merged row rather than adopting the sighting's
        # claim: a job first stored by URL has since had its platform id
        # filled in, and its identity must describe the data now on the row —
        # anything else leaves the key disagreeing with the id column.
        merged.identity_key = JobIdentity.of(merged).identity_key
        previous_status = existing.status
        self.update(existing.id, self._row_values(merged, created_at=None))
        if merged.status is not previous_status:
            self._write_event(
                existing.id,
                from_state=previous_status,
                to_state=merged.status,
                actor=actor,
                reason="status changed while merging a rediscovery",
            )
        return existing.id

    def _resolve_existing(self, incoming: Job) -> Optional[Job]:
        """Find the stored row this job describes, if any.

        Checked in descending order of confidence: identity, then platform id,
        then canonical URL. Returning the first hit is what lets a job that was
        first stored under a URL identity later adopt its platform id without
        creating a second row.
        """
        found = self.load_by_identity(incoming.identity_key or "")
        if found is not None:
            return found
        if incoming.source and incoming.external_job_id:
            found = self.find_by_external_id(incoming.source, incoming.external_job_id)
            if found is not None:
                return found
        if incoming.canonical_url:
            # A URL hit is authoritative: ``ux_jobs_canonical_url`` makes a
            # canonical URL unique, so the schema has already ruled that two
            # rows cannot disagree about it. Refusing here would only turn a
            # merge into an IntegrityError on insert.
            return self.find_by_canonical_url(incoming.canonical_url)
        return None

    def load(self, job_id: str) -> Optional[Job]:
        """Load one job with its requirements."""
        row = self.get(job_id)
        return None if row is None else self._row_to_job(row)

    def require(self, job_id: str) -> Job:
        """Load one job or raise.

        Raises:
            JobNotFoundError: If there is no such job.
        """
        job = self.load(job_id)
        if job is None:
            raise JobNotFoundError("no job with that id", job_id=job_id)
        return job

    def load_by_identity(self, identity_key: str) -> Optional[Job]:
        if not identity_key:
            return None
        row = self.db.query_one(
            "SELECT * FROM jobs WHERE identity_key = ?", (identity_key,)
        )
        return None if row is None else self._row_to_job(row)

    def find_by_external_id(self, source: str, external_job_id: str) -> Optional[Job]:
        row = self.db.query_one(
            "SELECT * FROM jobs WHERE source = ? AND external_job_id = ?",
            (source, external_job_id),
        )
        return None if row is None else self._row_to_job(row)

    def find_by_canonical_url(self, canonical_url: str) -> Optional[Job]:
        if not canonical_url:
            return None
        row = self.db.query_one(
            "SELECT * FROM jobs WHERE canonical_url = ?", (canonical_url,)
        )
        return None if row is None else self._row_to_job(row)

    def patch_metadata(self, job_id: str, updates: Mapping[str, Any]) -> bool:
        """Merge keys into a job's stored metadata, and nothing else.

        A derived annotation - the reconciliation report, an extraction
        note - belongs next to the rows it describes but must not travel
        through :meth:`save`, which merges discoveries, bumps sighting
        counters, and rewrites identity. This writes only the metadata
        column (plus ``updated_at``). A ``None`` value removes the key,
        so "no report" reads as an absent block rather than a stored
        null.

        Returns:
            ``False`` when there is no such job; ``True`` after a write.
        """
        row = self.db.query_one(
            "SELECT source_metadata FROM jobs WHERE id = ?", (job_id,)
        )
        if row is None:
            return False
        metadata = from_json_text(row_get(row, "source_metadata"), {}) or {}
        if not isinstance(metadata, dict):
            metadata = {}
        for key, value in updates.items():
            if value is None:
                metadata.pop(key, None)
            else:
                metadata[key] = value
        self.update(
            job_id,
            {
                "source_metadata": to_json_text(metadata),
                "updated_at": utc_now().isoformat(),
            },
        )
        return True

    def list_jobs(
        self,
        *,
        status: JobStatus | str | Sequence[JobStatus | str] | None = None,
        source: str | None = None,
        decision: MatchDecision | str | None = None,
        candidate_id: str | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[Job]:
        """List jobs, optionally filtered by status, source or match decision.

        ``status`` accepts a single status or a sequence of them. A
        ``decision`` filter joins the newest matching row in ``job_matches``,
        which is what the dashboard needs for "show me everything that was
        rejected".
        """
        sql = ["SELECT DISTINCT j.* FROM jobs j"]
        params: list[Any] = []
        where: list[str] = []

        if decision is not None:
            sql.append(
                "JOIN job_matches m ON m.job_id = j.id "
                "AND m.rowid = (SELECT MAX(m2.rowid) FROM job_matches m2 "
                "               WHERE m2.job_id = j.id)"
            )
            where.append("m.decision = ?")
            params.append(str(decision))
            if candidate_id is not None:
                where.append("m.candidate_id = ?")
                params.append(candidate_id)

        if status:
            # ``JobStatus`` is a str enum, so a bare status would otherwise be
            # iterated character by character and match nothing.
            if isinstance(status, str):
                status = [status]
            values = [str(s.value if isinstance(s, JobStatus) else s) for s in status]
            where.append(f"j.status IN ({', '.join('?' for _ in values)})")
            params.extend(values)
        if source:
            where.append("j.source = ?")
            params.append(source)
        if where:
            sql.append("WHERE " + " AND ".join(where))
        sql.append("ORDER BY j.last_seen_at DESC, j.rowid DESC")
        if limit is not None:
            sql.append("LIMIT ? OFFSET ?")
            params.extend([int(limit), int(offset)])

        rows = self.db.query(" ".join(sql), tuple(params))
        return [self._row_to_job(row) for row in rows]

    def count_by_status(self) -> dict[str, int]:
        rows = self.db.query("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        return {row["status"]: int(row["n"]) for row in rows}

    # ------------------------------------------------------------- lifecycle
    def transition(
        self,
        job_id: str,
        to_state: JobStatus,
        *,
        actor: str = "system",
        reason: str = "",
        detail: Optional[dict[str, Any]] = None,
    ) -> Job:
        """Move a job to ``to_state`` and record why.

        The status column and the audit event are written in one transaction,
        so a job can never end up in a state with no record of how it got
        there.

        Raises:
            JobNotFoundError: If there is no such job.
            InvalidStateTransitionError: If the transition table forbids the
                move. The error carries the allowed destinations.
        """
        with self.db.transaction():
            job = self.require(job_id)
            moved = job.transition_to(to_state, reason=reason)
            self.update(job_id, {"status": to_state.value, "updated_at": utc_now().isoformat()})
            self._write_event(
                job_id,
                from_state=job.status,
                to_state=to_state,
                actor=actor,
                reason=reason,
                detail=detail,
            )
        return moved

    def _write_event(
        self,
        job_id: str,
        *,
        from_state: JobStatus | str,
        to_state: JobStatus | str,
        actor: str,
        reason: str = "",
        detail: Optional[dict[str, Any]] = None,
    ) -> None:
        from core.actors import classify_actor

        seq = int(
            self.db.scalar(
                "SELECT COALESCE(MAX(seq), 0) + 1 FROM job_state_events WHERE job_id = ?",
                (job_id,),
            )
            or 1
        )
        self.db.execute(
            "INSERT INTO job_state_events "
            "(job_id, seq, from_state, to_state, actor_kind, reason, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                seq,
                from_state.value if isinstance(from_state, JobStatus) else from_state,
                to_state.value if isinstance(to_state, JobStatus) else to_state,
                classify_actor(actor),
                reason or None,
                to_json_text(detail),
                utc_now().isoformat(),
            ),
        )

    def state_events(self, job_id: str) -> list[dict[str, Any]]:
        """Every recorded transition for ``job_id``, oldest first."""
        return self.db.query(
            "SELECT * FROM job_state_events WHERE job_id = ? ORDER BY seq", (job_id,)
        )

    # ---------------------------------------------------------- requirements
    def replace_requirements(self, job_id: str, requirements: Iterable[Requirement]) -> int:
        """Replace the stored requirements for one job.

        The whole set is replaced rather than diffed: requirements are derived
        artefacts of one description, and a partial update could leave a
        requirement that the current text no longer supports.

        Opens its own transaction; callers already inside one should use
        :meth:`_write_requirements` instead, because SQLite cannot nest
        transactions.
        """
        rows = list(requirements)
        with self.db.transaction():
            self._write_requirements(job_id, rows)
        return len(rows)

    def _write_requirements(self, job_id: str, rows: Sequence[Requirement]) -> None:
        """Delete and re-insert requirements. Must run inside a transaction."""
        self.db.execute("DELETE FROM job_requirements WHERE job_id = ?", (job_id,))
        for requirement in rows:
            self._insert_requirement(job_id, requirement)

    def _insert_requirement(self, job_id: str, requirement: Requirement) -> None:
        rid = requirement.id or new_id("req")
        self.db.execute(
            "INSERT INTO job_requirements "
            "(id, job_id, kind, priority, text, normalized, ambiguous, min_years, "
            " source_excerpt, extraction_source, analysis_source, evidence_json, "
            " confidence, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rid,
                job_id,
                requirement.kind.value,
                requirement.priority.value,
                requirement.text,
                requirement.normalized,
                1 if requirement.ambiguous else 0,
                requirement.min_years,
                requirement.source_excerpt,
                requirement.extraction_source.value,
                requirement.analysis_source.value,
                to_json_text([e.model_dump(mode="json") for e in requirement.evidence]),
                requirement.confidence,
                utc_now().isoformat(),
            ),
        )

    def requirements(self, job_id: str) -> list[Requirement]:
        """Every stored requirement for ``job_id``, in insertion order."""
        rows = self.db.query(
            "SELECT * FROM job_requirements WHERE job_id = ? ORDER BY rowid", (job_id,)
        )
        return [self._row_to_requirement(row) for row in rows]

    # -------------------------------------------------------- JD extraction
    def record_extraction_run(
        self,
        job_id: str,
        *,
        status: ExtractionStatus,
        method: ExtractionMethod,
        raw_length: int = 0,
        normalized_length: int = 0,
        content_hash: Optional[str] = None,
        source: str = "",
        error_code: Optional[str] = None,
        detail: Optional[dict[str, Any]] = None,
    ) -> str:
        """Record one attempt at capturing a job description.

        Every attempt is kept, including the failures, so "when did this job
        stop yielding a description?" is answerable from stored data.
        """
        run_id = new_id("xrun")
        self.db.execute(
            "INSERT INTO job_extraction_runs "
            "(id, job_id, extraction_status, extraction_method, raw_length, "
            " normalized_length, content_hash, source, error_code, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                job_id,
                status.value,
                method.value,
                int(raw_length),
                int(normalized_length),
                content_hash,
                source or None,
                error_code,
                to_json_text(detail),
                utc_now().isoformat(),
            ),
        )
        return run_id

    def latest_extraction(self, job_id: str) -> Optional[dict[str, Any]]:
        return self.db.query_one(
            "SELECT * FROM job_extraction_runs WHERE job_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (job_id,),
        )

    def extraction_runs(self, job_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM job_extraction_runs WHERE job_id = ? ORDER BY rowid",
            (job_id,),
        )

    # ------------------------------------------------------------- analyses
    def find_cached_analysis(
        self,
        job_id: str,
        *,
        content_hash: str,
        analyzer: str,
        analyzer_version: str,
        prompt_version: Optional[str] = None,
    ) -> Optional[dict[str, Any]]:
        """Return a successful earlier analysis matching this exact key.

        A changed description produces a different ``content_hash`` and
        therefore no match, which is what stops stale requirements surviving
        an edited posting.
        """
        return self.db.query_one(
            "SELECT * FROM job_analyses WHERE job_id = ? AND content_hash = ? "
            "AND analyzer = ? AND analyzer_version = ? AND IFNULL(prompt_version, '') = ? "
            "AND status = 'SUCCESS' "
            "ORDER BY created_at DESC LIMIT 1",
            (job_id, content_hash, analyzer, analyzer_version, prompt_version or ""),
        )

    def find_current_analysis(
        self,
        job_id: str,
        *,
        content_hash: str,
    ) -> Optional[dict[str, Any]]:
        """The newest successful analysis of this exact content, whatever read it.

        The cache keys are per-analyzer, but matching asks a different
        question: *has the text now on the job been read at all?* An AI
        interpretation answers yes under its own key while the
        deterministic key misses - and re-running that key would replace
        the model's rows with a rule's. This query is the guard: any
        successful reading of the current content means the stored
        requirements are current as they stand.
        """
        return self.db.query_one(
            "SELECT * FROM job_analyses WHERE job_id = ? AND content_hash = ? "
            "AND status = 'SUCCESS' "
            "ORDER BY created_at DESC LIMIT 1",
            (job_id, content_hash),
        )

    def record_analysis(
        self,
        job_id: str,
        *,
        content_hash: str,
        analyzer: str,
        analyzer_version: str,
        analysis_source: AnalysisSource,
        requirement_count: int,
        status: str = "SUCCESS",
        ai_provider: Optional[str] = None,
        ai_model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        error_code: Optional[str] = None,
        model_run_id: Optional[str] = None,
    ) -> str:
        run_id = new_id("ana")
        self.db.execute(
            "INSERT INTO job_analyses "
            "(id, job_id, content_hash, analyzer, analyzer_version, ai_provider, "
            " ai_model, prompt_version, analysis_source, requirement_count, status, "
            " error_code, model_run_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id, content_hash, analyzer, analyzer_version, "
            "             IFNULL(prompt_version, '')) "
            "DO UPDATE SET requirement_count = excluded.requirement_count, "
            "              status = excluded.status, "
            "              ai_provider = excluded.ai_provider, "
            "              ai_model = excluded.ai_model, "
            "              error_code = excluded.error_code, "
            "              model_run_id = excluded.model_run_id, "
            "              created_at = excluded.created_at",
            (
                run_id,
                job_id,
                content_hash,
                analyzer,
                analyzer_version,
                ai_provider,
                ai_model,
                prompt_version,
                analysis_source.value,
                int(requirement_count),
                status,
                error_code,
                model_run_id,
                utc_now().isoformat(),
            ),
        )
        return run_id

    def analyses(self, job_id: str) -> list[dict[str, Any]]:
        return self.db.query(
            "SELECT * FROM job_analyses WHERE job_id = ? ORDER BY rowid", (job_id,)
        )

    # --------------------------------------------------------------- matches
    def find_cached_match(
        self,
        job_id: str,
        candidate_id: str,
        *,
        requirements_fingerprint: str,
        candidate_fingerprint: str,
        scorer_fingerprint: str = "",
    ) -> Optional[dict[str, Any]]:
        # Decoded like every other match loader: a caller reusing a cached
        # result should not have to know that one path hands back JSON text.
        return self._decode_match(
            self.db.query_one(
                "SELECT * FROM job_matches WHERE job_id = ? AND candidate_id = ? "
                "AND requirements_fingerprint = ? AND candidate_fingerprint = ? "
                "AND scorer_fingerprint = ? "
                "ORDER BY created_at DESC LIMIT 1",
                (
                    job_id,
                    candidate_id,
                    requirements_fingerprint,
                    candidate_fingerprint,
                    scorer_fingerprint,
                ),
            )
        )

    def save_match(
        self,
        *,
        job_id: str,
        candidate_id: str,
        decision: MatchDecision,
        hard_gate_status: HardGateStatus,
        analysis_source: AnalysisSource,
        requirements_fingerprint: str,
        candidate_fingerprint: str,
        scorer_fingerprint: str = "",
        explanation: dict[str, Any],
        matched_count: int = 0,
        mismatched_count: int = 0,
        unknown_count: int = 0,
        semantic_score: Optional[float] = None,
        confidence: Optional[float] = None,
        ai_provider: Optional[str] = None,
        ai_model: Optional[str] = None,
        prompt_version: Optional[str] = None,
        model_run_id: Optional[str] = None,
        evidence: Optional[list[dict[str, Any]]] = None,
        review_reasons: Optional[list[str]] = None,
    ) -> str:
        """Persist a match result, replacing any earlier one for the same key.

        The unique cache index is the conflict target, so re-running an
        unchanged analysis overwrites rather than accumulating rows.
        """
        match_id = new_id("match")
        self.db.execute(
            "INSERT INTO job_matches "
            "(id, job_id, candidate_id, decision, hard_gate_status, matched_count, "
            " mismatched_count, unknown_count, semantic_score, confidence, "
            " analysis_source, requirements_fingerprint, candidate_fingerprint, "
            " scorer_fingerprint, "
            " ai_provider, ai_model, prompt_version, model_run_id, explanation, "
            " evidence, review_reasons, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id, candidate_id, requirements_fingerprint, "
            "             candidate_fingerprint, scorer_fingerprint) "
            "DO UPDATE SET decision = excluded.decision, "
            "              hard_gate_status = excluded.hard_gate_status, "
            "              matched_count = excluded.matched_count, "
            "              mismatched_count = excluded.mismatched_count, "
            "              unknown_count = excluded.unknown_count, "
            "              semantic_score = excluded.semantic_score, "
            "              confidence = excluded.confidence, "
            "              analysis_source = excluded.analysis_source, "
            "              ai_provider = excluded.ai_provider, "
            "              ai_model = excluded.ai_model, "
            "              prompt_version = excluded.prompt_version, "
            "              model_run_id = excluded.model_run_id, "
            "              explanation = excluded.explanation, "
            "              evidence = excluded.evidence, "
            "              review_reasons = excluded.review_reasons, "
            "              created_at = excluded.created_at",
            (
                match_id,
                job_id,
                candidate_id,
                decision.value,
                hard_gate_status.value,
                int(matched_count),
                int(mismatched_count),
                int(unknown_count),
                semantic_score,
                confidence,
                analysis_source.value,
                requirements_fingerprint,
                candidate_fingerprint,
                scorer_fingerprint,
                ai_provider,
                ai_model,
                prompt_version,
                model_run_id,
                to_json_text(explanation),
                to_json_text(evidence),
                to_json_text(review_reasons),
                utc_now().isoformat(),
            ),
        )
        stored = self.db.query_one(
            "SELECT id FROM job_matches WHERE job_id = ? AND candidate_id = ? "
            "AND requirements_fingerprint = ? AND candidate_fingerprint = ?",
            (job_id, candidate_id, requirements_fingerprint, candidate_fingerprint),
        )
        return str(stored["id"]) if stored else match_id

    def load_match(self, match_id: str) -> Optional[dict[str, Any]]:
        # Not ``self.get``: that reads the ``jobs`` table this repository is
        # named for, and a match id is not a job id.
        row = self.db.query_one("SELECT * FROM job_matches WHERE id = ?", (match_id,))
        return self._decode_match(row)

    def matches(
        self,
        *,
        job_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        decision: MatchDecision | str | None = None,
        limit: Optional[int] = None,
    ) -> list[dict[str, Any]]:
        """Stored match results, newest first, with JSON columns decoded."""
        where: list[str] = []
        params: list[Any] = []
        if job_id:
            where.append("job_id = ?")
            params.append(job_id)
        if candidate_id:
            where.append("candidate_id = ?")
            params.append(candidate_id)
        if decision is not None:
            where.append("decision = ?")
            params.append(str(decision.value if isinstance(decision, MatchDecision) else decision))
        sql = "SELECT * FROM job_matches"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY created_at DESC, rowid DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        return [self._decode_match(row) for row in self.db.query(sql, tuple(params))]

    def review_required(self, *, candidate_id: Optional[str] = None) -> list[dict[str, Any]]:
        """Jobs whose newest match asks for a human, joined to that match."""
        return self.db.query(
            "SELECT j.id, j.title, j.company, j.canonical_url, j.status, "
            "       m.decision, m.review_reasons, m.created_at AS matched_at "
            "FROM jobs j "
            "JOIN job_matches m ON m.job_id = j.id "
            "AND m.rowid = (SELECT MAX(m2.rowid) FROM job_matches m2 WHERE m2.job_id = j.id) "
            "WHERE m.decision IN ('REVIEW_REQUIRED', 'INSUFFICIENT_EVIDENCE') "
            + ("AND m.candidate_id = ? " if candidate_id else "")
            + "ORDER BY m.created_at DESC",
            (candidate_id,) if candidate_id else (),
        )

    def has_failed_attempt(self, job_id: str, *, content_hash: str) -> bool:
        """Whether any analysis recorded for this content died outright.

        ``FAILED`` rows are written by the AI path when a model attempt
        fails validation or the provider errors out, then never served
        (the cache returns ``SUCCESS`` only). Their existence is the
        durable evidence that a human reading was *tried* on this exact
        description and did not survive - the deterministic re-read that
        replaced it never erases that fact.
        """
        return (
            self.db.query_one(
                "SELECT 1 FROM job_analyses "
                "WHERE job_id = ? AND content_hash = ? AND status = 'FAILED' "
                "LIMIT 1",
                (job_id, content_hash),
            )
            is not None
        )

    # ------------------------------------------------------------ mapping
    def _decode_match(self, row: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if row is None:
            return None
        decoded = dict(row)
        decoded["explanation"] = from_json_text(row.get("explanation"), {})
        decoded["evidence"] = from_json_text(row.get("evidence"), [])
        decoded["review_reasons"] = from_json_text(row.get("review_reasons"), [])
        return decoded

    def _row_values(self, job: Job, *, created_at: Optional[Any]) -> dict[str, Any]:
        """Map a job to the ``jobs`` columns."""
        now = utc_now().isoformat()
        identity = job.identity_key or JobIdentity.of(job).identity_key
        return {
            "id": job.id,
            "source": job.source or "",
            "external_job_id": job.external_job_id,
            "identity_key": identity,
            "canonical_url": job.canonical_url,
            "original_url": job.url,
            "company": job.company,
            "company_normalized": normalize_company(job.company),
            "title": job.title,
            "title_normalized": _safe_normalized_title(job.title),
            "location": job.location,
            "workplace_type": job.workplace_type,
            "employment_type": job.employment_type,
            "experience_level": job.experience_level,
            "salary_min": job.salary_min,
            "salary_max": job.salary_max,
            "salary_currency": job.salary_currency,
            "salary_period": job.salary_period,
            "description_raw": job.description_raw,
            "description_text": job.description_text,
            "content_hash": job.description_hash,
            "extraction_status": row_get(_status_metadata(job), "extraction_status"),
            "status": job.status.value,
            "posted_at": job.posted_at.isoformat() if job.posted_at else None,
            "discovered_at": job.discovered_at.isoformat(),
            "first_seen_at": job.first_seen_at.isoformat() if job.first_seen_at else None,
            "last_seen_at": job.last_seen_at.isoformat() if job.last_seen_at else None,
            "seen_count": job.seen_count,
            "analysis_source": job.analysis_source.value,
            "source_metadata": to_json_text(job.metadata),
            "created_at": created_at.isoformat() if created_at else now,
            "updated_at": now,
        }

    def _row_to_job(self, row: dict[str, Any]) -> Job:
        job_id = row["id"]
        return Job(
            id=job_id,
            source=row_get(row, "source", ""),
            external_job_id=row_get(row, "external_job_id"),
            company=row_get(row, "company", ""),
            title=row_get(row, "title", ""),
            location=row_get(row, "location"),
            canonical_url=row_get(row, "canonical_url"),
            url=row_get(row, "original_url"),
            workplace_type=row_get(row, "workplace_type"),
            employment_type=row_get(row, "employment_type"),
            experience_level=row_get(row, "experience_level"),
            salary_min=row_get(row, "salary_min"),
            salary_max=row_get(row, "salary_max"),
            salary_currency=row_get(row, "salary_currency"),
            salary_period=row_get(row, "salary_period"),
            description_raw=row_get(row, "description_raw"),
            description_text=row_get(row, "description_text"),
            description_hash=row_get(row, "content_hash"),
            identity_key=row_get(row, "identity_key"),
            status=JobStatus(row_get(row, "status", JobStatus.DISCOVERED.value)),
            posted_at=_dt(row_get(row, "posted_at")),
            discovered_at=_dt(row_get(row, "discovered_at")) or utc_now(),
            first_seen_at=_dt(row_get(row, "first_seen_at")),
            last_seen_at=_dt(row_get(row, "last_seen_at")),
            seen_count=int(row_get(row, "seen_count", 1) or 1),
            requirements=self.requirements(job_id),
            analysis_source=AnalysisSource(row_get(row, "analysis_source", "JOB_DATA")),
            metadata=from_json_text(row_get(row, "source_metadata"), {}) or {},
        )

    def _row_to_requirement(self, row: dict[str, Any]) -> Requirement:
        return Requirement(
            id=row_get(row, "id", ""),
            kind=RequirementKind(row_get(row, "kind", "OTHER")),
            text=row_get(row, "text", ""),
            normalized=row_get(row, "normalized"),
            priority=RequirementPriority(row_get(row, "priority", "UNKNOWN")),
            ambiguous=bool(row_get(row, "ambiguous", 0)),
            min_years=row_get(row, "min_years"),
            source_excerpt=row_get(row, "source_excerpt"),
            extraction_source=ExtractionMethod(
                row_get(row, "extraction_source", "DETERMINISTIC")
            ),
            analysis_source=AnalysisSource(row_get(row, "analysis_source", "JOB_DATA")),
            evidence=_decode_evidence(row_get(row, "evidence_json")),
            confidence=float(row_get(row, "confidence", 1.0)),
        )


def _safe_normalized_title(title: str) -> str:
    """Normalised title for indexing; empty rather than an exception."""
    try:
        return normalize_title(title)
    except ValueError:
        return ""


def _decode_evidence(raw: Any) -> list:
    """Decode stored evidence rows.

    A row that no longer validates is logged and skipped rather than allowed
    to hide the requirement it was attached to: losing one citation is bad,
    losing the requirement entirely is worse.
    """
    from core.evidence import Evidence

    payload = from_json_text(raw, []) if isinstance(raw, str) else (raw or [])
    out = []
    for index, item in enumerate(payload):
        try:
            out.append(Evidence.model_validate(item))
        except Exception as exc:  # noqa: BLE001 - one bad row must not hide the requirement
            log.warning(
                "could not decode stored requirement evidence, skipping row",
                extra={"jobs": {"index": index, "error": str(exc)}},
            )
    return out


def _status_metadata(job: Job) -> dict[str, Any]:
    """Extraction status carried on the job, if the pipeline stored one."""
    value = job.metadata.get("extraction_status")
    return {"extraction_status": value} if value else {}
