"""Reading requirements out of a job description, with rules rather than a model.

A job description is prose written by a person for people, so the extractor's
first job is to refuse most of it. Responsibilities, marketing, benefits and
the section headings that introduce them are not things a candidate must have,
and turning them into requirements would make every posting look like a wall of
demands. The rules below therefore read a description the way a careful reader
would:

* section headings decide the tone of what follows — *requirements* and *nice
  to have* are asks, *responsibilities* and *about us* are not;
* a heading the rules do not recognise resets the section to neutral rather
  than inheriting the previous tone, because a misread heading is worse than
  an unknown one;
* under a neutral tone a line is only taken when it matches a requirement
  signal ("experience with", "years of") or names something the lexicon
  recognises, which is what keeps company prose out;
* the priority a line states for itself ("...a plus") beats the section it
  sits in.

Everything produced here is ``DETERMINISTIC``: the same description produces
the same rows, in the same order, with the same excerpt quoted back — so a
human reviewing a classification can find the text it was read from. The AI
path (:mod:`jobs.extraction_schema`) produces the same shape with a different
``extraction_source``, and the two are never mixed inside one run.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from html.parser import HTMLParser
from typing import Iterable, Optional, Sequence

from core.enums import ExtractionMethod, RequirementPriority
from core.logging_config import get_logger
from jobs.models import Requirement, RequirementKind
from jobs.normalizer import normalize_text

__all__ = ["classify_term", "extract_requirements", "merge_requirements"]

log = get_logger(__name__)

# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------
class _Tone(Enum):
    """How a line should be read, given where it appeared."""

    REQUIRED = "REQUIRED"
    PREFERRED = "PREFERRED"
    NEUTRAL = "NEUTRAL"
    SKIP = "SKIP"


def _clean_heading(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().strip(":").strip().lower()


_REQUIRED_HEADINGS = frozenset(
    {
        "required qualifications",
        "requirement",
        "requirements",
        "qualification",
        "qualifications",
        "minimum qualifications",
        "basic qualifications",
        "key qualifications",
        "job requirements",
        "role requirements",
        "our requirements",
        "what we look for",
        "what we're looking for",
        "what you need",
        "what you'll need",
        "what you will need",
        "you'll need",
        "you will need",
        "must have",
        "must haves",
        "must-haves",
        "skills",
        "skills and experience",
        "skills & experience",
        "experience and skills",
        "experience & skills",
        "who you are",
        "about you",
        "you are",
        "candidate profile",
        "ideal candidate",
        "education and experience",
        "minimum requirements",
        "job qualifications",
    }
)

_PREFERRED_HEADINGS = frozenset(
    {
        "nice to have",
        "nice-to-have",
        "nice to haves",
        "preferred",
        "preferred skills",
        "preferred experience",
        "preferred qualifications",
        "bonus",
        "bonus points",
        "plus",
        "extras",
        "desirable",
        "would be nice",
        "would be great",
        "beneficial",
        "not required",
        "not strictly required",
        "what would make you stand out",
        "additional skills",
        "other skills",
    }
)

_SKIP_HEADINGS = frozenset(
    {
        "about the role",
        "about the job",
        "about this role",
        "the role",
        "role overview",
        "job description",
        "overview",
        "about us",
        "about the company",
        "about our company",
        "who we are",
        "our story",
        "what we do",
        "responsibilities",
        "what you will do",
        "what you'll do",
        "day to day",
        "day-to-day",
        "in this role",
        "your responsibilities",
        "key responsibilities",
        "role responsibilities",
        "what we offer",
        "what we provide",
        "our offer",
        "benefits",
        "perks",
        "compensation",
        "salary",
        "how to apply",
        "application process",
        "equal employment opportunity",
        "equal opportunity",
        "our commitment to diversity",
        "diversity and inclusion",
        "privacy notice",
        "disclaimer",
        "company overview",
        "our values",
        "why join us",
        "life at",
    }
)


# ---------------------------------------------------------------------------
# Signals and lexicon
# ---------------------------------------------------------------------------
#: Phrases that ask something of the candidate. Used only under a neutral
#: tone, where the section itself said nothing about whether a line is an ask.
_REQUIREMENT_SIGNALS = (
    "experience with",
    "experience in",
    "experience of",
    "years of experience",
    "years experience",
    "knowledge of",
    "familiarity with",
    "proficiency in",
    "proficient in",
    "hands-on",
    "hands on",
    "background in",
    "understanding of",
    "ability to",
    "able to",
    "comfort with",
    "comfortable with",
    "strong grasp",
    "solid grounding",
    "fluent",
    "degree in",
    "degree or",
    "qualified",
    "you have",
    "you know",
    "you hold",
    "you bring",
    "must have",
    "required:",
    "minimum of",
    "at least",
)

#: Words a line may state about itself, which beat the section heading.
_PREFERRED_LINE_MARKERS = (
    "a plus",
    "is plus",
    "nice to have",
    "nice-to-have",
    "preferred",
    "bonus",
    "would be great",
    "would be nice",
    "desirable",
    "optional",
    "is welcome",
    "are welcome",
    "welcome to hear from",
    "not strictly required",
)

_REQUIRED_LINE_MARKERS = (
    "required",
    "must have",
    "must-have",
    "essential",
    "mandatory",
    "necessary",
)

#: A line that says experience is *not* required must not become a required
#: requirement, which is the one reading a naive marker match would produce.
_NOT_REQUIRED_RE = re.compile(
    r"\b(?:no|without|not)\b[^.!?]{0,40}\b(?:required|necessary|needed)\b",
    re.IGNORECASE,
)

_YEARS_RE = re.compile(
    r"\b(\d{1,2}(?:\.\d)?)\s*(?:\+|-|\s*to\s*\d{1,2}(?:\.\d)?)?\s*years?\b",
    re.IGNORECASE,
)

# Ordered: the first match wins, so more specific terms come first.
_LEXICON: tuple[tuple[str, RequirementKind], ...] = (
    # Programming languages.
    ("python", RequirementKind.PROGRAMMING_LANGUAGE),
    ("javascript", RequirementKind.PROGRAMMING_LANGUAGE),
    ("typescript", RequirementKind.PROGRAMMING_LANGUAGE),
    ("golang", RequirementKind.PROGRAMMING_LANGUAGE),
    ("c++", RequirementKind.PROGRAMMING_LANGUAGE),
    ("c#", RequirementKind.PROGRAMMING_LANGUAGE),
    ("sql", RequirementKind.PROGRAMMING_LANGUAGE),
    ("bash", RequirementKind.PROGRAMMING_LANGUAGE),
    ("perl", RequirementKind.PROGRAMMING_LANGUAGE),
    ("scala", RequirementKind.PROGRAMMING_LANGUAGE),
    ("kotlin", RequirementKind.PROGRAMMING_LANGUAGE),
    ("swift", RequirementKind.PROGRAMMING_LANGUAGE),
    ("ruby", RequirementKind.PROGRAMMING_LANGUAGE),
    ("php", RequirementKind.PROGRAMMING_LANGUAGE),
    ("rust", RequirementKind.PROGRAMMING_LANGUAGE),
    ("html", RequirementKind.PROGRAMMING_LANGUAGE),
    ("css", RequirementKind.PROGRAMMING_LANGUAGE),
    # Frameworks and libraries.
    ("pytorch", RequirementKind.FRAMEWORK),
    ("tensorflow", RequirementKind.FRAMEWORK),
    ("scikit-learn", RequirementKind.FRAMEWORK),
    ("fastapi", RequirementKind.FRAMEWORK),
    ("flask", RequirementKind.FRAMEWORK),
    ("django", RequirementKind.FRAMEWORK),
    ("react", RequirementKind.FRAMEWORK),
    ("angular", RequirementKind.FRAMEWORK),
    ("node.js", RequirementKind.FRAMEWORK),
    ("next.js", RequirementKind.FRAMEWORK),
    ("spring boot", RequirementKind.FRAMEWORK),
    ("rails", RequirementKind.FRAMEWORK),
    ("laravel", RequirementKind.FRAMEWORK),
    ("pandas", RequirementKind.FRAMEWORK),
    ("numpy", RequirementKind.FRAMEWORK),
    ("langchain", RequirementKind.FRAMEWORK),
    ("hugging face", RequirementKind.FRAMEWORK),
    ("llama.cpp", RequirementKind.FRAMEWORK),
    ("keras", RequirementKind.FRAMEWORK),
    # Databases.
    ("sqlite", RequirementKind.DATABASE),
    ("postgres", RequirementKind.DATABASE),
    ("postgresql", RequirementKind.DATABASE),
    ("mysql", RequirementKind.DATABASE),
    ("mongodb", RequirementKind.DATABASE),
    ("dynamodb", RequirementKind.DATABASE),
    ("cassandra", RequirementKind.DATABASE),
    ("snowflake", RequirementKind.DATABASE),
    ("bigquery", RequirementKind.DATABASE),
    ("elasticsearch", RequirementKind.DATABASE),
    ("redis", RequirementKind.DATABASE),
    ("duckdb", RequirementKind.DATABASE),
    # Cloud and platform.
    ("aws", RequirementKind.CLOUD),
    ("azure", RequirementKind.CLOUD),
    ("google cloud", RequirementKind.CLOUD),
    ("gcp", RequirementKind.CLOUD),
    # Infrastructure and tooling.
    ("kubernetes", RequirementKind.TECHNOLOGY),
    ("terraform", RequirementKind.TECHNOLOGY),
    ("docker", RequirementKind.TECHNOLOGY),
    ("microservices", RequirementKind.TECHNOLOGY),
    ("graphql", RequirementKind.TECHNOLOGY),
    ("prometheus", RequirementKind.TECHNOLOGY),
    ("grafana", RequirementKind.TECHNOLOGY),
    ("ansible", RequirementKind.TECHNOLOGY),
    ("jenkins", RequirementKind.TECHNOLOGY),
    ("airflow", RequirementKind.TECHNOLOGY),
    ("kubeflow", RequirementKind.TECHNOLOGY),
    ("kafka", RequirementKind.TECHNOLOGY),
    ("hadoop", RequirementKind.TECHNOLOGY),
    ("spark", RequirementKind.TECHNOLOGY),
    ("linux", RequirementKind.TECHNOLOGY),
    ("unix", RequirementKind.TECHNOLOGY),
    ("git", RequirementKind.TECHNOLOGY),
    ("ollama", RequirementKind.TECHNOLOGY),
    ("pytest", RequirementKind.TECHNOLOGY),
    ("pydantic", RequirementKind.TECHNOLOGY),
    ("pdfplumber", RequirementKind.TECHNOLOGY),
    ("python-docx", RequirementKind.TECHNOLOGY),
    ("unstructured", RequirementKind.TECHNOLOGY),
    ("jupyter", RequirementKind.TECHNOLOGY),
    ("excel", RequirementKind.TECHNOLOGY),
    ("powerpoint", RequirementKind.TECHNOLOGY),
    # Education and certification.
    ("phd", RequirementKind.EDUCATION),
    ("mba", RequirementKind.EDUCATION),
    ("bachelor", RequirementKind.EDUCATION),
    ("master", RequirementKind.EDUCATION),
    ("degree", RequirementKind.EDUCATION),
    ("diploma", RequirementKind.EDUCATION),
    ("certified", RequirementKind.CERTIFICATION),
    ("certification", RequirementKind.CERTIFICATION),
    # Human languages.
    ("english", RequirementKind.LANGUAGE),
    ("spanish", RequirementKind.LANGUAGE),
    ("french", RequirementKind.LANGUAGE),
    ("german", RequirementKind.LANGUAGE),
    ("dutch", RequirementKind.LANGUAGE),
    ("mandarin", RequirementKind.LANGUAGE),
    ("japanese", RequirementKind.LANGUAGE),
    ("hindi", RequirementKind.LANGUAGE),
    # Ways of working.
    ("communication", RequirementKind.SOFT_SKILL),
    ("collaboration", RequirementKind.SOFT_SKILL),
    ("stakeholder", RequirementKind.SOFT_SKILL),
    ("mentoring", RequirementKind.SOFT_SKILL),
    ("mentor", RequirementKind.SOFT_SKILL),
    ("leadership", RequirementKind.SOFT_SKILL),
    ("problem-solving", RequirementKind.SOFT_SKILL),
    ("problem solving", RequirementKind.SOFT_SKILL),
    ("critical thinking", RequirementKind.SOFT_SKILL),
    ("attention to detail", RequirementKind.SOFT_SKILL),
    ("time management", RequirementKind.SOFT_SKILL),
    ("adaptability", RequirementKind.SOFT_SKILL),
    ("teamwork", RequirementKind.SOFT_SKILL),
    # Domain knowledge.
    ("machine learning", RequirementKind.DOMAIN),
    ("deep learning", RequirementKind.DOMAIN),
    ("retrieval-augmented generation", RequirementKind.DOMAIN),
    ("natural language processing", RequirementKind.DOMAIN),
    ("computer vision", RequirementKind.DOMAIN),
    ("recommender systems", RequirementKind.DOMAIN),
    ("data engineering", RequirementKind.DOMAIN),
    ("data modelling", RequirementKind.DOMAIN),
    ("data modeling", RequirementKind.DOMAIN),
    ("vector search", RequirementKind.DOMAIN),
    ("e-commerce", RequirementKind.DOMAIN),
    ("healthcare", RequirementKind.DOMAIN),
    ("fintech", RequirementKind.DOMAIN),
    # Working arrangements and authorisation.
    ("visa", RequirementKind.SPONSORSHIP),
    ("sponsorship", RequirementKind.SPONSORSHIP),
    ("work authorization", RequirementKind.SPONSORSHIP),
    ("authorized to work", RequirementKind.SPONSORSHIP),
    ("relocation", RequirementKind.LOCATION),
    ("remote", RequirementKind.WORKPLACE_TYPE),
    ("hybrid", RequirementKind.WORKPLACE_TYPE),
    ("on-site", RequirementKind.WORKPLACE_TYPE),
    ("onsite", RequirementKind.WORKPLACE_TYPE),
    ("full-time", RequirementKind.EMPLOYMENT_TYPE),
    ("part-time", RequirementKind.EMPLOYMENT_TYPE),
    ("internship", RequirementKind.EMPLOYMENT_TYPE),
)

_KIND_RANK: dict[RequirementKind, int] = {
    kind: index
    for index, kind in enumerate(
        [
            RequirementKind.PROGRAMMING_LANGUAGE,
            RequirementKind.FRAMEWORK,
            RequirementKind.DATABASE,
            # A line that says "certified" or "degree" is about the
            # credential, even when it names the vendor or the technology.
            RequirementKind.CERTIFICATION,
            RequirementKind.EDUCATION,
            RequirementKind.CLOUD,
            RequirementKind.TECHNOLOGY,
            RequirementKind.LANGUAGE,
            RequirementKind.SPONSORSHIP,
            RequirementKind.WORKPLACE_TYPE,
            RequirementKind.EMPLOYMENT_TYPE,
            RequirementKind.LOCATION,
            RequirementKind.DOMAIN,
            RequirementKind.SOFT_SKILL,
            RequirementKind.YEARS_OF_EXPERIENCE,
            RequirementKind.EXPERIENCE,
            RequirementKind.OTHER,
        ]
    )
}

_TERM_RE = {
    term: re.compile(rf"(?<!\w){re.escape(term)}(?!\w)", re.IGNORECASE)
    for term, _ in _LEXICON
}

#: Confidence attached to a priority the text states (a heading, or a marker
#: such as "a plus") against one that had to be inferred.
_CONFIDENCE_STATED = 0.9
_CONFIDENCE_INFERRED = 0.6


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------
class _BlockKind(Enum):
    HEADING = "heading"
    BULLET = "bullet"
    PARAGRAPH = "paragraph"


@dataclass(frozen=True)
class _Block:
    text: str
    kind: _BlockKind


_BULLET_RE = re.compile(r"^\s*(?:[-*•‣–]|\d{1,2}[.)])\s+")
_SEPARATOR_RE = re.compile(r"^[-=_~*·]{3,}\s*$")
_METADATA_RE = re.compile(r"^[A-Za-z][A-Za-z /&-]{0,40}:\s+\S")


class _MarkupBlocks(HTMLParser):
    """Blocks of text, in document order, out of HTML.

    Only tags that carry structure are followed: a description that happens to
    contain markup for emphasis must not be chopped up by it. Nested inline
    tags (``<li><p>``) stay inside the block that opened first, so a list item
    remains one ask rather than becoming a headingless paragraph.
    """

    _HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
    _WRAP_TAGS = {"p", "div", "section", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[_Block] = []
        self._kind: Optional[_BlockKind] = None
        self._parts: list[str] = []

    def _open(self, kind: _BlockKind) -> None:
        """Open a block, or join the one already open.

        A block is joined only by a tag nested inside a non-heading element,
        which is how ``<li><p>text</p></li>`` stays one item. Everything else
        starts a fresh block, including a second item of the same kind —
        ``<li>one<li>two`` is an unclosed list item to this parser, and
        treating it as one would fuse two claims into a single row.
        """
        if (
            self._kind is None
            or kind is self._kind
            or kind is _BlockKind.HEADING
            or self._kind is _BlockKind.HEADING
        ):
            self._flush()
            self._kind, self._parts = kind, []

    def _close(self, kind: _BlockKind) -> None:
        if self._kind is kind:
            self._flush()

    def _flush(self) -> None:
        if self._kind is None:
            return
        text = re.sub(r"\s+", " ", "".join(self._parts)).strip()
        if text:
            self.blocks.append(_Block(text, self._kind))
        self._kind, self._parts = None, []

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        if tag in self._HEADING_TAGS:
            self._open(_BlockKind.HEADING)
        elif tag == "li":
            self._open(_BlockKind.BULLET)
        elif tag in self._WRAP_TAGS:
            self._open(_BlockKind.PARAGRAPH)
        elif tag in {"br", "hr"}:
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in self._HEADING_TAGS:
            self._close(_BlockKind.HEADING)
        elif tag == "li":
            self._close(_BlockKind.BULLET)
        elif tag in self._WRAP_TAGS:
            self._close(_BlockKind.PARAGRAPH)

    def handle_data(self, data: str) -> None:
        if self._kind is not None:
            self._parts.append(data)

    def close(self) -> None:
        super().close()
        self._flush()


def _markup_blocks(markup: str) -> list[_Block]:
    parser = _MarkupBlocks()
    parser.feed(markup)
    parser.close()
    return parser.blocks


def _text_blocks(text: str) -> list[_Block]:
    """Blocks out of plain text: paragraphs, headings, and bullets.

    Job descriptions are usually hard-wrapped, so lines are rejoined into
    paragraphs first. Three kinds of line break that joining instead:

    * a separator (``----``) closes the block above it and is dropped;
    * a heading-shaped line becomes a block of its own, which is what makes
      underlined headings readable;
    * a bullet marker starts a new block, and the lines after it continue
      that bullet.
    """
    blocks: list[_Block] = []
    for chunk in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in chunk.splitlines() if line.strip()]
        if not lines:
            continue
        if len(lines) == 1:
            blocks.extend(_single_line(lines[0]))
            continue
        carried = -1
        for line in lines:
            if _SEPARATOR_RE.match(line):
                carried = -1
                continue
            bullet = _BULLET_RE.match(line)
            if bullet:
                blocks.append(_Block(line[bullet.end():].strip(), _BlockKind.BULLET))
                carried = len(blocks) - 1
                continue
            if _looks_like_heading(line):
                blocks.append(_Block(line, _BlockKind.HEADING))
                carried = -1
                continue
            if carried >= 0:
                block = blocks[carried]
                blocks[carried] = _Block(f"{block.text} {line}".strip(), block.kind)
            else:
                blocks.append(_Block(line, _BlockKind.PARAGRAPH))
                carried = len(blocks) - 1
    return blocks


def _single_line(line: str) -> list[_Block]:
    bullet = _BULLET_RE.match(line)
    if bullet:
        return [_Block(line[bullet.end():].strip(), _BlockKind.BULLET)]
    # A description folded onto one line still has sentences in it.
    sentences = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", line.strip())
        if part.strip()
    ]
    return [_Block(sentence, _BlockKind.PARAGRAPH) for sentence in sentences] or [
        _Block(line.strip(), _BlockKind.PARAGRAPH)
    ]


def _blocks(description: str, raw: Optional[str]) -> list[_Block]:
    """Blocks of candidate text, structure taken from markup when there is any."""
    markup = raw if raw and "<" in raw else description
    found = _markup_blocks(markup) if _looks_like_markup(markup) else _text_blocks(markup)
    return [block for block in found if block.text.strip()]


def _looks_like_markup(text: str) -> bool:
    return bool(re.search(r"</?(?:h[1-6]|li|p|br|ul|ol|div)\b", text, re.IGNORECASE))


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------
def _is_separator_or_metadata(text: str) -> bool:
    """A rule, a column of key and value, or a banner line: not content."""
    if _SEPARATOR_RE.match(text):
        return True
    if _METADATA_RE.match(text):
        return True
    return False


def _is_banner(text: str) -> bool:
    """All-caps text too long to be a heading — a notice, not an ask."""
    letters = [char for char in text if char.isalpha()]
    return len(letters) >= 8 and all(char.isupper() for char in letters)


def _is_noise(text: str) -> bool:
    return _is_separator_or_metadata(text) or _is_banner(text)


def _recognised_heading(text: str) -> Optional[_Tone]:
    heading = _clean_heading(text)
    if heading in _REQUIRED_HEADINGS:
        return _Tone.REQUIRED
    if heading in _PREFERRED_HEADINGS:
        return _Tone.PREFERRED
    if heading in _SKIP_HEADINGS:
        return _Tone.SKIP
    return None


def _looks_like_heading(text: str) -> bool:
    """A structural heading the lexicon does not know.

    Used to decide where a section begins when reading plain text, never to
    assign a priority: an unrecognised heading resets the tone to neutral.
    """
    if len(text) > 60 or text.endswith((".", "!", "?")):
        return False
    words = text.split()
    if not words or len(words) > 8:
        return False
    if text.endswith(":") or text.isupper():
        # "TECHNOLOGIES" and "STACK" name the set below them; the rule has to
        # survive the line being a single word, which is how those headings
        # are written.
        return True
    if len(words) < 2:
        # A lone word in mixed case is a term, not a title: "Python" is a
        # skill while "TECHNOLOGIES" above is a heading, and only their
        # capitalisation tells them apart.
        return False
    return len(words) <= 6 and all(
        not word[0].isalpha() or word[0].isupper() for word in words if word
    )


def _priority_of(text: str, tone: _Tone) -> tuple[RequirementPriority, bool]:
    """Priority a line claims for itself, falling back to its section.

    Returns ``(priority, stated)`` — ``stated`` distinguishes a priority the
    document claims, whether the line says it or a recognised heading does,
    from a line under a heading that says nothing, where the posting simply
    has not stated a priority.
    """
    lowered = text.lower()
    if any(marker in lowered for marker in _PREFERRED_LINE_MARKERS):
        return RequirementPriority.PREFERRED, True
    if _NOT_REQUIRED_RE.search(lowered):
        # "No prior experience required" is the one reading a naive match on
        # "required" would get backwards, and getting it backwards fails
        # candidates for something the posting never asked for.
        return RequirementPriority.UNKNOWN, True
    if any(marker in lowered for marker in _REQUIRED_LINE_MARKERS):
        return RequirementPriority.REQUIRED, True
    if tone is _Tone.REQUIRED:
        # The heading says so, which is as much a statement of priority as
        # a marker on the line itself.
        return RequirementPriority.REQUIRED, True
    if tone is _Tone.PREFERRED:
        return RequirementPriority.PREFERRED, True
    return RequirementPriority.UNKNOWN, False


def _min_years_of(text: str) -> Optional[float]:
    match = _YEARS_RE.search(text)
    if not match:
        return None
    value = float(match.group(1))
    return value if value <= 60 else None


def _kind_and_years(text: str) -> tuple[RequirementKind, Optional[float]]:
    lowered = text.lower()
    min_years = _min_years_of(text)

    matches: list[tuple[int, int, RequirementKind]] = []
    for term, kind in _LEXICON:
        if _TERM_RE[term].search(lowered):
            matches.append(
                (_KIND_RANK[kind], -len(term), kind)
            )
    if matches:
        matches.sort()
        kind = matches[0][2]
    elif min_years is not None:
        kind = RequirementKind.YEARS_OF_EXPERIENCE
    elif "experience" in lowered:
        kind = RequirementKind.EXPERIENCE
    else:
        kind = RequirementKind.OTHER
    return kind, min_years


def classify_term(term: str) -> RequirementKind:
    """The category the lexicon gives a bare term, or ``OTHER``.

    Exported so the candidate side files its skills under the same taxonomy
    the requirement side reads them with: "python" must land in
    ``PROGRAMMING_LANGUAGE`` on both sides or the gate would compare a skill
    against a category it never claims to be in.
    """
    kind, _years = _kind_and_years(term)
    return kind


def _term_list(text: str) -> Optional[list[str]]:
    """Split a stack line into its terms, or ``None``.

    Only ever fires when every element is a term the lexicon knows by name,
    which is what keeps it off prose: "Comfortable with SQL and SQLite for data
    modelling" is one judgement and is left whole, while
    "Python, Pydantic, SQLite, pytest" is a list of seven.
    """
    candidate = re.sub(r"\s+", " ", text).strip().rstrip(".!;,").strip()
    if not candidate or len(candidate) > 160:
        return None
    if re.search(r"[?!]|\.\s", candidate) or candidate.endswith(":"):
        return None
    parts = [part.strip() for part in re.split(r",|/|\band\b", candidate) if part.strip()]
    if not 2 <= len(parts) <= 12:
        return None
    known = {term.lower() for term, _ in _LEXICON}
    if not all(part.lower() in known for part in parts):
        return None
    return parts


def _has_signal(text: str) -> bool:
    """Whether a line says something a candidate must have.

    Covers both phrasings — a requirement signal ("experience with") and a
    term the lexicon knows — because a line written either way is an ask, and
    a years-of-experience figure, which is an ask whatever else it says.
    """
    lowered = text.lower()
    if _YEARS_RE.search(text):
        return True
    if any(signal in lowered for signal in _REQUIREMENT_SIGNALS):
        return True
    return any(_TERM_RE[term].search(lowered) for term, _ in _LEXICON)


def _sentences(text: str) -> list[str]:
    return [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", text)
        if part.strip()
    ] or ([text] if text.strip() else [])


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def extract_requirements(
    description: str,
    *,
    raw: Optional[str] = None,
) -> list[Requirement]:
    """Requirements read from a job description.

    Args:
        description: The normalised description text.
        raw: The description as markup, when it is available. Structure —
            headings, list items, paragraphs — is read from it, because the
            normalised form has already had that structure folded away.

    Returns:
        Requirements in document order, deduplicated on their normalised
        form. An unreadable or empty description yields an empty list rather
        than an exception: a job with no readable requirements is a fact to
        record, not a crash.
    """
    text = (description or "").strip()
    markup = (raw or "").strip()
    if len(text) < 20 and len(markup) < 20:
        log.debug("no description to read requirements from")
        return []

    requirements: list[Requirement] = []
    seen: dict[str, int] = {}
    tone = _Tone.NEUTRAL

    for block in _blocks(text, markup):
        block_text = block.text.strip()
        if not block_text:
            continue

        heading_tone = _recognised_heading(block_text)
        if heading_tone is not None:
            tone = heading_tone
            continue
        if _is_separator_or_metadata(block_text):
            continue
        if block.kind is _BlockKind.HEADING or (
            block.kind is _BlockKind.PARAGRAPH
            and _looks_like_heading(block_text)
        ):
            # An unrecognised heading ends the section it follows rather than
            # extending it: a stack list under "TECHNOLOGIES" is not part of
            # the responsibilities above it, and only reading it as neutral
            # keeps those two apart. List items are never read this way —
            # "Python" set alone is a term, and losing it would drop a real
            # requirement the moment a poster wrote a short one.
            tone = _Tone.NEUTRAL
            continue
        if block.kind is not _BlockKind.BULLET and _is_banner(block_text):
            # A notice in capitals is not an ask. Never applied to list items:
            # an enumerated "JAVASCRIPT" is a stack entry, not a banner.
            continue
        if tone is _Tone.SKIP:
            continue

        explicit_section = tone in (_Tone.REQUIRED, _Tone.PREFERRED)
        for line, listed in _lines_of(block):
            line = line.strip()
            if not line or _is_noise(line):
                continue
            if not (explicit_section and listed) and not _has_signal(line):
                continue
            requirement = _to_requirement(line, tone)
            _merge(requirements, seen, requirement)

    log.info(
        "requirements extracted",
        extra={"extraction": {"count": len(requirements), "method": "DETERMINISTIC"}},
    )
    return requirements


def merge_requirements(rows: Iterable[Requirement]) -> list[Requirement]:
    """``rows`` deduplicated on their normalised form, in their original order.

    Shared by both extraction paths so that a deterministic reading and a
    model's reading of the same posting fold the same way: duplicates collapse,
    a disagreement about priority is kept as the stricter reading and marked
    ambiguous, and a more specific category replaces a vague one. Documented
    behaviour rather than an implementation detail — the review queue relies on
    it to show one row per requirement.
    """
    merged: list[Requirement] = []
    seen: dict[str, int] = {}
    for row in rows:
        _merge(merged, seen, row)
    return merged


def _lines_of(block: _Block) -> Sequence[tuple[str, bool]]:
    """Lines to consider for one block, each flagged when it was *listed*.

    A listed line — a bullet, or one element of a term list — is something the
    poster chose to enumerate, which under a requirements heading needs no
    further evidence that it is an ask. Prose does not get that benefit.
    """
    terms = _term_list(block.text)
    if terms:
        return [(term, True) for term in terms]
    if block.kind is _BlockKind.BULLET:
        return [(block.text, True)]
    return [(sentence, False) for sentence in _sentences(block.text)]


def _to_requirement(text: str, tone: _Tone) -> Requirement:
    priority, stated = _priority_of(text, tone)
    kind, min_years = _kind_and_years(text)
    if min_years is not None and kind in (
        RequirementKind.OTHER,
        RequirementKind.EXPERIENCE,
    ):
        kind = RequirementKind.YEARS_OF_EXPERIENCE
    excerpt = text.strip()
    return Requirement(
        kind=kind,
        text=excerpt,
        normalized=normalize_text(excerpt).lower(),
        priority=priority,
        min_years=min_years,
        source_excerpt=excerpt,
        extraction_source=ExtractionMethod.DETERMINISTIC,
        confidence=_CONFIDENCE_STATED if stated else _CONFIDENCE_INFERRED,
    )


def _merge(
    requirements: list[Requirement],
    seen: dict[str, int],
    requirement: Requirement,
) -> None:
    """Append or fold into an equal requirement already read.

    Requirements are deduplicated on their normalised form because a posting
    may name the same skill under "requirements" and under its stack list.
    A genuine disagreement between those readings — required in one, preferred
    in the other — is kept as the stricter reading and marked ambiguous, so it
    reaches review instead of quietly deciding a match.
    """
    key = (requirement.normalized or requirement.text).lower()
    index = seen.get(key)
    if index is None:
        seen[key] = len(requirements)
        requirements.append(requirement)
        return

    kept = requirements[index]
    priorities = {kept.priority, requirement.priority}
    if priorities == {
        RequirementPriority.REQUIRED,
        RequirementPriority.PREFERRED,
    }:
        merged_priority = RequirementPriority.REQUIRED
        ambiguous = True
    elif RequirementPriority.UNKNOWN in priorities and len(priorities) > 1:
        # One side named a priority and the other did not; only the side that
        # spoke is carried. Two unknowns are not a disagreement, and the
        # branch must not run for them — there would be nothing to pick.
        merged_priority = next(
            priority for priority in priorities if priority is not RequirementPriority.UNKNOWN
        )
        ambiguous = False
    else:
        merged_priority = kept.priority
        ambiguous = False

    if (
        _KIND_RANK[requirement.kind] < _KIND_RANK[kept.kind]
        or kept.kind is RequirementKind.OTHER
    ):
        kind = requirement.kind
    else:
        kind = kept.kind

    requirements[index] = kept.model_copy(
        update={
            "priority": merged_priority,
            "ambiguous": kept.ambiguous or ambiguous or requirement.ambiguous,
            "kind": kind,
            "min_years": max(
                value
                for value in (kept.min_years, requirement.min_years)
                if value is not None
            )
            if (kept.min_years is not None or requirement.min_years is not None)
            else None,
            "confidence": max(kept.confidence, requirement.confidence),
        }
    )
