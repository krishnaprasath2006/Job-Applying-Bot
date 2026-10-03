"""Resume relevance: which stored resume fits this posting, and why.

Selection here is deliberately narrow: it reads only evidence that already
exists in the repository - the posting's requirement rows and each stored
resume's declared skills and skills section (falling back to the resume's
own text when it declares neither). Nothing is fetched, nothing is
generated, and the same inputs always produce the same pick.

The vocabulary is :class:`~core.enums.ResumeRelevanceDecision`:

``RECOMMENDED``
    One resume covers strictly more of the posting's stated skills than
    every other, and covers at least one. ``recommended_resume_id`` names
    it; ``runner_up_resume_id`` names the closest rival when there is one.
``REVIEW_REQUIRED``
    Two or more resumes tie. A tie is a human's decision, not a
    coin-flip's: ``recommended_resume_id`` stays empty on purpose.
``INSUFFICIENT_EVIDENCE``
    No resumes are stored, the posting states no measurable skills, or no
    resume covers anything it states. A zero is reported as a zero with a
    reason - never promoted to a recommendation.

``confidence`` is the winner's coverage of the measurable rows: how much
of what the posting asked for the pick actually answers. A perfect
coverage with a perfect tie is still a tie - confidence says how much was
covered, the decision says whether the pick was unambiguous.
"""

from __future__ import annotations

import re
from typing import Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.enums import ResumeRelevanceDecision
from jobs.models import Job, Requirement, RequirementKind

__all__ = [
    "ResumeCandidateScore",
    "ResumeRelevance",
    "recommend_resume",
]

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")

#: Words a skill row carries that name no skill. Left in, "years" would
#: make "3+ years of experience" cover any resume that ever mentioned a
#: year, "of" would make any two-word phrase cover everything, and
#: "strong" would cover the strong and the weak alike.
_GENERIC = frozenset(
    {
        "a",
        "an",
        "ability",
        "and",
        "are",
        "background",
        "bonus",
        "deep",
        "experience",
        "familiarity",
        "for",
        "good",
        "hands",
        "in",
        "is",
        "knowledge",
        "must",
        "nice",
        "of",
        "on",
        "or",
        "plus",
        "preferred",
        "required",
        "requirement",
        "strong",
        "the",
        "to",
        "understanding",
        "with",
        "year",
        "years",
    }
)

#: Rows of these kinds can be covered by a resume's declared skills.
#: (COMPENSATION and LOCATION rows are about terms, not coverage.)
_COVERABLE_KINDS = frozenset(
    {
        RequirementKind.SKILL,
        RequirementKind.TOOL,
        RequirementKind.TECHNOLOGY,
        RequirementKind.PROGRAMMING_LANGUAGE,
        RequirementKind.FRAMEWORK,
        RequirementKind.DATABASE,
        RequirementKind.CLOUD,
        RequirementKind.LANGUAGE,
        RequirementKind.SOFT_SKILL,
        RequirementKind.CERTIFICATION,
        RequirementKind.EDUCATION,
        RequirementKind.DOMAIN,
        RequirementKind.OTHER,
    }
)


class ResumeCandidateScore(BaseModel):
    """How one resume stands against the posting's measurable rows."""

    model_config = ConfigDict(extra="forbid")

    resume_id: str
    coverage: float = Field(ge=0.0, le=1.0)
    covered: list[str] = Field(default_factory=list)
    missed: list[str] = Field(default_factory=list)


class ResumeRelevance(BaseModel):
    """The pick, the reason, and the scores behind both."""

    model_config = ConfigDict(extra="forbid")

    decision: ResumeRelevanceDecision
    recommended_resume_id: Optional[str] = None
    runner_up_resume_id: Optional[str] = None
    reason: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    scores: list[ResumeCandidateScore] = Field(default_factory=list)


def _tokens(text: str) -> frozenset[str]:
    words = _TOKEN_RE.findall(text.lower())
    # A token without a letter is a requirement a resume can never
    # contain: "3+" would otherwise demand the digit-and-plus appear in
    # the document. "c++" and "5g" have letters, so they stay.
    return frozenset(
        word for word in words if any(character.isalpha() for character in word)
    ) - _GENERIC


