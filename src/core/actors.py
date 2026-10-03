"""Who is writing: human, deterministic code, or AI.

One classification, used by both the persistence layer (to record who changed
a fact) and the safety guard (to decide who may change a verified fact). Having
a single definition matters: if the two disagree, a write can be logged as the
user's while the guard treats it as AI, or the guard can be bypassed because an
actor name happened to be listed in one place and not the other.

Classification is prefix-based so concrete actor names work without being
registered. The default is ``AI``: an unrecognised writer must never be able to
present itself as the human.
"""

from __future__ import annotations

__all__ = [
    "AI",
    "ActorKind",
    "DETERMINISTIC",
    "HUMAN",
    "HUMAN_ACTOR_PREFIXES",
    "DETERMINISTIC_ACTOR_PREFIXES",
    "classify_actor",
    "is_trusted_actor",
]

#: An AI model wrote this.
AI = "AI"
#: Deterministic code wrote this: a parser, a regex, a rule.
DETERMINISTIC = "DETERMINISTIC"
#: A person wrote this, or explicitly confirmed it.
HUMAN = "HUMAN"

ActorKind = str

#: Names indicating a person acted.
HUMAN_ACTOR_PREFIXES: tuple[str, ...] = ("user", "human", "candidate", "cli", "owner")
#: Names indicating deterministic code acted.
DETERMINISTIC_ACTOR_PREFIXES: tuple[str, ...] = ("deterministic", "parser", "rule", "regex")
#: Exact names that are deterministic despite not matching a prefix above.
_DETERMINISTIC_EXACT: frozenset[str] = frozenset({"system"})
#: Exact names that are the human despite not matching a prefix above.
_HUMAN_EXACT: frozenset[str] = frozenset()


def classify_actor(actor: str) -> ActorKind:
    """Map an actor name to ``HUMAN``, ``DETERMINISTIC``, or ``AI``.

    Args:
        actor: Who performed the write, e.g. ``"user"``,
            ``"deterministic_resume_parser"``, ``"ollama"``.

    Returns:
        One of :data:`HUMAN`, :data:`DETERMINISTIC`, :data:`AI`.

    Raises:
        ValueError: If ``actor`` is empty. An unnamed writer cannot be
            classified, and neither default is acceptable: ``AI`` would make
            legitimate writes fail the guard, ``HUMAN`` would defeat it.
    """
    normalised = (actor or "").strip().lower()
    if not normalised:
        raise ValueError("actor must be named; an unnamed writer cannot be audited")
    if normalised in _HUMAN_EXACT:
        return HUMAN
    if normalised in _DETERMINISTIC_EXACT:
        return HUMAN
    if normalised.startswith(HUMAN_ACTOR_PREFIXES):
        return HUMAN
    if normalised.startswith(DETERMINISTIC_ACTOR_PREFIXES):
        return DETERMINISTIC
    return AI


def is_trusted_actor(actor: str) -> bool:
    """Whether this actor may change a ``VERIFIED`` fact.

    Both a person and deterministic code may, because a deterministic parser
    extracting a value the candidate has already confirmed is not a guess. AI
    may not, at any status.
    """
    return classify_actor(actor) in (HUMAN, DETERMINISTIC)
