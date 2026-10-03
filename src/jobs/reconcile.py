"""Cross-checking two readings of the same posting.

An AI interpretation and the deterministic extractor both read the same
job description, and they do not always agree: one records years the
other missed, one calls a line REQUIRED the other read as PREFERRED, one
finds a requirement the other never produced. The stored requirement
rows hold the model's reading (it is the one matching runs on), so
without a cross-check the rule's reading would vanish from the database
while quietly shaping the match - and
:data:`~core.enums.ReviewReason.EXTRACTION_CONFLICT` would have no
source.

This module is that cross-check. It pairs the two requirement sets row
by row, names each disagreement, counts them, and - per the milestone
rule that neither reading overwrites the other - keeps *both* complete
row sets in the report: the model's rows live in ``job_requirements``,
the rule's rows ride in the report block beside them, and the conflict
status binds them together. :func:`apply_conflicts` folds the count into
a verdict that would otherwise have decided alone.

Pairing is deliberately simple enough to explain to a human reading the
conflict later: exact normalized text first, then greedy token overlap
among what is left. A conflict is only reported where the disagreement
changes a decision - differing years, a priority flip involving
REQUIRED, or a REQUIRED row one side never produced. One extractor
reading more detail than the other is enrichment; two extractions
contradicting each other is a conflict.

The report and the rows it describes move together: a report is written
only when those rows are stored, and cleared when they are replaced.
That is what lets the match cache stay coherent without the report
becoming part of the fingerprint.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field

from core.enums import MatchDecision
from jobs.matching import MatchResult
from jobs.models import Requirement

__all__ = [
    "ConflictIssue",
    "MAX_ISSUES_IN_METADATA",
    "RECONCILIATION_KEY",
    "ReconciliationReport",
    "RequirementConflict",
    "apply_conflicts",
    "conflict_count",
    "reconcile",
]

#: Where the report rides on the job, in the same metadata block that
#: carries provenance.
RECONCILIATION_KEY = "reconciliation"

#: How many individual issues the stored metadata carries; the count in
#: ``conflicts`` is always the full one, capped storage or not.
MAX_ISSUES_IN_METADATA = 50

#: Below this Jaccard overlap, two rows of one kind are not the same
#: requirement read twice.
_MIN_PAIR_OVERLAP = 0.5

_TOKEN_RE = re.compile(r"[a-z0-9+#]+")


class ConflictIssue(str, Enum):
    """What two extractions disagreed about."""

    YEARS_DISAGREE = "YEARS_DISAGREE"
    PRIORITY_DISAGREE = "PRIORITY_DISAGREE"
    PRESENCE_DISAGREE = "PRESENCE_DISAGREE"


class RequirementConflict(BaseModel):
    """One disagreement between the two extractions of a posting.

    Both sides are kept even when only one exists (a presence conflict
    has no opposite row), so a reader can see what each extractor said
    without reopening the analysis.
    """

    model_config = ConfigDict(extra="forbid")

    issue: ConflictIssue
    kind: str
    deterministic_text: str = ""
    ai_text: str = ""
    deterministic_years: Optional[float] = None
    ai_years: Optional[float] = None
    deterministic_priority: str = ""
    ai_priority: str = ""

    def summary(self) -> str:
        """One line naming the issue and both sides, for reports."""
        if self.issue is ConflictIssue.PRESENCE_DISAGREE:
            found = self.deterministic_text or self.ai_text
            by = "deterministic" if self.deterministic_text else "ai"
            return f"{self.issue.value}: {found!r} only in {by}"
        return (
            f"{self.issue.value}: deterministic={self.deterministic_text!r} "
            f"ai={self.ai_text!r}"
        )


class ReconciliationReport(BaseModel):
    """The verdict of one cross-check: both readings and how they clashed.

    The full row sets are kept, not just their counts: the milestone
    rule is that neither extraction overwrites the other, so the report
    preserves the deterministic reading in full (the model's rows are
    already stored as the job's requirements) alongside the conflict
    status that binds them.
    """

    model_config = ConfigDict(extra="forbid")

    deterministic_count: int = Field(default=0, ge=0)
    ai_count: int = Field(default=0, ge=0)
    conflicts: list[RequirementConflict] = Field(default_factory=list)
    deterministic_rows: list[Requirement] = Field(default_factory=list)
    ai_rows: list[Requirement] = Field(default_factory=list)

    @property
    def conflict_count(self) -> int:
        return len(self.conflicts)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    def to_metadata(self) -> dict[str, Any]:
        """The JSON-safe block stored under ``reconciliation``."""
        return {
            "conflicts": self.conflict_count,
            "deterministic": self.deterministic_count,
            "ai": self.ai_count,
            "issues": [
                conflict.model_dump(mode="json")
                for conflict in self.conflicts[:MAX_ISSUES_IN_METADATA]
            ],
            "deterministic_rows": [
                row.model_dump(mode="json") for row in self.deterministic_rows
            ],
            "ai_rows": [
                row.model_dump(mode="json") for row in self.ai_rows
            ],
        }

    def summary(self) -> str:
        """One line for a report or a log."""
        if not self.has_conflicts:
            return f"agreed on {self.deterministic_count} requirement(s)"
        return (
            f"{self.conflict_count} conflict(s) across "
            f"{self.deterministic_count} deterministic and "
            f"{self.ai_count} ai requirement(s)"
        )


def reconcile(
    deterministic: Sequence[Requirement],
    ai: Sequence[Requirement],
) -> ReconciliationReport:
    """Pair two extractions and name the disagreements.

    Args:
        deterministic: Rows the rule-based extractor produced.
        ai: Rows the model produced for the same description.

    Returns:
        Both complete row sets - preserved so neither reading overwrites
        the other - their counts, and every conflict, ordered by kind in
        the deterministic document order first, then kinds only the model
        found. A pair reports at most one issue - years outrank priority
        - so one disagreement is never counted twice.
    """
    det_by_kind = _by_kind(deterministic)
    ai_by_kind = _by_kind(ai)
    conflicts: list[RequirementConflict] = []

    for kind in dict.fromkeys([*det_by_kind, *ai_by_kind]):
        det_rows = det_by_kind.get(kind, [])
        ai_rows = ai_by_kind.get(kind, [])
        pairs, det_left, ai_left = _pair(det_rows, ai_rows)

        for det, mine in pairs:
            if det.min_years != mine.min_years:
                conflicts.append(
                    _conflict(ConflictIssue.YEARS_DISAGREE, kind, det, mine)
                )
            elif det.priority.is_mandatory != mine.priority.is_mandatory:
                conflicts.append(
                    _conflict(ConflictIssue.PRIORITY_DISAGREE, kind, det, mine)
                )

        # A row one side never produced is a conflict only when it was
        # REQUIRED: a missed preferred line is a gap in detail, not a
        # contradiction of what the posting demands.
        for det in det_left:
            if det.priority.is_mandatory:
                conflicts.append(
                    _conflict(ConflictIssue.PRESENCE_DISAGREE, kind, det, None)
                )
        for mine in ai_left:
            if mine.priority.is_mandatory:
                conflicts.append(
                    _conflict(ConflictIssue.PRESENCE_DISAGREE, kind, None, mine)
                )

    return ReconciliationReport(
        deterministic_count=len(deterministic),
        ai_count=len(ai),
        conflicts=conflicts,
        deterministic_rows=list(deterministic),
        ai_rows=list(ai),
    )


def apply_conflicts(result: MatchResult, conflicts: int) -> MatchResult:
    """Promote a verdict that would have decided alone when the readings clashed.

    A ``MATCH`` or ``PARTIAL_MATCH`` stands on requirements two
    extractors contradicted; the verdict becomes ``REVIEW_REQUIRED`` so a
    person sees what the model and the rules could not settle between
    them. Verdicts that already require a human keep theirs, and a
    ``HARD_MISMATCH`` is not softened: the gate's veto outranks an
    extraction doubt.

    Args:
        result: The verdict as the matcher composed it.
        conflicts: The cross-checker's count.

    Returns:
        The promoted result, or the original one untouched.
    """
    if conflicts <= 0:
        return result
    if result.decision in (MatchDecision.MATCH, MatchDecision.PARTIAL_MATCH):
        return result.model_copy(update={"decision": MatchDecision.REVIEW_REQUIRED})
    return result


def conflict_count(metadata: Optional[Mapping[str, Any]]) -> int:
    """The count in a job's stored reconciliation block.

    Returns ``0`` when the block is absent or unreadable - the safe
    answer for a caller about to ask "should a human look at this?" is
    never to invent doubt from malformed data, only to report what was
    recorded.
    """
    if not metadata:
        return 0
    block = metadata.get(RECONCILIATION_KEY)
    if not isinstance(block, Mapping):
        return 0
    value = block.get("conflicts")
    if isinstance(value, bool) or not isinstance(value, int):
        return 0
    return max(value, 0)


def _by_kind(rows: Sequence[Requirement]) -> dict[str, list[Requirement]]:
    grouped: dict[str, list[Requirement]] = {}
    for row in rows:
        grouped.setdefault(row.kind.value, []).append(row)
    return grouped


def _conflict(
    issue: ConflictIssue,
    kind: str,
    det: Optional[Requirement],
    ai: Optional[Requirement],
) -> RequirementConflict:
    return RequirementConflict(
        issue=issue,
        kind=kind,
        deterministic_text=det.text if det is not None else "",
        ai_text=ai.text if ai is not None else "",
        deterministic_years=det.min_years if det is not None else None,
        ai_years=ai.min_years if ai is not None else None,
        deterministic_priority=det.priority.value if det is not None else "",
        ai_priority=ai.priority.value if ai is not None else "",
    )


def _pair(
    det_rows: Sequence[Requirement],
    ai_rows: Sequence[Requirement],
) -> tuple[
    list[tuple[Requirement, Requirement]],
    list[Requirement],
    list[Requirement],
]:
    """Pair rows of one kind: exact text first, then greedy overlap.

    Returns the pairs plus each side's leftovers, in document order.
    """
    det_paired: set[int] = set()
    ai_paired: set[int] = set()
    pairs: list[tuple[Requirement, Requirement]] = []

    for i, det in enumerate(det_rows):
        key = (det.normalized or det.text).strip().lower()
        for j, mine in enumerate(ai_rows):
            if j in ai_paired:
                continue
            if key == (mine.normalized or mine.text).strip().lower():
                pairs.append((det, mine))
                det_paired.add(i)
                ai_paired.add(j)
                break

    for i, det in enumerate(det_rows):
        if i in det_paired:
            continue
        det_tokens = _tokens(det)
        best_j = -1
        best_score = 0.0
        for j, mine in enumerate(ai_rows):
            if j in ai_paired:
                continue
            score = _jaccard(det_tokens, _tokens(mine))
            if score > best_score:
                best_score = score
                best_j = j
        if best_j >= 0 and best_score >= _MIN_PAIR_OVERLAP:
            pairs.append((det, ai_rows[best_j]))
            det_paired.add(i)
            ai_paired.add(best_j)

    det_left = [row for i, row in enumerate(det_rows) if i not in det_paired]
    ai_left = [row for j, row in enumerate(ai_rows) if j not in ai_paired]
    return pairs, det_left, ai_left


def _tokens(row: Requirement) -> set[str]:
    return set(_TOKEN_RE.findall((row.normalized or row.text).lower()))


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    return len(left & right) / len(union)
