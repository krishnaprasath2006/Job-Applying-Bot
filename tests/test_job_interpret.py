"""AI interpretation: a model's reading of a posting, checked against the
posting.

Three contracts: the prompt is grounded in the posting alone (and bounded);
validation refuses a reading whose evidence is missing or foreign — a
response that fails is persisted as a *failed* run, never as a success; and
the service falls back to the deterministic extractor while recording the
attempt under the AI cache key, so a fallback can never masquerade as a
model reading and the next call retries the model.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import pytest
from pydantic import ValidationError

from ai.provider import StructuredResult
from assistant.job_service import JobService
from core.enums import (
    AnalysisSource,
    ExtractionMethod,
    ModelRunStatus,
    ModelRunTask,
)
from core.errors import (
    AIProviderError,
    AIResponseValidationError,
    ConfigurationError,
    JobExtractionError,
    ProviderUnavailableError,
)
from core.model_run import ModelRun
from jobs.extraction_schema import RequirementExtraction
from jobs.acquisition import parse_job_page
from jobs.interpret import (
    INTERPRETER,
    MAX_PROMPT_CHARS,
    build_prompt,
    error_code_for,
    interpret,
    interpret_prompt_version,
    validate_extraction,
)
from jobs.models import Job
from candidate_profile.service import ProfileService

EVIDENCE_YEARS = "5+ years of hands-on machine learning experience"
EVIDENCE_SKILL = "Strong Python and SQL"


def fixture_text(fixtures_dir: Path) -> str:
    html = (fixtures_dir / "html" / "job_detail.html").read_text(encoding="utf-8")
    page = parse_job_page(
        html, source="fixture", page_url="https://example.test/jobs/view/1"
    )
    assert page.description_text
    return page.description_text


def payload(*, evidence: Optional[str] = EVIDENCE_YEARS) -> dict:
    return {
        "requirements": [
            {
                "text": "5+ years of hands-on machine learning experience",
                "category": "EXPERIENCE",
                "priority": "REQUIRED",
                "min_years": 5,
                "evidence": evidence,
                "confidence": 0.9,
            },
            {
                "text": "Strong Python and SQL",
                "category": "SKILL",
                "priority": "REQUIRED",
                "evidence": EVIDENCE_SKILL,
                "confidence": 0.95,
            },
        ]
    }


class FakeProvider:
    """A provider that answers from a fixed payload or raises on demand."""

    name = "fake"
    model = "fake-1"
    supports_embeddings = True

    def __init__(self, *, payload: Optional[dict] = None, error: Optional[BaseException] = None):
        self._payload = payload
        self._error = error
        self.calls: list[dict] = []

    def generate_structured(
        self,
        prompt: str,
        response_model,
        *,
        task: ModelRunTask = ModelRunTask.EXTRACT,
        model: Optional[str] = None,
        analysis_source: AnalysisSource = AnalysisSource.AI_GENERAL,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        options=None,
        prompt_version: str = "x",
        **kwargs,
    ) -> StructuredResult:
        self.calls.append(
            {
                "prompt": prompt,
                "task": task,
                "analysis_source": analysis_source,
                "system": system,
                "model": model,
                "prompt_version": prompt_version,
            }
        )
        run = ModelRun.start(
            provider=self.name,
            model=model or self.model,
            task=task,
            prompt=prompt,
            analysis_source=analysis_source,
            prompt_version=prompt_version,
        )
        if self._error is not None:
            run.fail(str(self._error))
            raise self._error
        body = json.dumps(self._payload)
        try:
            value = response_model.model_validate(self._payload)
        except ValidationError:
            failed = run.fail("structured parse failed")
            raise AIProviderError(
                "output did not match RequirementExtraction", run_id=failed.id
            ) from None
        run.complete(body, 5)
        return StructuredResult(
            value=value, run=run, raw_text=body, analysis_source=analysis_source
        )


@pytest.fixture()
def profiles(tmp_path, db) -> ProfileService:
    service = ProfileService(db, storage_path=tmp_path / "candidate_profile.json")
    service.create_profile("primary", persist_json=True, actor="user")
    return service


@pytest.fixture()
def service(db, profiles) -> JobService:
    return JobService(db, profile_service=profiles, candidate_id="primary")


@pytest.fixture()
def description(fixtures_dir) -> str:
    return fixture_text(fixtures_dir)


@pytest.fixture()
def job(service, fixtures_dir) -> Job:
    result = service.ingest_page(
        (fixtures_dir / "html" / "job_detail.html").read_text(encoding="utf-8"),
        source="fixture",
    )
    return result.job


# ---------------------------------------------------------------------------
# The prompt
# ---------------------------------------------------------------------------
class TestPrompt:
    def test_it_names_every_category_and_quotes_the_posting(
        self, description: str
    ) -> None:
        prompt = build_prompt(description)
        assert description[:80] in prompt
        assert "EXPERIENCE" in prompt
        assert "SKILL" in prompt
        assert "verbatim" in prompt

    def test_it_is_bounded(self) -> None:
        prompt = build_prompt("x" * (MAX_PROMPT_CHARS * 3))
        assert len(prompt) < MAX_PROMPT_CHARS + 4_000

    def test_it_carries_no_candidate_data(self, description: str) -> None:
        prompt = build_prompt(description).lower()
        assert "candidate" not in prompt
        assert "resume" not in prompt


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
class TestValidation:
    def test_nothing_found_in_a_real_posting_is_refused(self, description: str) -> None:
        empty = RequirementExtraction(requirements=[])
        with pytest.raises(AIResponseValidationError, match="no requirements"):
            validate_extraction(empty, description=description)

    def test_nothing_found_in_a_stub_is_allowed(self) -> None:
        validate_extraction(
            RequirementExtraction(requirements=[]), description="Senior role"
        )

    def test_a_requirement_without_evidence_is_refused(self, description: str) -> None:
        body = payload()
        body["requirements"][0]["evidence"] = None
        extraction = RequirementExtraction.model_validate(body)
        with pytest.raises(AIResponseValidationError, match="evidence span"):
            validate_extraction(extraction, description=description)

    def test_evidence_that_is_not_in_the_posting_is_refused(
        self, description: str
    ) -> None:
        extraction = RequirementExtraction.model_validate(
            payload(evidence="Ten years building rockets for a living")
        )
        with pytest.raises(AIResponseValidationError, match="does not appear"):
            validate_extraction(extraction, description=description)

    def test_genuine_evidence_passes(self, description: str) -> None:
        extraction = RequirementExtraction.model_validate(payload())
        validate_extraction(extraction, description=description)  # no raise


# ---------------------------------------------------------------------------
# interpret()
# ---------------------------------------------------------------------------
class TestInterpret:
    def test_a_good_reading_comes_back_ai_attributed(
        self, description: str
    ) -> None:
        provider = FakeProvider(payload=payload())
        runs: list[ModelRun] = []
        result = interpret(description, provider=provider, run_sink=runs.append)
        assert result.used_ai is True
        assert result.provider == "fake"
        assert result.prompt_version == "ai-1:fake:fake-1"
        assert result.run_id
        assert result.requirements
        for requirement in result.requirements:
            assert requirement.extraction_source is ExtractionMethod.AI
        assert [run.status for run in runs] == [ModelRunStatus.SUCCESS]
        call = provider.calls[0]
        assert call["analysis_source"] is AnalysisSource.JOB_DATA
        assert call["task"] is ModelRunTask.EXTRACT
        assert call["system"]

    def test_a_rejected_reading_persists_a_failed_run_then_raises(
        self, description: str
    ) -> None:
        provider = FakeProvider(
            payload=payload(evidence="Invented span that appears nowhere")
        )
        runs: list[ModelRun] = []
        with pytest.raises(AIResponseValidationError) as exc:
            interpret(description, provider=provider, run_sink=runs.append)
        assert exc.value.details.get("run_id")
        assert [run.status for run in runs] == [ModelRunStatus.FAILED]
        assert runs[0].error

    def test_a_provider_failure_propagates_unchanged(self, description: str) -> None:
        provider = FakeProvider(error=ProviderUnavailableError("Ollama is not running"))
        with pytest.raises(ProviderUnavailableError):
            interpret(description, provider=provider)

    def test_the_prompt_version_tracks_provider_and_model(self) -> None:
        assert interpret_prompt_version("ollama", "qwen") == "ai-1:ollama:qwen"
        assert interpret_prompt_version("", None) == "ai-1:unknown:default"

    def test_error_codes_are_stable(self) -> None:
        assert error_code_for(ProviderUnavailableError("x")) == "PROVIDER_UNAVAILABLE"
        assert error_code_for(AIResponseValidationError("x")) == "RESPONSE_INVALID"
        assert error_code_for(AIProviderError("x")) == "AI_PROVIDER_ERROR"


# ---------------------------------------------------------------------------
# The service's AI path
# ---------------------------------------------------------------------------
class TestAnalyzeWithAI:
    def test_a_successful_model_reading_is_stored_and_cached(
        self, service, job
    ) -> None:
        provider = FakeProvider(payload=payload())
        first = service.analyze(job.id, ai=True, provider=provider)
        assert first.ai_fallback is False
        assert first.cached is False
        assert first.requirements
        assert all(
            r.extraction_source is ExtractionMethod.AI for r in first.requirements
        )
        assert service._model_runs.count() == 1

        second = service.analyze(job.id, ai=True, provider=provider)
        assert second.cached is True
        # The cache answered without waking the model a second time.
        assert len(provider.calls) == 1
        # Same readings (ids differ only because the stored rows carry them).
        assert [r.text for r in second.requirements] == [
            r.text for r in first.requirements
        ]
        assert all(
            r.extraction_source is ExtractionMethod.AI for r in second.requirements
        )

    def test_a_provider_failure_falls_back_and_records_the_attempt(
        self, service, job
    ) -> None:
        provider = FakeProvider(error=ProviderUnavailableError("not running"))
        outcome = service.analyze(job.id, ai=True, provider=provider)
        assert outcome.ai_fallback is True
        assert outcome.ai_error_code == "PROVIDER_UNAVAILABLE"
        assert outcome.requirements  # deterministic extraction still ran
        assert all(
            r.extraction_source is ExtractionMethod.DETERMINISTIC
            for r in outcome.requirements
        )

        # The failed attempt never became a cache hit: the next call
        # retries the model rather than serving the fallback as its result.
        again = service.analyze(job.id, ai=True, provider=provider)
        assert len(provider.calls) == 2
        assert again.ai_fallback is True

    def test_a_rejected_response_falls_back_and_keeps_the_failed_run(
        self, service, job
    ) -> None:
        provider = FakeProvider(payload=payload(evidence="nowhere to be found"))
        outcome = service.analyze(job.id, ai=True, provider=provider)
        assert outcome.ai_fallback is True
        assert outcome.ai_error_code == "RESPONSE_INVALID"
        assert service._model_runs.count() == 1
        stored = next(
            row for row in service._model_runs.by_task(ModelRunTask.EXTRACT)
        )
        assert stored["status"] == ModelRunStatus.FAILED.value

    def test_ai_without_a_provider_is_refused(self, service, job) -> None:
        with pytest.raises(ConfigurationError, match="without a provider"):
            service.analyze(job.id, ai=True)

    def test_ai_on_a_job_with_no_description_is_refused(self, service) -> None:
        job_id, _ = service.save(Job(source="fixture", title="Role With No JD"))
        with pytest.raises(JobExtractionError) as exc:
            service.analyze(job_id, ai=True, provider=FakeProvider(payload=payload()))
        assert exc.value.details.get("error_code") == "JD_NOT_FOUND"

    def test_the_offline_path_touches_no_model(self, service, job) -> None:
        outcome = service.analyze(job.id)
        assert outcome.ai_fallback is False
        assert outcome.requirements
        assert service._model_runs.count() == 0
