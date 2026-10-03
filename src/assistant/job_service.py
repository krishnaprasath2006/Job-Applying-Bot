"""Job intelligence service: analysis, matching, explanation, and review
for saved postings.

This is the wiring layer, in the same sense as ``ProfileService``: it owns
a repository, it reads the candidate profile, and it calls into the pure
``jobs`` package — it contains no matching rules of its own. Everything
that decides something lives in ``jobs``; everything that fetches or
stores something lives here or below.

Two deliberate omissions:

* **No browser.** Pages arrive as text (a saved fixture, a capture handed
  over by the automation layer later). Nothing here navigates, and the
  CLI commands built on this service open no browser either.
* **No state-machine driving.** Ingesting stores a job with whatever
  lifecycle state it carries; transitions belong to the pipeline that
  performs them, and guessing them here would record work that never
  happened.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Optional, Sequence, Union

from core.enums import AnalysisSource, RetrievalMethod, ReviewReason, SourceMode
from core.errors import (
    AIProviderError,
    ConfigurationError,
    JobExtractionError,
    JobNotFoundError,
)
from core.logging_config import get_logger
from core.model_run import ModelRun
from database.repositories.resumes import ResumeRepository
from jobs.dimensions import MatchReport, build_report
from jobs.relevance import ResumeRelevance, recommend_resume
from database.connection import Database
from database.repositories.jobs import JobRepository
from database.repositories.model_runs import ModelRunRepository
from database.repositories.reviews import ReviewRepository
from jobs.acquisition import JobPage, parse_job_page
from jobs.analysis import (
    MatchOutcome,
    RequirementAnalysis,
    analyze_job,
    content_fingerprint,
    match_job,
)
from jobs.candidate import CandidateEvidence
from jobs.deduplicator import canonicalize_url
from jobs.discovery import DiscoveryResult, discover, discover_listing
from jobs.explain import MatchExplanation, explain_match
from jobs.interpret import (
    INTERPRETER,
    INTERPRETER_VERSION,
    error_code_for,
    interpret,
    interpret_prompt_version,
)
from jobs.matching import MatchResult
from jobs.models import Job, JobStatus, Requirement
from jobs.reconcile import RECONCILIATION_KEY, conflict_count, reconcile
from jobs.records import JobNormalizer, RetrievalInfo, enforce_source_mode
from jobs.requirements import extract_requirements
from jobs.review import (
    _INCOMPLETE_EXTRACTIONS,
    ReviewItem,
    ReviewQueue,
)
from jobs.source import JobSource, SearchQuery, job_link_id
from profile.service import ProfileService

__all__ = ["DiscoveryOutcome", "IngestResult", "JobService"]

log = get_logger(__name__)

#: Marks "use the scorer this service was built with", distinct from an
#: explicit ``None`` meaning "score with no scorer at all".
_SCORER_UNSET = object()


@dataclass(frozen=True)
class DiscoveryOutcome:
    """A discovery attempt plus what was newly stored.

    Attributes:
        result: The typed discovery outcome (jobs normalised, status,
            reason, error code).
        stored: Jobs newly inserted into the database.
        merged: Existing job ids the discovery merged into (duplicates).
    """

    result: DiscoveryResult
    stored: tuple[Job, ...] = ()
    merged: tuple[str, ...] = ()

    @property
    def stored_count(self) -> int:
        return len(self.stored)

    @property
    def merged_count(self) -> int:
        return len(self.merged)


@dataclass(frozen=True)
class IngestResult:
    """One local page capture turned into a stored job.

    Attributes:
        job: The stored row — re-read from the database, so the caller
            gets the assigned id rather than the pre-insert copy.
        page: What the capture said, including why it was or was not
            usable.
        created: ``False`` when this merged into an existing job instead
            of creating one.
    """

    job: Job
    page: JobPage
    created: bool


class JobService:
    """Analysis, matching, and review for one candidate against saved jobs.

    Args:
        db: The migrated database.
        profile_service: Source of the candidate facts the matcher reads.
        candidate_id: Whose profile this service matches with; also the
            candidate the match cache and the review queue are keyed by.
        scorer: Optional similarity implementation. ``None`` — the
            default — means matching runs on claims and facts alone, which
            is the honest configuration when no embedding model is
            configured: similarity nobody computed is not similarity zero.
        evidence_provider: Overrides how candidate evidence is built,
            for tests and for callers that hold their evidence elsewhere.
        resume_provider: Overrides how stored resumes are listed for
            relevance, as :class:`ResumeRelevance` reads only what it is
            handed.
        source_mode: What discovery may do. The default is read-only;
            every discovery entry point re-checks it, so a caller cannot
            bypass the boundary by skipping this constructor.
    """

    def __init__(
        self,
        db: Database,
        *,
        profile_service: ProfileService,
        candidate_id: str = "primary",
        scorer: Optional[object] = None,
        evidence_provider: Optional[Callable[[], CandidateEvidence]] = None,
        resume_provider: Optional[Callable[[], list[object]]] = None,
        source_mode: SourceMode = SourceMode.DISCOVERY_ONLY,
    ) -> None:
        self.repository = JobRepository(db)
        self._model_runs = ModelRunRepository(db)
        self._resumes = ResumeRepository(db)
        self._reviews = ReviewRepository(db)
        self._profiles = profile_service
        self._candidate_id = candidate_id
        self._scorer = scorer
        self._evidence_provider = evidence_provider
        self._resume_provider = resume_provider
        self.source_mode = source_mode

    # -- stored jobs ---------------------------------------------------------
    def save(self, job: Job) -> tuple[str, bool]:
        """Insert or merge one job. Returns ``(job_id, created)``."""
        return self.repository.save(job)

    def get(self, job_id: str) -> Job:
        """Load one job, or raise :class:`JobNotFoundError`.

        Raising rather than returning ``None`` is deliberate: every caller
        here has a job id that came from a user or a stored match, and a
        silent ``None`` would travel until it failed somewhere far from
        the typo that caused it.
        """
        job = self.repository.load(job_id)
        if job is None:
            raise JobNotFoundError(f"no job with id {job_id!r}", job_id=job_id)
        return job

    def list_jobs(
        self,
        *,
        status: Union[JobStatus, str, Sequence[Union[JobStatus, str]], None] = None,
        source: Optional[str] = None,
        candidate_id: Optional[str] = None,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list[Job]:
        """Stored jobs, oldest-discovery first as the repository orders them."""
        return self.repository.list_jobs(
            status=status,
            source=source,
            candidate_id=candidate_id,
            limit=limit,
            offset=offset,
        )

    # -- discovery -----------------------------------------------------------
    def discover(
        self,
        source: JobSource,
        query: SearchQuery,
        *,
        now: Optional[datetime] = None,
    ) -> DiscoveryOutcome:
        """Run one read-only search and store what it found.

        The adapter answers; this service normalises (the discovery module
        owns provenance), persists, and counts what was new versus merged
        so a re-run over the same page is measurable instead of silent.

        Raises:
            ApplicationBoundaryError: When this service was built for a
                mode that does not permit discovery (fail closed before
                the adapter is called).
            SourceAcquisitionError: When the source fails outright with a
                typed reason — a failed *attempt* is reported, an unusable
                *page* comes back as a failed result with its error code.
        """
        enforce_source_mode(self.source_mode, "DISCOVER")
        outcome = discover(source, query, mode=self.source_mode, now=now)
        return self._store(outcome)

    def discover_listing(
        self,
        html: str,
        *,
        source: str = "local",
        page_url: str = "",
        source_path: str = "",
        now: Optional[datetime] = None,
    ) -> DiscoveryOutcome:
        """Parse listing HTML in hand (fixture or capture) and store it.

        Same persistence and dedup path as :meth:`discover`; only the
        bytes' origin differs. An empty, partial, or blocked page stores
        nothing and comes back typed — zero rows and an error code are a
        report, not an exception.
        """
        enforce_source_mode(self.source_mode, "DISCOVER")
        outcome = discover_listing(
            html,
            source=source,
            page_url=page_url,
            source_path=source_path,
            mode=self.source_mode,
            now=now,
        )
        return self._store(outcome)

    def _store(self, outcome: DiscoveryResult) -> DiscoveryOutcome:
        """Persist a discovery's jobs, splitting new rows from merges."""
        stored: list[Job] = []
        merged: list[str] = []
        for job in outcome.jobs:
            job_id, created = self.repository.save(job)
            if created:
                stored.append(self.get(job_id))
            else:
                merged.append(job_id)
        if stored or merged:
            log.info(
                "discovery persisted",
                extra={
                    "discovery": {
                        "status": outcome.status.value,
                        "stored": len(stored),
                        "merged": len(merged),
                    }
                },
            )
        return DiscoveryOutcome(
            result=outcome,
            stored=tuple(stored),
            merged=tuple(merged),
        )

    # -- ingest --------------------------------------------------------------
    def ingest_from_source(
        self,
        source: JobSource,
        page_url: str,
        *,
        now: Optional[datetime] = None,
    ) -> IngestResult:
        """Read one posting page through a source adapter and store it.

        The adapter fetches; the page's own judgement of what it held
        (``JobPage.status``) becomes both the job's ``extraction_status``
        and the retrieval status in provenance — one attempt, one verdict,
        recorded twice for two readers. A job already discovered from a
        listing merges onto the same row, and provenance follows the text:
        if this fetch supplied the stored description, its origin replaces
        the listing's.

        Raises:
            ApplicationBoundaryError: When this service's mode does not
                permit fetching (fail closed before the adapter is called).
            SourceAcquisitionError: Whatever typed failure the adapter
                reports — blocked page, timeout, posting gone. Typed
                failures propagate so the caller sees the code, not a
                stack trace.
        """
        enforce_source_mode(self.source_mode, "FETCH")
        page = source.fetch_job(page_url)
        target = page.page_url or page_url
        canonical = canonicalize_url(target)
        base = Job(
            source=source.name,
            url=target or None,
            canonical_url=canonical or None,
            # The platform id lives in the posting URL. A page with no
            # JSON-LD still identifies itself by where it was fetched from,
            # and without this a listing stub and its own detail page would
            # meet only by luck of a matching URL spelling.
            external_job_id=page.external_job_id or (job_link_id(target) or None),
        )
        job = page.apply_to(base)
        metadata = dict(job.metadata)
        metadata["extraction_status"] = page.status.value
        job = job.model_copy(update={"metadata": metadata})
        job = JobNormalizer.attach_provenance(
            job, RetrievalInfo.from_page(page, retrieved_at=now)
        )
        job_id, created = self.repository.save(job)
        stored = self.get(job_id)
        return IngestResult(job=stored, page=page, created=created)

    def ingest_page(
        self,
        html: str,
        *,
        source: str = "local",
        page_url: str = "",
        source_path: str = "",
        now: Optional[datetime] = None,
    ) -> IngestResult:
        """Parse a local page capture and store the job it describes.

        No browser and no network: the caller supplies the page source
        exactly as received. An unusable capture still parses — its
        status and reason come back on the result so the caller can
        record what happened instead of guessing. The page's extraction
        verdict is stored twice, as ``extraction_status`` (for the reader
        asking "was this description ever good enough") and as retrieval
        status in provenance (for the reader asking "where did this come
        from").

        Args:
            html: The page source.
            source: Source key recorded on the job.
            page_url: Where the page came from, when known; it doubles as
                the canonical URL and therefore part of the job's
                identity.
            source_path: The file the bytes were read from, when local.
                Provenance falls back to it when no URL is known.

        Returns:
            The stored job (re-read, so ids are assigned), the capture,
            and whether this created the row.
        """
        page = parse_job_page(html, source=source, page_url=page_url)
        base = Job(
            source=source,
            url=page_url or None,
            canonical_url=page_url or None,
        )
        job = page.apply_to(base)
        metadata = dict(job.metadata)
        metadata["extraction_status"] = page.status.value
        job = job.model_copy(update={"metadata": metadata})
        job = JobNormalizer.attach_provenance(
            job,
            RetrievalInfo.from_extraction(
                extraction=page.status,
                method=RetrievalMethod.SAVED_PAGE,
                source_url=page_url or source_path,
                detail=page.reason,
                retrieved_at=now,
            ),
        )
        job_id, created = self.repository.save(job)
        stored = self.get(job_id)
        return IngestResult(job=stored, page=page, created=created)

    # -- candidate -----------------------------------------------------------
    def evidence(self) -> CandidateEvidence:
        """The candidate's claims and facts, as the matcher reads them."""
        if self._evidence_provider is not None:
            return self._evidence_provider()
        profile = self._profiles.load_profile(self._candidate_id)
        return CandidateEvidence.from_facts(profile.to_facts())

    # -- analysis ------------------------------------------------------------
    def analyze(
        self,
        job_id: str,
        *,
        ai: bool = False,
        provider: Optional[Any] = None,
        model: Optional[str] = None,
    ) -> RequirementAnalysis:
        """Requirements for one job, via the analysis cache.

        The default path is fully deterministic and unchanged: no provider,
        no network, no model. With ``ai=True`` the configured model reads
        the posting under strict validation, and the rules are:

        * a cache hit is served without calling the model at all — the AI
          key already holds this content's reading;
        * a provider or validation failure falls back to the deterministic
          extractor, and the attempt is recorded ``FAILED`` under the AI
          key (never as a success), so the next call retries the model;
        * every persisted model run goes through the run repository, so
          "which model produced these rows" is answerable later.

        Args:
            job_id: The posting to analyse.
            ai: Whether to attempt a model reading.
            provider: Something satisfying ``ai.provider.AIProvider``.
                Required when ``ai=True``; the service builds none itself
                because provider choice belongs to configuration, not to
                this wiring layer.
            model: Model override for this call.

        Returns:
            The requirements plus the cache verdict. ``ai_fallback``
            marks a result whose AI attempt failed.

        Raises:
            JobNotFoundError: Unknown job id.
            ConfigurationError: ``ai=True`` without a provider.
            JobExtractionError: ``ai=True`` on a job with no description —
                there is nothing to read, and asking a model to invent one
                is exactly the failure mode this milestone forbids.
        """
        job = self.get(job_id)
        if not ai:
            analysis = analyze_job(job, self.repository)
            if not analysis.cached and RECONCILIATION_KEY in job.metadata:
                # Fresh rows replaced the ones the cross-check described;
                # a report that no longer matches its rows is a lie.
                self.repository.patch_metadata(
                    job.id, {RECONCILIATION_KEY: None}
                )
            return analysis
        if provider is None:
            raise ConfigurationError(
                "ai analysis requested without a provider",
                job_id=job_id,
                hint="pass provider=... or run the offline path (ai=False)",
            )
        description = job.description_text or job.description_raw or ""
        if not description.strip():
            raise JobExtractionError(
                "job has no description to interpret",
                error_code="JD_NOT_FOUND",
                job_id=job_id,
            )
        provider_name = str(getattr(provider, "name", "unknown"))
        chosen_model = model or getattr(provider, "model", None) or None
        version = interpret_prompt_version(provider_name, chosen_model)

        # Phase 1: the cache answers without waking the model.
        content_hash = content_fingerprint(job)
        hit = self.repository.find_cached_analysis(
            job.id,
            content_hash=content_hash,
            analyzer=INTERPRETER,
            analyzer_version=INTERPRETER_VERSION,
            prompt_version=version,
        )
        if hit is not None:
            log.info("ai analysis cache hit", extra={"job": {"id": job.id}})
            return RequirementAnalysis(
                requirements=self.repository.requirements(job.id),
                content_hash=content_hash,
                analysis_id=str(hit.get("id", "")),
                cached=True,
            )

        # Phase 2: the model reads, strictly; failure records and falls back.
        try:
            interpretation = interpret(
                description,
                provider=provider,
                model=model,
                prompt_version=version,
                run_sink=self._model_runs.save,
            )
        except AIProviderError as exc:
            code = error_code_for(exc)
            log.warning(
                "ai interpretation failed; deterministic fallback",
                extra={
                    "job": {"id": job.id},
                    "ai": {"error_code": code, "provider": provider_name},
                },
            )
            analysis = analyze_job(
                job,
                self.repository,
                analyzer=INTERPRETER,
                analyzer_version=INTERPRETER_VERSION,
                prompt_version=version,
                ai_provider=provider_name,
                ai_model=chosen_model,
                status="FAILED",
                error_code=code,
            )
            if not analysis.cached and RECONCILIATION_KEY in job.metadata:
                # The rows a previous cross-check described are gone.
                self.repository.patch_metadata(job.id, {RECONCILIATION_KEY: None})
            return analysis
        analysis = analyze_job(
            job,
            self.repository,
            extract=lambda text, raw=None: interpretation.requirements,
            analyzer=INTERPRETER,
            analyzer_version=INTERPRETER_VERSION,
            analysis_source=AnalysisSource.JOB_DATA,
            prompt_version=interpretation.prompt_version,
            ai_provider=interpretation.provider,
            ai_model=interpretation.model,
            model_run_id=interpretation.run_id,
        )
        if not analysis.cached:
            # Written together with these rows, and only with them: the
            # report describes exactly the requirements just stored.
            self._record_reconciliation(job, interpretation.requirements)
        return analysis

    def _record_reconciliation(
        self, job: Job, ai_rows: Sequence[Requirement]
    ) -> None:
        """Cross-check the model's rows against the rule's and store the verdict.

        The deterministic extractor runs again over the same description
        purely to disagree with the model - its rows are never stored
        here, only the count of what the two readings could not settle.
        """
        description = job.description_text or job.description_raw or ""
        report = reconcile(
            extract_requirements(description, raw=job.description_raw or None),
            ai_rows,
        )
        log.info(
            "requirements cross-checked",
            extra={
                "job": {"id": job.id},
                "reconciliation": {"conflicts": report.conflict_count},
            },
        )
        self.repository.patch_metadata(
            job.id, {RECONCILIATION_KEY: report.to_metadata()}
        )

    def _current_analysis(self, job: Job) -> RequirementAnalysis:
        """Requirements already computed for the text now on the job.

        The per-analyzer cache keys answer "has *this* extractor run on
        this content"; matching asks a different question: is there a
        successful reading of the current text at all? An AI
        interpretation counts, so matching never re-extracts over the
        model's rows - the deterministic key would miss after an AI-only
        analysis and replace them. When no reading exists, this falls
        back to the ordinary deterministic analysis, and clears any
        reconciliation the replaced rows carried.
        """
        content_hash = content_fingerprint(job)
        row = self.repository.find_current_analysis(
            job.id, content_hash=content_hash
        )
        if row is None:
            analysis = analyze_job(job, self.repository)
            if RECONCILIATION_KEY in job.metadata:
                self.repository.patch_metadata(job.id, {RECONCILIATION_KEY: None})
            return analysis
        return RequirementAnalysis(
            requirements=self.repository.requirements(job.id),
            content_hash=content_hash,
            analysis_id=str(row.get("id", "")),
            cached=True,
        )

    # -- model runs ----------------------------------------------------------
    def record_model_run(self, run: ModelRun) -> str:
        """Persist one model run - an embedding included - in the registry.

        Exposed so a scorer built outside this service (the CLI's
        ``--scorer embedding``) can file its runs through the same
        repository the interpret path uses, instead of each caller
        inventing its own sink.
        """
        return self._model_runs.save(run)

    # -- matching ------------------------------------------------------------
    def match(self, job_id: str, *, scorer: Any = _SCORER_UNSET) -> MatchOutcome:
        """Match one job against the candidate, via the match cache.

        Analysis runs first (it is cached too), so a caller may match a
        job it has never analysed and get the same verdict as one that
        has. When the cross-checker recorded disagreements between two
        extractions, they ride along: a verdict two readings contradicted
        is promoted to review instead of deciding alone.

        Args:
            job_id: The posting to judge.
            scorer: Override the scorer for this call - the CLI's
                ``--scorer`` flag reaches in here. Omit to use the scorer
                the service was built with (``None`` by default: claims
                and facts only). The scorer's identity becomes part of
                the match cache key, so switching scorers recomputes
                rather than replays.
        """
        job = self.get(job_id)
        analysis = self._current_analysis(job)
        # A report exists only for the rows currently stored; a fresh
        # extraction just cleared it, and passing its count anyway would
        # promote a verdict the rows no longer support.
        conflicts = conflict_count(job.metadata) if analysis.cached else 0
        extraction_status = job.metadata.get("extraction_status")
        chosen = self._scorer if scorer is _SCORER_UNSET else scorer
        outcome = match_job(
            job,
            analysis.requirements,
            self.evidence(),
            self.repository,
            candidate_id=self._candidate_id,
            scorer=chosen,  # type: ignore[arg-type]
            extraction_status=extraction_status,
            conflicts=conflicts,
        )
        self._record_review(
            job,
            outcome,
            analysis=analysis,
            conflicts=conflicts,
            extraction_status=extraction_status,
        )
        return outcome

    # -- review lifecycle ----------------------------------------------------
    def _record_review(
        self,
        job: Job,
        outcome: MatchOutcome,
        *,
        analysis: RequirementAnalysis,
        conflicts: int,
        extraction_status: Any,
    ) -> None:
        """Persist the doubt behind this match - or close a stale one.

        Two things put a review on record: the match itself asking for a
        human (its derived reasons), and a *suspicious analysis* the
        match was confident enough to wave through - a fallback that
        replaced a failed model reading, or a description that never
        fully arrived. The second kind is captured even when the
        decision is ``MATCH``: a confident verdict built on a broken
        reading is exactly what a human should glance at.

        When neither holds and a review is open, the doubt is gone and
        the row is closed with a note saying so. A resolved row is never
        rewritten unless the doubt itself changes - that rule lives in
        the repository, not here.
        """
        reasons = list(outcome.review_reasons)
        status_upper = str(extraction_status or "").upper()
        suspicious = (
            bool(analysis.ai_fallback)
            or self.repository.has_failed_attempt(
                job.id, content_hash=analysis.content_hash
            )
            or status_upper in _INCOMPLETE_EXTRACTIONS
        )
        supporting = {
            "decision": outcome.result.decision.value,
            "gate_status": outcome.result.gate.status.value,
            "conflicts": int(conflicts),
            "extraction_status": extraction_status,
            "ai_fallback": bool(analysis.ai_fallback),
            "similarity_score": outcome.result.similarity_score,
        }
        if not reasons and not suspicious:
            self._reviews.clear(
                job.id,
                self._candidate_id,
                note="re-match no longer raises this doubt",
            )
            return
        if not reasons:
            # The match is confident, but the analysis behind it was not:
            # name the doubt the way the queue already names it.
            reasons = [ReviewReason.JD_EXTRACTION_INCOMPLETE]
        self._reviews.record(
            job_id=job.id,
            candidate_id=self._candidate_id,
            decision=outcome.result.decision,
            reasons=reasons,
            supporting=supporting,
        )

    def resolve_review(self, job_id: str, *, note: str = "") -> bool:
        """Mark this candidate's review for the posting resolved.

        Returns:
            ``True`` when an open review transitioned; ``False`` when
            there was none to resolve (never recorded, or already
            answered) - see :meth:`database.repositories.reviews.
            ReviewRepository.resolve`.
        """
        return self._reviews.resolve(job_id, self._candidate_id, note=note)

    def review_status(self, job_id: str) -> Optional[str]:
        """The persisted lifecycle state for this posting, or ``None``."""
        row = self._reviews.find(job_id, self._candidate_id)
        return str(row["status"]) if row else None

    def open_review_count(self) -> int:
        """How many recorded doubts are still open for this candidate."""
        return self._reviews.count_open(self._candidate_id)

    def report(self, job_id: str, *, scorer: Any = _SCORER_UNSET) -> MatchReport:
        """The eleven-dimension report for one job.

        Built on top of :meth:`match`, so every rule the verdict obeys -
        cache keys, gate precedence, conflict promotion - applies here
        unchanged; the report explains the decision, it never re-decides
        it. The same ``scorer`` override as :meth:`match` applies.

        Args:
            job_id: The posting to report on.
            scorer: Override the scorer for this call, as in
                :meth:`match`.
        """
        outcome = self.match(job_id, scorer=scorer)
        job = self.get(job_id)
        analysis = self._current_analysis(job)
        return build_report(
            job, analysis.requirements, self.evidence(), outcome.result
        )

    # -- resume relevance ----------------------------------------------------
    def _stored_resumes(self) -> list[object]:
        """The candidate's resumes: injected by tests, loaded from the store."""
        if self._resume_provider is not None:
            return self._resume_provider()
        loaded = [
            self._resumes.load(row["id"])
            for row in self._resumes.for_candidate(self._candidate_id)
        ]
        return [resume for resume in loaded if resume is not None]

    def relevance(self, job_id: str) -> ResumeRelevance:
        """Which stored resume fits this posting, and why.

        Reads only what is already stored - the analysed rows and the
        resumes themselves. Nothing is fetched or generated, and no
        recommendation is ever invented: an empty store, an unmeasurable
        posting, or a zero-coverage lineup each come back as
        ``INSUFFICIENT_EVIDENCE`` with a reason a human can act on.

        Args:
            job_id: The posting to select a resume for.
        """
        job = self.get(job_id)
        analysis = self._current_analysis(job)
        return recommend_resume(job, analysis.requirements, self._stored_resumes())

    # -- explanation ---------------------------------------------------------
    def explain(self, job_id: str) -> MatchExplanation:
        """The audit record for the stored match, not a fresh verdict.

        Raises:
            JobNotFoundError: When no match has been stored for this job
                and candidate — explaining a decision that was never made
                would mean inventing one.
        """
        rows = self.repository.matches(
            job_id=job_id, candidate_id=self._candidate_id, limit=1
        )
        if not rows:
            raise JobNotFoundError(
                f"no stored match for job {job_id!r} and candidate "
                f"{self._candidate_id!r}; run match first",
                job_id=job_id,
            )
        result = MatchResult.model_validate(rows[0]["explanation"])
        return explain_match(
            result,
            self.repository.requirements(job_id),
            self.evidence(),
            job=self.get(job_id),
        )

    # -- review --------------------------------------------------------------
    def review_queue(self) -> ReviewQueue:
        """What still waits for a human: queued matches plus open captures.

        Match-derived items arrive newest first, each annotated with its
        persisted lifecycle state; items a human already resolved drop
        out until their doubt changes. Open *captured* reviews whose
        match itself did not queue (the suspicious-analysis path) are
        appended - a doubt nobody can see is not a capture.
        """
        queue = ReviewQueue.from_rows(
            self.repository.review_required(candidate_id=self._candidate_id)
        )
        statuses = self._reviews.statuses_for(
            [item.job_id for item in queue.items], self._candidate_id
        )
        kept: list[ReviewItem] = []
        for item in queue.items:
            item.status = statuses.get(item.job_id)
            if item.status == "RESOLVED":
                continue
            kept.append(item)
        known = {item.job_id for item in kept}
        for row in self._reviews.open_reviews(self._candidate_id):
            if str(row.get("job_id")) not in known:
                kept.append(ReviewItem.from_review_row(row))
        queue.items = kept
        return queue
