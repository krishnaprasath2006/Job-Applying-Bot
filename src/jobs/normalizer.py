"""Job text normalisation.

Purely mechanical text handling so that later phases compare like with like. No
interpretation happens here: this function does not decide that "3+ years of
Python" means anything in particular.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

__all__ = ["normalize_text", "normalize_title", "normalize_company", "slugify", "normalize_skills"]

_WHITESPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\s&/+#.-]")
#: Anything that cannot appear in an identifier fragment. Stricter than
#: ``_PUNCT_RE`` on purpose: ``&``, ``/``, ``+``, and ``#`` carry meaning in a
#: human-readable title but would corrupt a slug.
_SLUG_UNSAFE_RE = re.compile(r"[^\w\s-]")
_DASH_RUN_RE = re.compile(r"-{2,}")
_TITLE_NOISE_RE = re.compile(
    # Word-shaped noise, bounded by word boundaries.
    r"\b(?:remote|hybrid|onsite|on-site|full[- ]?time|part[- ]?time|contract|permanent|"
    r"intern|internship|graduate|fresher|senior|junior|mid[- ]?level|lead|principal)\b"
    # Level ranges. These end in a bracket, so a trailing \b could never match
    # and the whole alternative was silently dead.
    r"|\(\s*(?:l\s*)?\d+\s*[-–]\s*(?:l\s*)?\d+\s*\)"
    r"|\[\s*(?:l\s*)?\d+\s*[-–]\s*(?:l\s*)?\d+\s*\]",
    re.IGNORECASE,
)
_COMPANY_SUFFIX_RE = re.compile(
    r"\b(?:inc|inc\.|llc|ltd|ltd\.|limited|pvt|private|gmbh|bv|nv|plc|co|corp|"
    r"corporation|company|technologies|technology|labs|solutions|services|systems|group)\b\.?",
    re.IGNORECASE,
)

_SKILL_ALIASES: dict[str, str] = {
    "postgres": "postgresql",
    "py": "python",
    "py3": "python",
    "python3": "python",
    "js": "javascript",
    "ts": "typescript",
    "golang": "go",
    "node": "node.js",
    "nodejs": "node.js",
    "k8s": "kubernetes",
    "gcp": "google cloud",
    "aws": "aws",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "rest": "rest api",
    "restful": "rest api",
    "ci cd": "ci/cd",
    "cicd": "ci/cd",
    "power bi": "powerbi",
    "sk learn": "scikit-learn",
    "tensorflow2": "tensorflow",
    "pytorch": "pytorch",
}


def normalize_text(text: str | None) -> str:
    """Collapse whitespace and normalise unicode.

    NFKC folding means ``ﬁ`` and ``fi`` compare equal, which matters because
    PDF extraction produces both.
    """
    if not text:
        return ""
    folded = unicodedata.normalize("NFKC", text)
    folded = folded.replace("\u00a0", " ").replace("\u2019", "'").replace("\u2018", "'")
    folded = folded.replace("\u201c", '"').replace("\u201d", '"')
    folded = folded.replace("\u2013", "-").replace("\u2014", "-")
    return _WHITESPACE_RE.sub(" ", folded).strip()


def normalize_title(title: str | None) -> str:
    """Reduce a job title to its core noun phrase.

    Strips seniority, location, and employment-type noise so that
    ``"Senior Machine Learning Engineer (Remote)"`` and
    ``"Machine Learning Engineer"`` normalise to the same thing.

    Raises:
        ValueError: If nothing meaningful remains after stripping.
    """
    cleaned = normalize_text(title).lower()
    cleaned = _TITLE_NOISE_RE.sub(" ", cleaned)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip(" -–—|/,")
    if not cleaned:
        raise ValueError(f"job title {title!r} has no meaningful content after normalisation")
    return cleaned


def normalize_company(company: str | None) -> str:
    """Strip legal suffixes so ``"Acme Inc."`` and ``"Acme"`` match."""
    cleaned = normalize_text(company).lower()
    cleaned = _COMPANY_SUFFIX_RE.sub(" ", cleaned)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    return _WHITESPACE_RE.sub(" ", cleaned).strip()


def slugify(text: str) -> str:
    """Lower-case, dash-separated identifier fragment.

    Unlike title and company normalisation, this keeps nothing but word
    characters and dashes. A slug is used as part of an id, and a slash or an
    ampersand surviving into one would produce an identifier that cannot be
    matched back by name.
    """
    cleaned = normalize_text(text).lower()
    cleaned = _SLUG_UNSAFE_RE.sub("-", cleaned)
    cleaned = _WHITESPACE_RE.sub("-", cleaned)
    return _DASH_RUN_RE.sub("-", cleaned).strip("-")


def normalize_skill(value: str | None) -> str:
    """Map a skill name to its canonical form.

    Aliases are a fixed, reviewable table. An unmapped name is returned
    lower-cased and otherwise untouched rather than being forced onto the
    nearest known skill, which would invent a match.
    """
    cleaned = normalize_text(value).lower().strip(" .,;")
    if not cleaned:
        return ""
    return _SKILL_ALIASES.get(cleaned, cleaned)


def normalize_skill_list(values: list[str]) -> list[str]:
    """Normalise and de-duplicate a list of skill names."""
    seen: dict[str, None] = {}
    for value in values or []:
        canonical = normalize_skill(value)
        if canonical:
            seen.setdefault(canonical, None)
    return sorted(seen)


def as_text(value: Any) -> str:
    """Best-effort conversion of a possibly-``None`` field to text."""
    return normalize_text(str(value)) if value is not None else ""
