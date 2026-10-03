# Test fixtures

**Everything in this directory is synthetic.** No file here describes a real
person, employer, vacancy, or credential. Every fixture is marked
`SYNTHETIC TEST DATA ONLY` so it is obvious both in review and in a diff.

Real candidate data must never be added here. Real resumes live in
`data/resumes/` (git-ignored), and the real profile lives in
`data/profile/candidate_profile.json` (also git-ignored). This directory is the
only place test data belongs.

## Files

| File | What it is | Regenerate |
|---|---|---|
| `synthetic_candidate.json` | A candidate profile with a handful of populated facts, including deliberately imperfect entries (a duplicate skill, an overlapping date range) so the validator has something to report. | hand-maintained |
| `synthetic_resume.txt` | A plain-text resume. Exercises the TXT extractor and the deterministic section parser. | hand-maintained |
| `synthetic_resume.pdf` | A one-page PDF resume. Exercises the pdfplumber extractor and the page-count path. | `python tests/fixtures/make_binary_fixtures.py` |
| `synthetic_resume.docx` | A DOCX resume including a table, so the table-reading path is covered. | `python tests/fixtures/make_binary_fixtures.py` |
| `synthetic_job_description.txt` | A fictional job posting with required and nice-to-have requirements, used by the job normaliser and deduplicator tests. | hand-maintained |
| `make_binary_fixtures.py` | Generates the PDF and DOCX. Written as code rather than committed as opaque binaries so the contents are reviewable. | — |

## Why the binary fixtures are generated

`reportlab` is not a project dependency and adding it just to produce a test
file would turn a test-only concern into a runtime requirement. The PDF writer
in `make_binary_fixtures.py` is a small hand-rolled PDF 1.4 emitter using only
the standard library; the script immediately verifies the result by reading it
back through `pdfplumber`, the same library the parser uses. The DOCX is
written with `python-docx`, which is already a dependency.

## Using them in tests

```python
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
resume_pdf = FIXTURES / "synthetic_resume.pdf"
```

Any resume passed to `ResumeService.ingest()` in a test should carry
`is_synthetic=True` (or be ingested with that flag) so synthetic data is
tagged as synthetic in the database and can never be confused with real data.
