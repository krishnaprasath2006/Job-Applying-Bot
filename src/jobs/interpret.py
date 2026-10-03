"""AI interpretation of a job description: an opinion with a check attached.

The raw posting stays authoritative. A model is asked for requirements and
must answer in the pinned schema (:class:`jobs.extraction_schema.RequirementExtraction`),
every requirement must quote the span it came from, and that span must
actually appear in the posting we hold. A response that fails any of this
raises :class:`~core.errors.AIResponseValidationError` — it is never
coerced into something plausible, and never reaches the matcher.

Falling back is the caller's decision, not this module's: :func:`interpret`
raises, and the service catches, records the failed attempt against the
cache key it was tried under, and runs the deterministic extractor instead.
The failure is then visible (a ``FAILED`` analysis row, a log line) rather
than indistinguishable from success.

Grounding: the prompt is built only from the posting, so every run is
recorded ``JOB_DATA``, never ``AI_GENERAL``. No candidate data enters this
module's prompts — a model that has seen the candidate cannot be asked to
report only what the job says.
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.enums import AnalysisSource, ModelRunTask
from core.errors import AIResponseValidationError
from core.logging_config import get_logger
from jobs.extraction_schema import RequirementExtraction
from jobs.models import Requirement, RequirementKind
from jobs.normalizer import normalize_text

__all__ = [
    "INTERPRETER",
    "INTERPRETER_VERSION",
    "PROMPT_VERSION",
    "Interpretation",
    "build_prompt",
    "error_code_for",
    "interpret",
    "interpret_prompt_version",
    "validate_extraction",
]

log = get_logger(__name__)

#: Cache identity of this interpreter, mirroring ``jobs.analysis``'s
#: ``ANALYZER``/``ANALYZER_VERSION`` pair. Bump the version whenever the
#: prompt or the validation rules change: old rows stay for audit, they
#: are simply never matched again.
INTERPRETER = "ai_interpret_requirements"
INTERPRETER_VERSION = "1"

#: Base prompt version. The composed version that reaches cache keys and
#: model-run rows adds the provider and model, so switching models is a
#: different key rather than a stale hit.
PROMPT_VERSION = "ai-1"

#: Longest posting sent to the model. Beyond this the marginal text is
#: boilerplate, and an unbounded prompt is how a context window turns a
#: reading into a truncation.
MAX_PROMPT_CHARS = 20_000

#: Below this length an empty extraction is a plausible reading; above it,
#: a model that found nothing did not read the posting.
EMPTY_IS_SUSPICIOUS_ABOVE = 150

_SYSTEM_PROMPT = (
    "You read job postings and report their requirements. "
    "Answer only from the posting text supplied. "
    "For every requirement quote a short verbatim span from the posting "
    "as evidence. Never invent requirements, employers, or years."
)

_PROMPT_TEMPLATE = """\
Report the requirements this job posting states, in the order they appear.

For each requirement:
- text: the requirement as the posting states it
- category: one of {categories}
- priority: REQUIRED, PREFERRED, or UNKNOWN when the posting does not say
- min_years: a number only when the text states a number of years
- evidence: a verbatim span from the posting this reading came from
- confidence: your confidence in [0, 1]