def _resume_tokens(resume: object) -> frozenset[str]:
    """A resume's own words: declared skills first, its content as fallback.

    ``skills`` is metadata the candidate filled in; the skills section is
    what the document actually says. Either is evidence; when a resume
    declares neither, its text is the only witness it has.
    """
    skills = list(getattr(resume, "skills", ()) or ())
    tokens: set[str] = set()
    for skill in skills:
        tokens.update(_tokens(skill))
    for section in getattr(resume, "sections", ()) or ():
        kind = getattr(section, "section_type", None)
        if getattr(kind, "value", kind) == "SKILLS":
            section_text = (
                getattr(section, "raw_text", None)
                or getattr(section, "text", "")
                or ""
            )
            tokens.update(_tokens(section_text))
    if tokens:
        return frozenset(tokens)
    return _tokens(getattr(resume, "raw_text", "") or "")


def _measurable_rows(
    requirements: Sequence[Requirement],
) -> list[tuple[Requirement, frozenset[str]]]:
    rows = []
    for requirement in requirements:
        if requirement.kind not in _COVERABLE_KINDS:
            continue
        tokens = _tokens(requirement.normalized or requirement.text)
        if not tokens:
            # A row with no words a resume could ever contain is not a
            # zero - it is not a measurement at all.
            continue
        rows.append((requirement, tokens))
    return rows


def recommend_resume(
    job: Job,
    requirements: Sequence[Requirement],
    resumes: Sequence[object],
) -> ResumeRelevance:
    """Pick the resume that covers the posting, or say why none does.

    Args:
        job: The posting (named in no verdict; the rows carry its asks).
        requirements: The analysed rows, document order.
        resumes: Stored resumes - anything exposing ``id``, ``skills``,
            ``sections`` and ``raw_text``, so tests may stand in a double.

    Returns:
        A decision with its reason, confidence, and per-resume scores
        ordered best first. Deterministic: input order decides ties'
        presentation, never their outcome.
    """
    if not resumes:
        return ResumeRelevance(
            decision=ResumeRelevanceDecision.INSUFFICIENT_EVIDENCE,
            reason=(
                f"no resumes are stored for this posting's candidate "
                f"({job.title or 'untitled job'})"
            ),
        )

    rows = _measurable_rows(requirements)
    if not rows:
        return ResumeRelevance(
            decision=ResumeRelevanceDecision.INSUFFICIENT_EVIDENCE,
            reason=(
                "the posting states no skill any stored resume could be "
                "measured against"
            ),
        )

    scores: list[ResumeCandidateScore] = []
    for resume in resumes:
        resume_words = _resume_tokens(resume)
        covered = [
            requirement.text
            for requirement, tokens in rows
            if tokens & resume_words
        ]
        missed = [
            requirement.text
            for requirement, tokens in rows
            if not tokens & resume_words
        ]
        scores.append(
            ResumeCandidateScore(
                resume_id=str(getattr(resume, "id", "")),
                coverage=round(len(covered) / len(rows), 4),
                covered=covered,
                missed=missed,
            )
        )

    # Stable order: coverage first, repository order as the tie-break, so
    # two equal resumes keep the order the caller listed them in.
    ranked = sorted(
        enumerate(scores),
        key=lambda pair: (-pair[1].coverage, pair[0]),
    )
    ordered = [score for _, score in ranked]
    best = ordered[0]
    runner_up = ordered[1] if len(ordered) > 1 else None

    if best.coverage == 0.0:
        return ResumeRelevance(
            decision=ResumeRelevanceDecision.INSUFFICIENT_EVIDENCE,
            reason=(
                f"none of the {len(scores)} stored resume(s) mentions any of "
                f"the {len(rows)} skill(s) this posting states"
            ),
            confidence=0.0,
            scores=ordered,
        )

    if runner_up is not None and runner_up.coverage == best.coverage:
        tied = [score for score in ordered if score.coverage == best.coverage]
        return ResumeRelevance(
            decision=ResumeRelevanceDecision.REVIEW_REQUIRED,
            runner_up_resume_id=runner_up.resume_id,
            reason=(
                f"{len(tied)} resumes tie at {best.coverage:.0%} coverage of "
                f"the posting's {len(rows)} stated skill(s); a human should "
                "choose"
            ),
            confidence=best.coverage,
            scores=ordered,
        )

    return ResumeRelevance(
        decision=ResumeRelevanceDecision.RECOMMENDED,
        recommended_resume_id=best.resume_id,
        runner_up_resume_id=runner_up.resume_id if runner_up else None,
        reason=(
            f"resume {best.resume_id} covers {len(best.covered)} of "
            f"{len(rows)} stated skill(s)"
            + (
                f", ahead of {runner_up.resume_id} at "
                f"{runner_up.coverage:.0%}"
                if runner_up
                else ""
            )
        ),
        confidence=best.coverage,
        scores=ordered,
    )
