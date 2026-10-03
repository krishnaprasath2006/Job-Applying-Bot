"""Guard helpers layered on top of :mod:`safety.policies`.

These express the two rules that are easy to get wrong and expensive when you
do: AI output must not become a verified fact, and an unknown fact must never
reach a form.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

from core.actors import is_trusted_actor
from core.enums import FactStatus
from core.errors import ImmutableFactError, MissingEvidenceError, SafetyViolationError
from core.evidence import Fact

__all__ = [
    "assert_no_fact_mutation",
    "assert_application_safe",
    "assert_all_application_safe",
    "assert_verified_only",
    "diff_verified_facts",
]


def assert_no_fact_mutation(
    before: Sequence[Fact],
    after: Sequence[Fact],
    *,
    actor: str,
) -> None:
    """Refuse a change to verified facts unless a trusted actor made it.

    This is the global domain rule in code form. AI may extract, classify,
    suggest, draft, and analyse; it may not promote anything to ``VERIFIED``.

    Args:
        before: Facts as they were before the operation.
        after: Facts after the operation.
        actor: Who is attempting the change, e.g. ``"ollama"`` or ``"user"``.

    Raises:
        ImmutableFactError: If any fact changed truth status or value in a way
            a non-human actor is not permitted to cause.
    """
    if is_trusted_actor(actor):
        return

    after_by_path = {f.field_path: f for f in after}
    for original in before:
        current = after_by_path.get(original.field_path)
        if current is None:
            # A fact that was application-safe and is now gone is a change, not
            # an absence. Letting this pass would let an AI actor quietly delete
            # a verified value, which is a silent loss of the candidate's data.
            if original.is_application_safe:
                raise ImmutableFactError(
                    "non-trusted actor attempted to remove a verified fact",
                    field_path=original.field_path,
                    actor=actor,
                    previous_value=original.value,
                )
            continue
        if original.is_application_safe != current.is_application_safe:
            raise ImmutableFactError(
                "non-trusted actor attempted to change a verified fact's truth status",
                field_path=original.field_path,
                actor=actor,
                before_status=original.status.value,
                after_status=current.status.value,
            )
        if original.value != current.value:
            raise ImmutableFactError(
                "non-trusted actor attempted to change a verified fact's value",
                field_path=original.field_path,
                actor=actor,
            )


def assert_application_safe(fact: Fact) -> None:
    """Raise unless ``fact`` may be typed into a real form.

    Raises:
        MissingEvidenceError: If the fact is ``UNKNOWN``, ``INFERRED``, or
            carries no evidence.
    """
    fact.assert_application_safe()


def assert_all_application_safe(facts: Iterable[Fact]) -> None:
    """Assert every fact is usable, reporting the first that is not."""
    for fact in facts:
        fact.assert_application_safe()


def assert_verified_only(facts: Iterable[Fact], field_path: str) -> None:
    """Raise unless every fact is verified and has evidence.

    Raises:
        MissingEvidenceError: If any fact could not be typed into a real form.
    """
    unsafe = [f.field_path for f in facts if not f.is_application_safe]
    if unsafe:
        raise MissingEvidenceError(
            "one or more facts are not verified",
            field_path=field_path,
            unverified_count=len(unsafe),
            examples=unsafe[:5],
        )


def diff_verified_facts(
    before: Iterable[Fact], after: Iterable[Fact]
) -> dict[str, dict[str, object]]:
    """Describe what changed between two fact sets.

    Purely informational, used by the review UI and by tests. Returns a mapping
    of ``field_path`` to ``{"before": ..., "after": ..., "kind": ...}``.
    """
    before_map = {f.field_path: f for f in before}
    after_map = {f.field_path: f for f in after}
    changes: dict[str, dict[str, object]] = {}

    for path, new in after_map.items():
        old = before_map.get(path)
        if old is None:
            changes[path] = {"before": None, "after": new.value, "kind": "added"}
        elif old.value != new.value:
            changes[path] = {
                "before": old.value,
                "after": new.value,
                "kind": "value_changed",
            }
        elif old.status is not new.status:
            changes[path] = {
                "before": old.status.value,
                "after": new.status.value,
                "kind": "status_changed",
            }

    for path, old in before_map.items():
        if path not in after_map:
            changes[path] = {"before": old.value, "after": None, "kind": "removed"}
    return changes