Job posting:
---
{description}
---
"""


class Interpretation(BaseModel):
    """One AI reading of a posting, plus the run that produced it.

    Attributes:
        requirements: The reading as stored requirements, AI-attributed
            and merged by the shared rule.
        prompt_version: The composed key this reading was tried under.
        provider: Provider key that answered.
        model: Model that answered.
        run_id: The ``model_runs`` row for the call, when one was
            persisted.
        used_ai: ``False`` only on the service's fallback path; kept on
            the result so a caller can tell which it got without
            comparing fingerprints.
    """

    model_config = ConfigDict(extra="forbid")

    requirements: list[Requirement] = Field(default_factory=list)
    prompt_version: str = PROMPT_VERSION
    provider: str = ""
    model: str = ""
    run_id: str = ""
    used_ai: bool = True


def interpret_prompt_version(
    provider_name: str, model: Optional[str] = None
) -> str:
    """The composed cache/model-run identity for one provider+model pair.

    Deterministic parts only: a different model is a different key, so a
    requirement set produced by model A can never be served as model B's
    reading of the same posting.
    """
    return f"{PROMPT_VERSION}:{provider_name or 'unknown'}:{model or 'default'}"


#: Stable codes for AI failures. Typed so callers branch and tests assert
#: without string matching against human sentences.
_ERROR_CODES = {
    "ProviderUnavailableError": "PROVIDER_UNAVAILABLE",
    "ProviderTimeoutError": "PROVIDER_TIMEOUT",
    "ModelNotFoundError": "MODEL_NOT_FOUND",
    "AIResponseValidationError": "RESPONSE_INVALID",
}


def error_code_for(exc: BaseException) -> str:
    """The stable code for one AI failure."""
    return _ERROR_CODES.get(type(exc).__name__, "AI_PROVIDER_ERROR")


def build_prompt(description: str) -> str:
    """The user prompt for one posting.

    Grounded in the posting only, truncated at
    :data:`MAX_PROMPT_CHARS` so the request is bounded no matter what
    arrived from the source.
    """
    categories = ", ".join(sorted(kind.value for kind in RequirementKind))
    text = (description or "").strip()[:MAX_PROMPT_CHARS]
    return _PROMPT_TEMPLATE.format(categories=categories, description=text)


def validate_extraction(
    extraction: RequirementExtraction, *, description: str
) -> None:
    """Check the reading against the posting it claims to describe.

    Three failure modes, all raising
    :class:`~core.errors.AIResponseValidationError`:

    * nothing found in a posting long enough to have said something;
    * a requirement with no evidence span;
    * an evidence span that does not appear in the posting we hold.

    A span that is not in the posting is the dangerous case: it reads as
    support and cites nothing, which is exactly how a plausible invention
    would travel.
    """
    text = (description or "").strip()
    if not extraction.requirements and len(text) >= EMPTY_IS_SUSPICIOUS_ABOVE:
        raise AIResponseValidationError(
            "model returned no requirements for a non-trivial posting",
            interpreter=INTERPRETER,
            prompt_version=INTERPRETER_VERSION,
            description_chars=len(text),
        )
    lowered = normalize_text(text).lower()
    for index, row in enumerate(extraction.requirements):
        evidence = (row.evidence or "").strip()
        if not evidence:
            raise AIResponseValidationError(
                "requirement came back without an evidence span",
                interpreter=INTERPRETER,
                index=index,
                text=row.text[:120],
            )
        if normalize_text(evidence).lower() not in lowered:
            raise AIResponseValidationError(
                "evidence excerpt does not appear in the posting",
                interpreter=INTERPRETER,
                index=index,
                evidence=evidence[:120],
            )


def interpret(
    description: str,
    *,
    provider: Any,
    raw: Optional[str] = None,
    model: Optional[str] = None,
    prompt_version: Optional[str] = None,
    run_sink: Optional[Callable[[Any], None]] = None,
) -> Interpretation:
    """Read one posting's requirements with a model. Strictly.

    Args:
        description: The normalised posting text; the only grounding.
        provider: Something satisfying :class:`ai.provider.AIProvider`.
        raw: The posting's markup, when available. Kept for signature
            parity with ``extract_requirements``; the model is shown
            normalised text because HTML teaches it nothing.
        model: Model override for this call.
        prompt_version: Composed version to record; defaults to
            provider-derived.
        run_sink: Called with the :class:`core.model_run.ModelRun` on
            success (as ``SUCCESS``) and on a validation rejection (as
            ``FAILED``), so the caller persists the audit row either way.
            A provider-level failure never reaches this — the provider
            has already marked its own run failed before raising.

    Returns:
        The requirements, AI-attributed, with the run identity.

    Raises:
        AIResponseValidationError: The response failed schema or
            grounding checks. The caller decides what to do instead.
        AIProviderError: The provider itself failed (unreachable,
            timed out, returned unparseable output).
    """
    del raw  # markup adds tokens, not information, to this prompt
    version = prompt_version or interpret_prompt_version(
        getattr(provider, "name", "unknown"), model or getattr(provider, "model", None)
    )
    prompt = build_prompt(description)
    result = provider.generate_structured(
        prompt,
        RequirementExtraction,
        task=ModelRunTask.EXTRACT,
        analysis_source=AnalysisSource.JOB_DATA,
        system=_SYSTEM_PROMPT,
        model=model,
        prompt_version=version,
    )
    extraction = result.value
    try:
        validate_extraction(extraction, description=description)
    except AIResponseValidationError as exc:
        # The model answered; our checks rejected the answer. The run
        # itself is still an audit fact — persist it as failed, so the
        # rejected response leaves a trace instead of vanishing.
        failed = result.run.fail(f"response validation failed: {exc}")
        if run_sink is not None:
            run_sink(failed)
        details = dict(exc.details)
        details["run_id"] = failed.id
        raise AIResponseValidationError(str(exc.message), **details) from exc
    if run_sink is not None:
        run_sink(result.run)
    requirements = extraction.to_requirements()
    log.info(
        "ai interpretation completed",
        extra={
            "ai": {
                "provider": result.run.provider,
                "model": result.run.model,
                "requirements": len(requirements),
            }
        },
    )
    return Interpretation(
        requirements=requirements,
        prompt_version=version,
        provider=result.run.provider,
        model=result.run.model,
        run_id=result.run.id,
        used_ai=True,
    )
