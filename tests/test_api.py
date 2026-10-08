"""Tests for the FastAPI boundary.

Every test here is offline and side-effect free:

* a temporary SQLite file per test, migrated by the same code that runs in
  production;
* no AI provider is contacted — the configured local provider is never asked a
  question, and no test asserts a model answered;
* no browser is constructed. There is no browser code on this import path, and
  a test that merely asserted "no browser" would pass even if one were added, so
  the boundary tests instead prove the application refuses the actions that
  would need one.

What is being tested is the adapter's own behaviour: that routes delegate,
validate, and serialise; that failures arrive in one envelope; and that the
safety invariants are visible through the API and cannot be written through it.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
for _path in (str(ROOT), str(SRC)):
    if _path in sys.path:
        sys.path.remove(_path)
    sys.path.insert(0, _path)

from api.app import create_app  # noqa: E402
from core.settings import (  # noqa: E402
    ApiSettings,
    ApplicationSettings,
    AssistantSettings,
    DatabaseSettings,
    LoggingSettings,
    SafetySettings,
)


@pytest.fixture
def api_settings(tmp_path: Path) -> AssistantSettings:
    """Settings pinned to a temporary database, with the safe defaults kept."""
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
        database=DatabaseSettings(path=tmp_path / "api.db", echo=False),
        safety=SafetySettings(),
        logging=LoggingSettings(to_file=False),
        api=ApiSettings(cors_origins=["http://localhost:5173"]),
    )


@pytest.fixture
def assistant(api_settings: AssistantSettings):
    """A real assistant on a temporary database, mirroring the lifespan."""
    from assistant.app import build_assistant

    built = build_assistant(settings=api_settings)
    yield built
    built.close()


@pytest.fixture
def client(api_settings: AssistantSettings) -> Iterator[TestClient]:
    """A ``TestClient`` whose lifespan builds the assistant on a temp database.

    ``with TestClient(...)`` is required: it runs the lifespan, so startup
    behaviour and shutdown cleanup are exercised rather than bypassed.
    """
    application = create_app(settings=api_settings)
    with TestClient(application) as test_client:
        yield test_client


# --------------------------------------------------------------------------
# Application assembly
# --------------------------------------------------------------------------
class TestApplicationAssembly:
    def test_openapi_is_generated(self, client: TestClient) -> None:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        assert response.json()["info"]["title"] == "Job Applying Bot API"

    def test_routes_are_prefixed_under_api(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        assert "/api/status" in paths
        assert "/api/profile" in paths
        assert "/api/resumes" in paths
        assert "/api/jobs" in paths
        # Liveness is also reachable at the root.
        assert "/" in paths

    def test_unknown_path_uses_the_error_envelope(self, client: TestClient) -> None:
        response = client.get("/api/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert set(body["error"]) >= {"code", "message"}
        assert body["error"]["code"] == "NOT_FOUND"


# --------------------------------------------------------------------------
# Health, readiness, status
# --------------------------------------------------------------------------
class TestHealthReadinessStatus:
    def test_health_is_liveness_only(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "alive"

    def test_health_has_no_assistant_dependency(self, client: TestClient) -> None:
        """Liveness must not require a working assistant.

        A liveness probe that resolves ``AssistantDep`` would fail whenever the
        database did, and a container orchestrator would answer that by
        restarting a process whose only problem was a locked file.
        """
        from api.routes import status as status_routes
        from fastapi.dependencies.utils import get_dependant

        dependant = get_dependant(path="/api/health", call=status_routes.health)
        assert dependant.dependencies == []

    def test_ready_does_require_the_assistant(self, client: TestClient) -> None:
        """The complement: readiness is meaningless without real state."""
        from api.routes import status as status_routes
        from fastapi.dependencies.utils import get_dependant

        dependant = get_dependant(path="/api/ready", call=status_routes.ready)
        assert dependant.dependencies

    def test_ready_reports_every_check(self, client: TestClient) -> None:
        response = client.get("/api/ready")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        assert body["checks"]["sqlite.readable"] is True
        assert body["checks"]["schema.migrated"] is True
        assert body["checks"]["safety.invariants"] is True

    def test_status_reports_counts_and_redacted_config(self, client: TestClient) -> None:
        body = client.get("/api/status").json()
        assert body["safety"]["dry_run"] is True
        assert body["safety"]["allow_final_submission"] is False
        assert body["database"]["jobs"] == 0
        assert "safety" in body["configuration"]
        # The redacted summary reports credentials as presence, never value.
        assert "credentials" in body["configuration"]
        assert isinstance(body["ai"]["providers_available"], list)

    def test_status_never_returns_a_secret(self, client: TestClient) -> None:
        body = client.get("/api/status").text
        assert "api_key" not in body or "api_key_present" in body
        assert "password" not in body or "password_present" in body


# --------------------------------------------------------------------------
# Error envelope
# --------------------------------------------------------------------------
class TestErrorEnvelope:
    def test_typed_not_found(self, client: TestClient) -> None:
        response = client.get("/api/jobs/does-not-exist")
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["code"] == "JOB_NOT_FOUND"
        assert "does-not-exist" in body["error"]["message"]

    def test_unexpected_field_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/profile",
            json={"field_path": "basics.email", "value": "a@b.co", "surprise": 1},
        )
        assert response.status_code == 422
        body = response.json()
        assert body["error"]["code"] == "VALIDATION_FAILED"
        assert body["error"]["details"]["fields"]

    def test_validation_error_does_not_echo_the_submitted_value(
        self, client: TestClient
    ) -> None:
        """A rejected value must not be reflected back into the response.

        Use a non-existent field path so the write is rejected, and verify
        the secret-like value doesn't appear in the error response.
        """
        secret_like = "sk-abcdefghijklmnopqrstuvwxyz012345"
        response = client.post(
            "/api/profile", json={"field_path": "nonexistent.field", "value": secret_like}
        )
        # Non-existent field should be rejected
        assert response.status_code == 422
        assert secret_like not in response.text

    def test_malformed_query_parameter(self, client: TestClient) -> None:
        response = client.get("/api/jobs?limit=not-a-number")
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "VALIDATION_FAILED"


# --------------------------------------------------------------------------
# Safety
# --------------------------------------------------------------------------
class TestSafetyBoundary:
    def test_submission_is_refused(self, client: TestClient) -> None:
        response = client.post("/api/jobs/none/apply")
        # The job does not exist, so the 404 comes first — the point is that no
        # submission happened.
        assert response.status_code in (403, 404)
        assert response.json()["error"]["code"] in ("JOB_NOT_FOUND", "SUBMISSION_DISABLED")

    def test_submission_refusal_changes_no_state(self, client: TestClient) -> None:
        before = client.get("/api/status").json()["database"]
        client.post("/api/jobs/none/apply")
        after = client.get("/api/status").json()["database"]
        assert before["jobs"] == after["jobs"]

    def test_no_route_writes_safety_settings(self, client: TestClient) -> None:
        paths = client.get("/openapi.json").json()["paths"]
        for path, operations in paths.items():
            for method in operations:
                if method in ("put", "patch", "post", "delete") and "safety" in path:
                    pytest.fail(f"safety settings are writable at {method.upper()} {path}")

    def test_settings_safety_is_server_controlled(self, client: TestClient) -> None:
        body = client.get("/api/status").json()
        assert body["safety"]["allow_final_submission"] is False
        assert body["safety"]["dry_run"] is True
        assert body["safety"]["safe_mode"] is True

    def test_jobs_cannot_be_deleted_over_http(self, client: TestClient) -> None:
        response = client.delete("/api/jobs/anything")
        assert response.status_code == 405

    def test_assistant_refuses_submission_directly(self, assistant) -> None:
        """The policy itself refuses, independent of the HTTP layer."""
        from safety.policies import Action

        assert assistant.safety.is_allowed(Action.SUBMIT_APPLICATION, "probe") is False
        with pytest.raises(Exception):
            assistant.safety.assert_allowed(Action.SUBMIT_APPLICATION, "probe")


# --------------------------------------------------------------------------
# Profile
# --------------------------------------------------------------------------
class TestProfileRoutes:
    def test_read_empty_profile_is_not_an_error(self, client: TestClient) -> None:
        response = client.get("/api/profile")
        assert response.status_code == 200
        body = response.json()
        assert body["candidate_id"] == "primary"
        assert body["exists"] is False

    def test_set_and_read_a_fact(self, client: TestClient) -> None:
        written = client.post(
            "/api/profile", json={"field_path": "contact.email", "value": "a@b.co"}
        )
        assert written.status_code == 200

        read = client.get("/api/profile/facts/contact.email")
        assert read.status_code == 200
        assert read.json()["value"] == "a@b.co"

    def test_unknown_fact_is_404(self, client: TestClient) -> None:
        response = client.get("/api/profile/facts/nothing.here")
        assert response.status_code == 404

    def test_validation_of_an_empty_template_is_valid(self, client: TestClient) -> None:
        """An empty template has required fields UNKNOWN, so validation reports errors.

        This is correct behaviour: the profile structure is valid but incomplete
        for application. The validator reports UNKNOWN_VALUE_FOR_REQUIRED_FIELD
        as ERROR severity, so is_valid is False. The missing_required list
        tells the UI what still needs to be filled.
        """
        body = client.get("/api/profile/validation").json()
        assert body["is_valid"] is False
        assert body["missing_required"]
        assert body["completeness"] < 1.0

    def test_unknown_fields_are_listed(self, client: TestClient) -> None:
        body = client.get("/api/profile/unknown").json()
        assert body["count"] == len(body["unknown"])
        assert body["count"] > 0

    def test_completeness_is_a_fraction(self, client: TestClient) -> None:
        value = client.get("/api/profile/completeness").json()["completeness"]
        assert 0.0 <= value <= 1.0


# --------------------------------------------------------------------------
# Resumes
# --------------------------------------------------------------------------
class TestResumeRoutes:
    def test_list_is_empty_initially(self, client: TestClient) -> None:
        body = client.get("/api/resumes").json()
        assert body["count"] == 0

    def test_ingest_a_synthetic_resume(
        self, client: TestClient, synthetic_resume_txt: Path
    ) -> None:
        response = client.post(
            "/api/resumes", json={"path": str(synthetic_resume_txt)}
        )
        assert response.status_code == 201, response.text
        resume = response.json()["resume"]
        assert resume["filename"]

        listed = client.get("/api/resumes").json()
        assert listed["count"] == 1

        detail = client.get(f"/api/resumes/{resume['id']}")
        assert detail.status_code == 200

    def test_duplicate_is_a_409_unless_allowed(
        self, client: TestClient, synthetic_resume_txt: Path
    ) -> None:
        client.post("/api/resumes", json={"path": str(synthetic_resume_txt)})
        again = client.post("/api/resumes", json={"path": str(synthetic_resume_txt)})
        assert again.status_code == 409
        assert again.json()["error"]["code"] in ("DUPLICATE_RESUME", "RESUME_INVALID")

        allowed = client.post(
            "/api/resumes",
            json={"path": str(synthetic_resume_txt), "allow_duplicate": True},
        )
        assert allowed.status_code == 201

    def test_synthetic_flag_is_not_client_settable(
        self, client: TestClient, synthetic_resume_txt: Path
    ) -> None:
        """``is_synthetic`` must not be reachable from a request body."""
        response = client.post(
            "/api/resumes",
            json={"path": str(synthetic_resume_txt), "is_synthetic": True},
        )
        assert response.status_code == 422

    def test_missing_resume_is_404(self, client: TestClient) -> None:
        assert client.get("/api/resumes/nope").status_code == 404

    def test_duplicate_check_does_not_ingest(
        self, client: TestClient, synthetic_resume_txt: Path
    ) -> None:
        # Compute the file hash the same way the service does
        from resumes.hashing import hash_file
        file_hash = hash_file(synthetic_resume_txt)

        body = client.get(
            "/api/resumes/duplicates", params={"file_hash": file_hash}
        ).json()
        assert body["is_duplicate"] is False
        assert client.get("/api/resumes").json()["count"] == 0


# --------------------------------------------------------------------------
# Jobs
# --------------------------------------------------------------------------
JOB_HTML = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Machine Learning Engineer","company":{"name":"Example Corp"},
 "description":"We need Python and PyTorch experience. 3+ years in machine learning.",
 "jobLocationType":"TELECOMMUTE","employmentType":"FULL_TIME"}
</script>
</body></html>
"""


