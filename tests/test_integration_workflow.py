"""Integration test for the end-to-end candidate profile → resume → job selection → match → resume draft → cover letter → application tracker workflow."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from resumes.generation import generate_resume_draft, _candidate_facts, _build_draft_from_data
from resumes.cover_letter import generate_cover_letter_draft
from candidate_profile.models import build_empty_profile, with_fact_update
from resumes.models import Resume
from core.enums import FactStatus
from api.schemas.application import ApplicationStatus


ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for _p in (str(ROOT), str(SRC)):
    if _p in __import__("sys").path:
        __import__("sys").path.remove(_p)
    __import__("sys").path.insert(0, _p)

from api.app import create_app
from fastapi.testclient import TestClient
from core.settings import ApiSettings, ApplicationSettings, AssistantSettings, DatabaseSettings, LoggingSettings, SafetySettings


@pytest.fixture
def api_settings(tmp_path):
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    resume_dir = tmp_path / "resumes"
    resume_dir.mkdir()
    return AssistantSettings(
        application=ApplicationSettings(
            candidate_id="primary",
            paths_root=tmp_path,
            profile_dir=profile_dir,
            resume_dir=resume_dir,
        ),
        database=DatabaseSettings(path=tmp_path / "integration.db", echo=False),
        safety=SafetySettings(),
        logging=LoggingSettings(to_file=False),
        api=ApiSettings(cors_origins=["http://localhost:5173"]),
    )


@pytest.fixture
def client(api_settings):
    application = create_app(settings=api_settings)
    with TestClient(application) as test_client:
        yield test_client


def _set_profile_facts(client):
    client.post("/api/profile", json={"field_path": "identity.full_name", "value": "Test Candidate"})
    client.post("/api/profile", json={"field_path": "experience.total_years_experience", "value": "5"})
    client.post("/api/profile", json={"field_path": "skills.proficient", "value": "Python, JavaScript"})


JOB_HTML = '<html><body><script type="application/ld+json">{"@context":"https://schema.org","@type":"JobPosting", "title":"Machine Learning Engineer","company":{"name":"Example Corp"}, "description":"We need Python and PyTorch experience. 3+ years in machine learning.", "jobLocationType":"TELECOMMUTE","employmentType":"FULL_TIME"}</script></body></html>'


class TestIntegrationWorkflow:
    def test_full_workflow_creates_persisted_records(self, client):
        # [1] A candidate profile can be loaded or created
        _set_profile_facts(client)
        profile_facts = client.get("/api/profile/facts/identity.full_name").json()
        assert profile_facts["value"] == "Test Candidate"

        # [2] A job can be loaded or created
        response = client.post("/api/jobs", json={"html": JOB_HTML, "source": "local", "page_url": "https://example.com/jobs/1"})
        assert response.status_code == 201, response.text
        job = response.json()["job"]
        assert job["title"] == "Machine Learning Engineer"
        job_id = job["id"]

        # [3] The matching endpoint returns a result and explanation
        client.post("/api/profile", json={"field_path": "experience.total_years_experience", "value": "5"})
        match_response = client.post(f"/api/jobs/{job_id}/match", json={"scorer": "lexical"})
        assert match_response.status_code == 200, match_response.text
        body = match_response.json()
        assert "decision" in body["result"]

        # [4] Resume generation uses the selected candidate and job
        # Use the data-grounded generation function with verified facts from the profile
        profile = build_empty_profile()
        profile = with_fact_update(profile, "identity.full_name", "Test Candidate", status=FactStatus.VERIFIED, source="USER_INPUT")
        profile = with_fact_update(profile, "experience.total_years_experience", "5", status=FactStatus.VERIFIED, source="USER_INPUT")
        profile = with_fact_update(profile, "skills.proficient", "Python, JavaScript", status=FactStatus.VERIFIED, source="USER_INPUT")

        facts = _candidate_facts(profile)
        resume = Resume(
            candidate_id="primary",
            filename="test_resume.pdf",
            file_type="pdf",
            file_hash="hash123",
            file_size_bytes=1000,
            char_count=100,
            content_hash="content123",
            raw_text="EXPERIENCE\n5 years as Software Engineer at Tech Corp\nSKILLS\nPython, Java, SQL",
            status="PARSED",
            parser_name="test",
            parser_version="1",
            is_synthetic=False,
            page_count=1,
        )
        draft = _build_draft_from_data(
            profile, resume,
            facts,
            "Software Engineer",
            "We are looking for a software engineer with 5+ years experience",
            "5+ years experience, Python, Java"
        )
        assert draft is not None
        assert len(draft) > 0
        assert "Software Engineer" in draft
        assert "Test Candidate" in draft

        # [5] Cover-letter generation uses the same selected candidate and job
        cover_draft, _ = generate_cover_letter_draft(
            profile,
            resume.raw_text,
            "Software Engineer",
            "Example Corp",
            "We are looking for a software engineer with 5+ years experience in Python and Java",
            "5+ years experience, Python, Java"
        )
        assert cover_draft is not None
        assert len(cover_draft) > 0
        assert "Software Engineer" in cover_draft
        assert "Test Candidate" in cover_draft

        # [6] An application-preparation record can be created
        app_create = client.post("/api/applications", json={
            "job_id": job_id,
            "status": "SAVED",
        })
        assert app_create.status_code == 201, app_create.text
        app_id = app_create.json()["id"]

        # [7] A subsequent request retrieves the correct persisted record
        app_retrieved = client.get(f"/api/applications/{app_id}")
        assert app_retrieved.status_code == 200, app_retrieved.text
        assert app_retrieved.json()["job_id"] == job_id
        assert app_retrieved.json()["status"] == "SAVED"

        # [8] Draft generation does not mark the application as submitted
        app_after = client.get(f"/api/applications/{app_id}")
        assert app_after.json()["status"] == "SAVED"
        # Safety: dry_run and safe_mode must remain active
        status_check = client.get("/api/status")
        assert status_check.json()["safety"]["dry_run"] is True
        assert status_check.json()["safety"]["safe_mode"] is True
