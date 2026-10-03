"""Source records, normalisation, and the read-only boundary.

The pipeline's contract: whatever a source says arrives as a
:class:`SourceJobRecord`, becomes exactly one shape of :class:`Job`, and
carries its provenance with it. The boundary contract: discovery actions
pass, application actions fail closed — before anyone can wire an
apply flow through the source layer by accident.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from core.enums import RetrievalMethod, SourceAdapterStatus, SourceMode
from core.errors import ApplicationBoundaryError, ConfigurationError
from jobs.models import JobStatus
from jobs.records import (
    PROVENANCE_KEY,
    JobNormalizer,
    RetrievalInfo,
    SourceJobRecord,
    enforce_source_mode,
)


def make_record(**overrides) -> SourceJobRecord:
    base = dict(
        source="linkedin",
        source_job_id="4001",
        url="https://www.linkedin.com/jobs/view/4001",
        canonical_url="https://www.linkedin.com/jobs/view/4001",
        title="Senior Python Engineer",
        company="Acme Analytics",
        location="Bengaluru",
        workplace_type="Remote",
        employment_type="Full-time",
        description_text="We need a senior Python engineer. " * 30,
        retrieval=RetrievalInfo(
            method=RetrievalMethod.BROWSER_FETCH,
            status=SourceAdapterStatus.OK,
            source_url="https://www.linkedin.com/jobs/view/4001",
        ),
    )
    base.update(overrides)
    return SourceJobRecord(**base)


class TestNormalization:
    def test_a_full_record_becomes_a_normalized_job(self) -> None:
        job = JobNormalizer().normalize(make_record())
        assert job.title == "Senior Python Engineer"
        assert job.company == "Acme Analytics"
        assert job.external_job_id == "4001"
        assert job.source == "linkedin"
        assert job.status is JobStatus.NORMALIZED
        assert job.employment_type == "Full-time"

    def test_a_record_without_a_description_stays_discovered(self) -> None:
        job = JobNormalizer().normalize(make_record(description_text=""))
        assert job.status is JobStatus.DISCOVERED
        assert job.description_text is None
        assert job.has_description() is False

    def test_provenance_travels_with_the_job(self) -> None:
        job = JobNormalizer().normalize(make_record())
        provenance = job.metadata[PROVENANCE_KEY]
        assert provenance["source"] == "linkedin"
        assert provenance["source_job_id"] == "4001"
        assert provenance["retrieval_method"] == "BROWSER_FETCH"
        assert provenance["retrieval_status"] == "OK"
        assert provenance["retrieved_at"].startswith(datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"))

    def test_normalization_is_deterministic(self) -> None:
        first = JobNormalizer().normalize(make_record(retrieval=RetrievalInfo(
            retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            method=RetrievalMethod.SAVED_PAGE,
        )))
        second = JobNormalizer().normalize(make_record(retrieval=RetrievalInfo(
            retrieved_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
            method=RetrievalMethod.SAVED_PAGE,
        )))
        assert first.model_dump(
            exclude={"discovered_at", "first_seen_at", "last_seen_at"}
        ) == second.model_dump(exclude={"discovered_at", "first_seen_at", "last_seen_at"})

    def test_a_record_with_no_title_is_refused(self) -> None:
        with pytest.raises(ValueError, match="no title"):
            JobNormalizer().normalize(make_record(title="   "))

    def test_saved_page_provenance_records_the_method(self) -> None:
        record = make_record(
            retrieval=RetrievalInfo(
                method=RetrievalMethod.SAVED_PAGE,
                source_url="C:/pages/job_detail.html",
            )
        )
        job = JobNormalizer().normalize(record)
        assert job.metadata[PROVENANCE_KEY]["retrieval_method"] == "SAVED_PAGE"
        assert job.metadata[PROVENANCE_KEY]["source_url"] == "C:/pages/job_detail.html"


class TestRetrievalRefusesSecrets:
    @pytest.mark.parametrize(
        "url",
        [
            "https://x.test/j?password=hunter2",
            "https://x.test/j?pwd=1234",
            "https://x.test/j?li_at=AQEDAR",
            "https://x.test/j?apikey=abc",
            "https://x.test/j?sessionid=deadbeef",
        ],
    )
    def test_credentials_in_a_url_are_refused(self, url: str) -> None:
        with pytest.raises(ValueError, match="credentials"):
            RetrievalInfo(source_url=url)

    def test_credentials_in_detail_are_refused(self) -> None:
        with pytest.raises(ValueError, match="credentials"):
            RetrievalInfo(detail="li_at=AQEDAR; path=/jobs")

    def test_ordinary_urls_pass(self) -> None:
        info = RetrievalInfo(source_url="https://www.linkedin.com/jobs/view/123")
        assert info.status is SourceAdapterStatus.OK


class TestSourceModeBoundary:
    @pytest.mark.parametrize(
        "action",
        ["DISCOVER", "FETCH", "PARSE", "NORMALIZE", "PERSIST", "READ", "discover"],
    )
    def test_discovery_actions_are_permitted(self, action: str) -> None:
        enforce_source_mode(SourceMode.DISCOVERY_ONLY, action)

    @pytest.mark.parametrize(
        "action",
        ["APPLY", "SUBMIT", "SUBMIT_APPLICATION", "FILL_FORM", "ACCEPT_DECLARATION", "UPLOAD_RESUME"],
    )
    def test_application_actions_fail_closed(self, action: str) -> None:
        with pytest.raises(ApplicationBoundaryError) as exc:
            enforce_source_mode(SourceMode.DISCOVERY_ONLY, action)
        assert exc.value.details["mode"] == "DISCOVERY_ONLY"
        assert exc.value.details["action"] == action

    def test_case_does_not_matter(self) -> None:
        with pytest.raises(ApplicationBoundaryError):
            enforce_source_mode(SourceMode.DISCOVERY_ONLY, "submit_application")

    def test_an_unrecognised_action_also_fails_closed(self) -> None:
        with pytest.raises(ApplicationBoundaryError, match="unrecognised"):
            enforce_source_mode(SourceMode.DISCOVERY_ONLY, "WIBBLE")

    def test_no_mode_permits_application(self) -> None:
        assert SourceMode.DISCOVERY_ONLY.allows_application is False

    def test_the_normalizer_enforces_the_mode_it_was_built_with(self) -> None:
        normalizer = JobNormalizer(mode=SourceMode.DISCOVERY_ONLY)
        # Normalisation itself is a discovery action and must pass...
        job = normalizer.normalize(make_record())
        assert job.title
        # ...and the boundary is reachable from the pipeline's own objects.
        with pytest.raises(ApplicationBoundaryError):
            enforce_source_mode(normalizer.mode, "CLICK_SUBMIT")


class TestSettingsEnforceDiscoveryOnly:
    def test_source_mode_defaults_to_discovery_only(self) -> None:
        from core.settings import JobSearchSettings

        assert JobSearchSettings().source_mode is SourceMode.DISCOVERY_ONLY

    def test_a_hypothetical_application_mode_is_refused_at_startup(self) -> None:
        from core.settings import AssistantSettings

        settings = AssistantSettings()
        # Simulate a future mode that claims to allow application. The enum
        # refuses such a value at validation time, so the guard is reached
        # here by writing past validation (test-only) to prove the startup
        # check itself works.
        class _ApplicationMode:
            value = "LIVE"

            @property
            def allows_application(self) -> bool:
                return True

        settings.job_search.__dict__["source_mode"] = _ApplicationMode()
        with pytest.raises(ConfigurationError, match="application execution"):
            settings.assert_consistent()

    def test_normal_settings_pass_assert_consistent(self) -> None:
        from core.settings import AssistantSettings

        AssistantSettings().assert_consistent()
