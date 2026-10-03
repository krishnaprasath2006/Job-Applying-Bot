"""Shared pytest fixtures.

``src`` is placed on ``sys.path`` at position 0 rather than relying on an
installed package, so ``pytest`` works from a clean checkout without an install
step. The project root is also added because the legacy modules (``config``,
``utils``, ``constants``) live there and must keep importing under their
original names; that is what the legacy compatibility tests check.

Order matters: ``src`` must come first, otherwise the ``assistant`` package
could resolve to something in the project root.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"

for _path in (str(ROOT), str(SRC)):
    if _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)

# Assert the ordering rather than trusting it: a silent misordering here would
# surface as a confusing ImportError inside an unrelated test.
assert sys.path.index(str(SRC)) < sys.path.index(str(ROOT)), (
    "src must precede the project root on sys.path"
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(scope="session")
def project_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def synthetic_resume_txt() -> Path:
    return FIXTURES / "synthetic_resume.txt"


@pytest.fixture
def synthetic_resume_pdf() -> Path:
    return FIXTURES / "synthetic_resume.pdf"


@pytest.fixture
def synthetic_resume_docx() -> Path:
    return FIXTURES / "synthetic_resume.docx"


@pytest.fixture
def synthetic_job_description() -> Path:
    return FIXTURES / "synthetic_job_description.txt"


@pytest.fixture
def synthetic_candidate() -> dict:
    import json

    return json.loads((FIXTURES / "synthetic_candidate.json").read_text(encoding="utf-8"))


@pytest.fixture
def db(tmp_path: Path) -> Iterator:
    """A migrated database in a temporary directory, closed on teardown."""
    from database.connection import Database

    database = Database(tmp_path / "test.db")
    database.initialize()
    yield database
    database.close()


@pytest.fixture
def safety_settings() -> "object":
    """Default safety settings, which are the safe ones by construction."""
    from core.settings import SafetySettings

    return SafetySettings()