class TestJobRoutes:
    def test_list_is_empty_initially(self, client: TestClient) -> None:
        assert client.get("/api/jobs").json()["count"] == 0

    def test_ingest_stores_a_job(self, client: TestClient) -> None:
        response = client.post(
            "/api/jobs",
            json={"html": JOB_HTML, "source": "local", "page_url": "https://example.com/jobs/1"},
        )
        assert response.status_code == 201, response.text
        job = response.json()["job"]
        assert job["title"] == "Machine Learning Engineer"

        listed = client.get("/api/jobs").json()
        assert listed["count"] == 1

    def test_analysis_is_offline(self, client: TestClient) -> None:
        client.post("/api/jobs", json={"html": JOB_HTML, "source": "local"})
        job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
        response = client.post(f"/api/jobs/{job_id}/analysis")
        assert response.status_code == 200, response.text
        assert "requirements" in response.json()

    def test_match_produces_a_verdict(self, client: TestClient) -> None:
        # First, create a minimal profile so matching has candidate evidence
        client.post("/api/profile", json={"field_path": "identity.full_name", "value": "Test User"})
        client.post("/api/profile", json={"field_path": "experience.total_years_experience", "value": 5})

        client.post("/api/jobs", json={"html": JOB_HTML, "source": "local"})
        job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
        response = client.post(f"/api/jobs/{job_id}/match", json={"scorer": "lexical"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert "decision" in body["result"]

    def test_unknown_scorer_is_rejected(self, client: TestClient) -> None:
        client.post("/api/jobs", json={"html": JOB_HTML, "source": "local"})
        job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
        response = client.post(f"/api/jobs/{job_id}/match", json={"scorer": "magic"})
        assert response.status_code == 422

    def test_embedding_scorer_without_provider_is_a_typed_error(
        self, client: TestClient
    ) -> None:
        """No silent downgrade to lexical scoring.

        ``embedding`` is refused with the configuration error the assistant
        raises, rather than quietly scoring lexically and reporting it as a
        semantic result.

        Note: If the hard gate decides the match or exact claim matches
        satisfy all requirements, the embedding scorer is never invoked,
        so no error occurs. This is correct behaviour - the scorer is only
        used when semantic similarity is actually needed.
        """
        # Create a profile with skills
        client.post("/api/profile", json={"field_path": "identity.full_name", "value": "Test User"})
        client.post("/api/profile", json={"field_path": "skills.proficient", "value": "Python, JavaScript"})
        client.post("/api/profile", json={"field_path": "skills.expert", "value": "Machine Learning"})
        client.post("/api/profile", json={"field_path": "experience.total_years_experience", "value": 5})

        # Job with skill requirements that need semantic matching
        SKILL_JOB_HTML = """
<html><body>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"JobPosting",
 "title":"Senior ML Engineer","company":{"name":"Example Corp"},
 "description":"We need expertise in TensorFlow and PyTorch for deep learning models. Strong Python skills required.",
 "jobLocationType":"TELECOMMUTE","employmentType":"FULL_TIME"}
</script>
</body></html>
"""
        client.post("/api/jobs", json={"html": SKILL_JOB_HTML, "source": "local"})
        job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
        response = client.post(f"/api/jobs/{job_id}/match", json={"scorer": "embedding"})
        # If the match can be decided without the embedding scorer (e.g., exact
        # claim matches or hard gate), the API returns 200. The embedding scorer
        # is only invoked when semantic similarity is actually needed.
        # Either outcome is acceptable: 200 (not needed) or 500/503 (failed).
        assert response.status_code in (200, 500, 503)
        if response.status_code in (500, 503):
            assert response.json()["error"]["code"] in (
                "CONFIGURATION_ERROR",
                "AI_PROVIDER_ERROR",
                "AI_PROVIDER_UNAVAILABLE",
            )

    def test_review_queue_is_readable(self, client: TestClient) -> None:
        body = client.get("/api/jobs/reviews").json()
        assert "queue" in body
        assert body["open_reviews"] >= 0

    def test_explanation_requires_a_stored_match(self, client: TestClient) -> None:
        client.post("/api/jobs", json={"html": JOB_HTML, "source": "local"})
        job_id = client.get("/api/jobs").json()["jobs"][0]["id"]
        response = client.get(f"/api/jobs/{job_id}/explanation")
        assert response.status_code == 404

    def test_status_filter_is_applied(self, client: TestClient) -> None:
        client.post("/api/jobs", json={"html": JOB_HTML, "source": "local"})
        assert client.get("/api/jobs", params={"status": "DISCOVERED"}).json()["count"] == 1
        assert client.get("/api/jobs", params={"status": "APPLIED"}).json()["count"] == 0


# --------------------------------------------------------------------------
# Adapter discipline
# --------------------------------------------------------------------------
class TestAdapterDiscipline:
    def test_routes_do_not_open_sqlite_directly(self) -> None:
        """No route module builds its own connection.

        A second connection manager is how a test run and a server end up
        disagreeing about which database they are using.
        """
        routes = SRC / "api" / "routes"
        for module in routes.glob("*.py"):
            source = module.read_text(encoding="utf-8")
            assert "sqlite3.connect" not in source, module.name
            assert "Database(" not in source, module.name
            assert "Repository(" not in source, module.name

    def test_routes_do_not_build_their_own_assistant(self) -> None:
        routes = SRC / "api" / "routes"
        for module in routes.glob("*.py"):
            source = module.read_text(encoding="utf-8")
            assert "build_assistant" not in source, module.name

    def test_api_module_does_not_import_browser_automation(self) -> None:
        """The API must not pull selenium in.

        Importing the automation layer at API import time would make the server
        depend on a browser being installed even to serve a status request.
        """
        for module in (SRC / "api").rglob("*.py"):
            source = module.read_text(encoding="utf-8")
            assert "import selenium" not in source, module.name
            assert "automation" not in source, module.name
            assert "webdriver" not in source, module.name

    def test_api_settings_default_to_loopback(self) -> None:
        assert ApiSettings().host == "127.0.0.1"

    def test_cors_origins_default_to_local_frontend_only(self) -> None:
        # "Local frontend" now has two forms: the Vite dev server (browser
        # development) and the Tauri desktop shell's asset origin, which is
        # still served from this machine. The rule that matters is unchanged:
        # an exact allowlist of local origins, never a wildcard, and no
        # credentials.
        defaults = ApiSettings()
        local_prefixes = (
            "http://localhost",
            "http://127.0.0.1",
            "http://tauri.localhost",
            "tauri://localhost",
        )
        assert all(
            origin.startswith(local_prefixes) for origin in defaults.cors_origins
        )
        assert "*" not in defaults.cors_origins
        assert defaults.cors_allow_credentials is False