"""The analysis cache: reuse a previous verdict exactly while it is still
true, and recompute the moment anything it rested on changed.

Two verdicts are cached, each keyed by fingerprints of its own inputs:

* **Requirements** — keyed by ``(content_hash, analyzer, analyzer_version,
  prompt_version)``. An edited posting hashes differently, so its old
  requirements can never be read back as current. The requirement rows
  themselves live in the database keyed by job, and a re-analysis replaces
  them, so a cache hit reads exactly what the recorded analysis read.
* **Match** — keyed by ``(job_id, candidate_id, requirements_fingerprint,
  candidate_fingerprint)``. Change the candidate, the requirements, or
  either fingerprint and the stored decision is simply a different key:
  nothing stale can be served, because staleness would be a new key.

Persistence reaches this module through :class:`AnalysisStore`, a
structural protocol — `database.repositories.JobRepository` satisfies it
without `jobs` ever importing `database`. The layering stays
``jobs -> core``; the wiring is CP10's JobService's job.

What is deliberately *not* cached: gate results and scores on their own.
They are recomputed from the same fingerprints or not at all — a half
cache, where a gate could be fresh and its scores old, is worse than no
cache because it cannot be spotted.
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AnalysisSource, HardGateStatus, MatchDecision, ReviewReason
from core.hashing import sha256_text
from core.logging_config import get_logger
from jobs.candidate import CandidateEvidence
from jobs.explain import explain_match
from jobs.hard_gate import HardGateResult
from jobs.matching import MatchResult, evaluate_match
from jobs.models import Job, Requirement
from jobs.reconcile import apply_conflicts
from jobs.requirements import extract_requirements
from jobs.review import derive_review_reasons

if TYPE_CHECKING:
    # Typing only: the cache names the scorer protocol without holding a
    # provider, the same seam matching keeps.
    from ai.embeddings import SemanticScorer

__all__ = [
    "ANALYZER",
    "ANALYZER_VERSION",
    "AnalysisStore",
    "MatchOutcome",
    "RequirementAnalysis",
    "analyze_job",
    "candidate_fingerprint",
    "content_fingerprint",
    "match_job",
    "requirements_fingerprint",
    "scorer_fingerprint",
]

log = get_logger(__name__)

#: Identity of the extractor whose output may be reused. Bump
#: ``ANALYZER_VERSION`` whenever extraction logic changes; old rows stay in
#: the table for audit, they are just never matched again.
ANALYZER = "extract_requirements"
ANALYZER_VERSION = "1"


@runtime_checkable
class AnalysisStore(Protocol):
    """The persistence the cache needs, and nothing else.

    Methods mirror `database.repositories.JobRepository` exactly; a
    structural match is enough, and this module holds no connection, no
    cursor, and no SQL.
    """

    def find_cached_analysis(
        self,
        job_id: str,
        *,
        content_hash: str,
        analyzer: str,
        analyzer_version: str,
        prompt_version: Optional[str] = None,
    ) -> Optional[Mapping[str, Any]]: ...

    def requirements(self, job_id: str) -> list[Requirement]: ...

    def replace_requirements(self, job_id: str, requirements: Iterable[Requirement]) -> int: ...

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
    ) -> str: ...

    def find_cached_match(
        self,
        job_id: str,
        candidate_id: str,
        *,
        requirements_fingerprint: str,
        candidate_fingerprint: str,
        scorer_fingerprint: str = "",
    ) -> Optional[Mapping[str, Any]]: ...

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
    ) -> str: ...


class RequirementAnalysis(BaseModel):
    """Requirements for one job, freshly extracted or served from cache.

    Attributes:
        requirements: The rows, in document order either way — a cache hit
            must be indistinguishable from a re-run.
        content_hash: The description fingerprint the key was built from.
        analysis_id: The ``job_analyses`` row behind this result.
        cached: Whether the store already had it.
        ai_fallback: An AI attempt was made, failed validation or the
            provider, and these requirements came from the deterministic
            extractor instead. The attempt is recorded as ``FAILED`` under
            the AI cache key, so this is never served as an AI result.
        ai_error_code: Which failure sent the fallback path.
    """

    model_config = ConfigDict(extra="forbid")

    requirements: list[Requirement] = Field(default_factory=list)
    content_hash: str = ""
    analysis_id: str = ""
    cached: bool = False
    ai_fallback: bool = False
    ai_error_code: Optional[str] = None


class MatchOutcome(BaseModel):
    """A match result, freshly computed or served from cache.

    The stored ``explanation`` column holds the full ``MatchResult``
    dump — decision, gate, and scores — because the rendered report is
    derivable from that and the reverse is not.
    """

    model_config = ConfigDict(extra="forbid")

    result: MatchResult
    match_id: str = ""
    cached: bool = False
    requirements_fingerprint: str = ""
    candidate_fingerprint: str = ""
    scorer_fingerprint: str = ""
    review_reasons: list[ReviewReason] = Field(default_factory=list)


def content_fingerprint(job: Job) -> str:
    """Fingerprint of the description an analysis rests on.

    The stored hash when the job carries one, otherwise a hash of whatever
    description text exists. A job with no description yet fingerprints as
    the empty string — all such rows share one key per job id, which is
    correct: they would all extract to nothing.
    """
    if job.description_hash:
        return job.description_hash
    return sha256_text(job.description_text or job.description_raw or "")


def requirements_fingerprint(requirements: Sequence[Requirement]) -> str:
    """Fingerprint of everything a verdict about requirements could rest on.

    Text, kind, priority, years, ambiguity, and confidence — in order,
    because order is what the matcher scores in. Anything left out would be
    a way for a changed requirement to read as unchanged.
    """
    parts = [
        "|".join(
            (
                requirement.text,
                requirement.normalized or "",
                requirement.kind.value,
                requirement.priority.value,
                "" if requirement.min_years is None else f"{requirement.min_years:g}",
                "1" if requirement.ambiguous else "0",
                f"{requirement.confidence:.4f}",
            )
        )
        for requirement in requirements
    ]
    return sha256_text("\n".join(parts))


def candidate_fingerprint(evidence: CandidateEvidence) -> str:
    """Fingerprint of everything a verdict about the candidate could rest on.

    The claims in order (lookup order matters: the first claim that
    answers wins), their truth status and field, plus the years and
    sponsorship answers. Evidence excerpts are left out: they quote a
    value without changing it.
    """
    parts = [
        f"years={evidence.years_of_experience!r}",
        f"sponsorship={evidence.requires_sponsorship!r}",
    ]
    parts.extend(
        "|".join(
            (
                claim.text,
                claim.normalized,
                claim.kind.value if claim.kind is not None else "",
                claim.source.status.value,
                claim.source.field_path,
            )
        )
        for claim in evidence.claims
    )
    return sha256_text("\n".join(parts))


def analyze_job(
    job: Job,
    store: AnalysisStore,
    *,
    extract: Callable[..., list[Requirement]] = extract_requirements,
    analyzer: str = ANALYZER,
    analyzer_version: str = ANALYZER_VERSION,
    analysis_source: AnalysisSource = AnalysisSource.JOB_DATA,
    prompt_version: Optional[str] = None,
    ai_provider: Optional[str] = None,
    ai_model: Optional[str] = None,
    model_run_id: Optional[str] = None,
    status: str = "SUCCESS",
    error_code: Optional[str] = None,
) -> RequirementAnalysis:
    """Requirements for one job, via the cache.

    Args:
        job: The posting; its description and id form the key.
        store: Persistence satisfying :class:`AnalysisStore`.
        extract: Extraction callable used on a miss, injectable so callers
            may route through a model without this module importing one.
            It is called as ``extract(text, raw=markup)`` — the same shape
            as :func:`extract_requirements` — with the job's normalised
            text and its markup when it has any.
        analyzer / analyzer_version: Identity of the extractor whose
            output may be reused. Defaults to the deterministic one; an AI
            interpreter passes its own so the two never share cache rows.
        analysis_source: Which kind of data produced the requirements,
            recorded with the analysis.
        prompt_version / ai_provider / ai_model / model_run_id: Identity of
            a model run, when there was one; ``None`` for the deterministic
            path.
        status: Recorded status for this analysis. ``FAILED`` rows are
            written but never served (the store returns ``SUCCESS`` only),
            which is how a failed attempt stays visible and still gets
            retried.
        error_code: Why the attempt failed, when ``status`` is not
            ``SUCCESS``.

    Returns:
        The requirements and the cache verdict. A hit reads the stored
        rows; a miss extracts, replaces them, and records the analysis so
        the next identical call is a hit.
    """
    content_hash = content_fingerprint(job)
    hit = store.find_cached_analysis(
        job.id,
        content_hash=content_hash,
        analyzer=analyzer,
        analyzer_version=analyzer_version,
        prompt_version=prompt_version,
    )
    if hit is not None:
        log.info("analysis cache hit", extra={"job": {"id": job.id}})
        return RequirementAnalysis(
            requirements=store.requirements(job.id),
            content_hash=content_hash,
            analysis_id=str(hit.get("id", "")),
            cached=True,
        )
    description = job.description_text or job.description_raw or ""
    requirements = extract(description, raw=job.description_raw or None)
    store.replace_requirements(job.id, requirements)
    analysis_id = store.record_analysis(
        job.id,
        content_hash=content_hash,
        analyzer=analyzer,
        analyzer_version=analyzer_version,
        analysis_source=analysis_source,
        requirement_count=len(requirements),
        status=status,
        ai_provider=ai_provider,
        ai_model=ai_model,
        prompt_version=prompt_version,
        error_code=error_code,
        model_run_id=model_run_id,
    )
    log.info(
        "analysis recorded",
        extra={
            "job": {"id": job.id},
            "analysis": {
                "requirements": len(requirements),
                "cached": False,
                "status": status,
            },
        },
    )
    return RequirementAnalysis(
        requirements=requirements,
        content_hash=content_hash,
        analysis_id=analysis_id,
        cached=False,
        ai_fallback=status != "SUCCESS",
        ai_error_code=error_code if status != "SUCCESS" else None,
    )


def scorer_fingerprint(scorer: Optional[Any]) -> str:
    """Identity of the scorer a verdict would rest on.

    Part of the match cache key: switching from no scorer to lexical, or
    from one embedding model to another, must recompute rather than replay
    the previous verdict. ``None`` - no scorer, claims and facts only -
    fingerprints as the empty string, which is also what rows written
    before this key existed carry, so old cache rows stay reachable exactly
    as long as they are still true.

    A scorer's own ``scorer_id`` is preferred; anything without one falls
    back to its class name, which still separates implementations even
    when it cannot separate their configurations.
    """
    if scorer is None:
        return ""
    explicit = getattr(scorer, "scorer_id", None)
    if isinstance(explicit, str) and explicit:
        return explicit
    cls = type(scorer)
    module = (cls.__module__ or "").rsplit(".", 1)[-1]
    return f"{module}.{cls.__qualname__}"


def match_job(
    job: Job,
    requirements: Sequence[Requirement],
    evidence: CandidateEvidence,
    store: AnalysisStore,
    *,
    candidate_id: str,
    scorer: Optional["SemanticScorer"] = None,
    gate: Optional[HardGateResult] = None,
    extraction_status: Optional[str] = None,
    conflicts: int = 0,
    analysis_source: AnalysisSource = AnalysisSource.JOB_DATA,
    ai_provider: Optional[str] = None,
    ai_model: Optional[str] = None,
    prompt_version: Optional[str] = None,
    model_run_id: Optional[str] = None,
) -> MatchOutcome:
    """Match one job against one candidate, via the cache.

    Args:
        job: The posting being judged.
        requirements: The rows the match runs over - usually from
            :func:`analyze_job`.
        evidence: The candidate's claims and facts.
        store: Persistence satisfying :class:`AnalysisStore`.
        candidate_id: Whose profile this is; part of the key.
        scorer: Similarity implementation, or ``None`` for claims-and-
            facts-only matching. Its :func:`scorer_fingerprint` is part
            of the cache key, so one scorer's verdict is never replayed
            as another's.
        gate: A precomputed gate result to reuse.
        extraction_status: Job extraction status, folded into the review
            reasons when the job's description never fully arrived.
        conflicts: The cross-checker's count of disagreements between two
            extractions of this posting (see :mod:`jobs.reconcile`).
            Above zero a verdict that would have decided alone is
            promoted to ``REVIEW_REQUIRED`` and the reason is stored with
            it. The report is always written together with the rows it
            describes, and those rows are what the requirements
            fingerprint covers - so a changed reconciliation means a
            different key, and the cached hit below can replay what it
            stored without re-deriving anything.

    Returns:
        The decision, its fingerprints, and the review reasons stored with
        it. A cached hit reconstructs the stored ``MatchResult`` exactly -
        same gate checks, same scores - and re-derives nothing.
    """
    requirements_fp = requirements_fingerprint(requirements)
    candidate_fp = candidate_fingerprint(evidence)
    scorer_fp = scorer_fingerprint(scorer)
    hit = store.find_cached_match(
        job.id,
        candidate_id,
        requirements_fingerprint=requirements_fp,
        candidate_fingerprint=candidate_fp,
        scorer_fingerprint=scorer_fp,
    )
    if hit is not None:
        log.info("match cache hit", extra={"job": {"id": job.id}})
        return MatchOutcome(
            result=MatchResult.model_validate(hit["explanation"]),
            match_id=str(hit.get("id", "")),
            cached=True,
            requirements_fingerprint=requirements_fp,
            candidate_fingerprint=candidate_fp,
            scorer_fingerprint=scorer_fp,
            review_reasons=[ReviewReason(value) for value in (hit.get("review_reasons") or [])],
        )

    result = evaluate_match(requirements, evidence, scorer=scorer, gate=gate)
    result = apply_conflicts(result, conflicts)
    explanation = explain_match(result, requirements, evidence, job=job)
    reasons = derive_review_reasons(
        result,
        explanation=explanation,
        extraction_status=extraction_status,
        conflicts=conflicts,
    )
    counts = _evaluation_counts(result)
    match_id = store.save_match(
        job_id=job.id,
        candidate_id=candidate_id,
        decision=result.decision,
        hard_gate_status=result.gate.status,
        analysis_source=analysis_source,
        requirements_fingerprint=requirements_fp,
        candidate_fingerprint=candidate_fp,
        scorer_fingerprint=scorer_fp,
        explanation=result.model_dump(mode="json"),
        matched_count=counts.matched,
        mismatched_count=counts.mismatched,
        unknown_count=counts.unknown,
        semantic_score=result.similarity_score,
        ai_provider=ai_provider,
        ai_model=ai_model,
        prompt_version=prompt_version,
        model_run_id=model_run_id,
        evidence=[
            row.candidate.model_dump(mode="json")
            for row in explanation.rows
            if row.candidate is not None
        ],
        review_reasons=[reason.value for reason in reasons],
    )
    log.info(
        "match recorded",
        extra={
            "job": {"id": job.id},
            "match": {"decision": result.decision.value, "cached": False},
        },
    )
    return MatchOutcome(
        result=result,
        match_id=match_id,
        cached=False,
        requirements_fingerprint=requirements_fp,
        candidate_fingerprint=candidate_fp,
        scorer_fingerprint=scorer_fp,
        review_reasons=reasons,
    )


class _Counts(BaseModel):
    matched: int = 0
    mismatched: int = 0
    unknown: int = 0


def _evaluation_counts(result: MatchResult) -> _Counts:
    """Counts across both the gate's rows and the scorer's — every row the
    verdict rested on, not half of them."""
    evaluations = [check.evaluation for check in result.gate.checks] + [
        score.evaluation for score in result.scores
    ]
    return _Counts(
        matched=sum(1 for evaluation in evaluations if evaluation.is_match),
        mismatched=sum(1 for evaluation in evaluations if evaluation.is_mismatch),
        unknown=sum(1 for evaluation in evaluations if evaluation.is_uncertain),
    )
