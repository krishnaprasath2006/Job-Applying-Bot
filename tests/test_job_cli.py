"""The ``job`` CLI: local pages in, verdicts out, no browser anywhere.

Every command runs through ``main()`` against a sandboxed database, so what
is asserted here is what a user would actually see — including the line
that says no application was started.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from assistant.cli import main
from core.enums import EvidenceSourceType, FactStatus
from core.evidence import Evidence


@pytest.fixture()
def sandbox(tmp_path: Path, monkeypatch):
    """A CLI wired to a temporary database and profile directory."""
    import assistant.cli as cli
    from assistant.app import build_assistant
    from core.settings import load_settings

    settings = load_settings(env_file=None)
    settings = settings.model_copy(
        update={
            "application": settings.application.model_copy(
                update={"paths_root": tmp_path, "candidate_id": "primary"}
            )
        }
    )

    def factory(args):
        return build_assistant(
            settings=settings, database_path=tmp_path / "cli.db"
        )

    monkeypatch.setattr(cli, "_assistant", factory)

    # A profile stating three verified years: enough for ``job match`` to
    # reach the gate against the fixture's five-year requirement.
    app = factory(None)
    try:
        profiles = app.profile_service
        profiles.create_profile("primary", persist_json=True, actor="user")
        profiles.update_fact(
            "experience.total_years_experience",
            3,
            status=FactStatus.VERIFIED,
            source=EvidenceSourceType.RESUME,
            source_id="resume.txt",
            evidence=[
                Evidence(
                    source_type=EvidenceSourceType.RESUME,
                    source_id="resume.txt",
                    text_excerpt="SYNTHETIC: 3 years",
                )
            ],
            candidate_id="primary",
            actor="user",
        )
    finally:
        app.close()
    return tmp_path


def fixture_page(fixtures_dir: Path) -> Path:
    return fixtures_dir / "html" / "job_detail.html"


def ingest_via_cli(capsys, fixtures_dir: Path) -> str:
    code = main(["job", "ingest", str(fixture_page(fixtures_dir))])
    assert code == 0
    match = re.search(r"Ingested job (\S+)", capsys.readouterr().out)
    assert match, "the ingest command did not name the job id"
    return match.group(1)


class TestJobListAndShow:
    def test_an_empty_database_says_so_and_points_at_ingest(
        self, sandbox, capsys
    ) -> None:
        assert main(["job", "list"]) == 0
        out = capsys.readouterr().out
        assert "No jobs saved yet." in out
        assert "job ingest" in out

    def test_the_full_local_flow(self, sandbox, fixtures_dir, capsys) -> None:
        # ingest
        job_id = ingest_via_cli(capsys, fixtures_dir)

        # list
        assert main(["job", "list"]) == 0
        out = capsys.readouterr().out
        assert job_id in out
        assert "Senior Machine Learning Engineer" in out

        # show
        assert main(["job", "show", job_id]) == 0
        out = capsys.readouterr().out
        assert f"Job {job_id}" in out
        assert "requirements:" in out
        assert "latest match: none" in out

        # analyze twice: miss, then cache hit
        assert main(["job", "analyze", job_id]) == 0
        out = capsys.readouterr().out
        assert "requirements:" in out
        assert "(cache hit)" not in out
        assert main(["job", "analyze", job_id]) == 0
        assert "(cache hit)" in capsys.readouterr().out

        # match: the gate vetoes before scoring
        assert main(["job", "match", job_id]) == 0
        out = capsys.readouterr().out
        assert "HARD_MISMATCH" in out
        assert "no application was started or submitted" in out

        # explain
        assert main(["job", "explain", job_id]) == 0
        out = capsys.readouterr().out
        assert "HARD_MISMATCH" in out
        assert "posting:" in out
        assert "candidate:" in out
        assert "No application was started or submitted." in out

        # a vetoed job is decided, so the queue stays empty
        assert main(["job", "queue"]) == 0
        assert "Review queue is empty." in capsys.readouterr().out

    def test_show_json_is_machine_readable(self, sandbox, fixtures_dir, capsys) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        main(["job", "analyze", job_id])
        capsys.readouterr()
        assert main(["job", "show", job_id, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["id"] == job_id
        assert payload["requirements"] >= 1

    def test_analyze_json_reports_the_cache_flag(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        main(["job", "analyze", job_id, "--json"])
        first = json.loads(capsys.readouterr().out)
        assert first["cached"] is False
        main(["job", "analyze", job_id, "--json"])
        second = json.loads(capsys.readouterr().out)
        assert second["cached"] is True
        assert second["requirements"] == first["requirements"]

    def test_list_json_is_a_list(self, sandbox, fixtures_dir, capsys) -> None:
        ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "list", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert isinstance(payload, list)
        assert len(payload) == 1


class TestRefusals:
    def test_ingesting_a_missing_file_fails_cleanly(self, sandbox, capsys) -> None:
        code = main(["job", "ingest", str(Path("no/such/page.html"))])
        out = capsys.readouterr()
        assert code == 1
        assert "not a file" in out.err

    def test_showing_an_unknown_job_fails_cleanly(self, sandbox, capsys) -> None:
        code = main(["job", "show", "job-missing"])
        out = capsys.readouterr()
        assert code == 1
        assert "JobNotFoundError" in out.err

    def test_explaining_without_a_match_fails_cleanly(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        code = main(["job", "explain", job_id])
        out = capsys.readouterr()
        assert code == 1
        assert "JobNotFoundError" in out.err
        assert "run match first" in out.err


def open_cli_db(sandbox: Path):
    """The CLI's own database, for seeding rows the commands should read."""
    from database.connection import Database

    return Database(sandbox / "cli.db")


class TestQueueCommand:
    def test_a_queued_job_lists_with_its_reasons(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        from core.enums import AnalysisSource, HardGateStatus, MatchDecision
        from database.repositories.jobs import JobRepository

        job_id = ingest_via_cli(capsys, fixtures_dir)
        database = open_cli_db(sandbox)
        try:
            JobRepository(database).save_match(
                job_id=job_id,
                candidate_id="primary",
                decision=MatchDecision.INSUFFICIENT_EVIDENCE,
                hard_gate_status=HardGateStatus.UNKNOWN,
                analysis_source=AnalysisSource.JOB_DATA,
                requirements_fingerprint="fp-cli",
                candidate_fingerprint="cfp-cli",
                explanation={"decision": "INSUFFICIENT_EVIDENCE"},
                review_reasons=["ELIGIBILITY_UNKNOWN"],
            )
        finally:
            database.close()
        assert main(["job", "queue"]) == 0
        out = capsys.readouterr().out
        assert job_id in out
        assert "ELIGIBILITY_UNKNOWN" in out
        assert "waiting for a human" in out
        assert "undecided, not rejected" in out

    def test_queue_json_lists_items(self, sandbox, fixtures_dir, capsys) -> None:
        from core.enums import AnalysisSource, HardGateStatus, MatchDecision
        from database.repositories.jobs import JobRepository

        job_id = ingest_via_cli(capsys, fixtures_dir)
        database = open_cli_db(sandbox)
        try:
            JobRepository(database).save_match(
                job_id=job_id,
                candidate_id="primary",
                decision=MatchDecision.REVIEW_REQUIRED,
                hard_gate_status=HardGateStatus.PASS,
                analysis_source=AnalysisSource.JOB_DATA,
                requirements_fingerprint="fp-cli-2",
                candidate_fingerprint="cfp-cli-2",
                explanation={"decision": "REVIEW_REQUIRED"},
                review_reasons=["LOW_AI_CONFIDENCE"],
            )
        finally:
            database.close()
        assert main(["job", "queue", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert len(payload) == 1
        assert payload[0]["job_id"] == job_id
        assert payload[0]["reasons"] == ["LOW_AI_CONFIDENCE"]


class TestJobDiscoverCommand:
    """``job discover``: saved listing pages in, stored jobs out, offline."""

    @staticmethod
    def listing_file(fixtures_dir: Path) -> Path:
        return fixtures_dir / "html" / "search_results.html"

    def test_show_reports_where_a_job_came_from(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "show", job_id]) == 0
        out = capsys.readouterr().out
        assert "provenance:" in out
        assert "SAVED_PAGE/OK" in out
        # No --url was given, so the file the bytes came from is recorded.
        assert "job_detail.html" in out

    def test_show_json_carries_the_provenance_block(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "show", job_id, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        provenance = payload["provenance"]
        assert provenance["retrieval_method"] == "SAVED_PAGE"
        assert provenance["retrieval_status"] == "OK"
        assert provenance["source_url"].endswith("job_detail.html")

    def test_a_saved_listing_page_stores_its_jobs(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        code = main([
            "job", "discover", str(self.listing_file(fixtures_dir)),
            "--source", "fixture",
            "--url", "https://www.linkedin.com/jobs/search/?keywords=engineer",
        ])
        assert code == 0
        out = capsys.readouterr().out
        assert "3 job(s): 3 new, 0 merged [OK]" in out
        assert main(["job", "list"]) == 0
        out = capsys.readouterr().out
        assert "3 job(s)." in out

    def test_running_it_again_merges_instead_of_duplicating(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        args = ["job", "discover", str(self.listing_file(fixtures_dir)), "--source", "fixture"]
        assert main(args) == 0
        capsys.readouterr()
        assert main(args) == 0
        out = capsys.readouterr().out
        assert "0 new, 3 merged" in out
        assert main(["job", "list"]) == 0
        assert "3 job(s)." in capsys.readouterr().out

    def test_a_blocked_page_fails_loudly_with_its_code(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        blocked = fixtures_dir / "html" / "challenge.html"
        code = main(["job", "discover", str(blocked), "--source", "fixture"])
        captured = capsys.readouterr()
        assert code == 1
        assert "SOURCE_BLOCKED" in captured.out
        assert "did not yield a usable answer" in captured.err
        assert main(["job", "list"]) == 0
        assert "No jobs saved yet." in capsys.readouterr().out

    def test_a_directory_walks_every_page_in_it(
        self, sandbox, fixtures_dir, capsys, tmp_path
    ) -> None:
        pages = tmp_path / "pages"
        pages.mkdir()
        for name in ("search_results.html", "search_results_empty.html"):
            (pages / name).write_bytes((fixtures_dir / "html" / name).read_bytes())
        assert main(["job", "discover", str(pages), "--source", "fixture"]) == 0
        out = capsys.readouterr().out
        assert "across 2 page(s)." in out
        assert "3 new" in out

    def test_a_path_that_is_not_there_says_so(self, sandbox, capsys, tmp_path) -> None:
        code = main(["job", "discover", str(tmp_path / "nope.html")])
        assert code == 1
        assert "no readable pages" in capsys.readouterr().err


class TestJobAnalyzeAI:
    """``job analyze --ai``: a model reading, or an honest failure."""

    def test_a_down_provider_falls_back_and_names_the_code(
        self, sandbox, fixtures_dir, capsys, monkeypatch
    ) -> None:
        from assistant.app import Assistant
        from core.errors import ProviderUnavailableError

        class DownProvider:
            name = "down"
            model = "none"

            def generate_structured(self, *args, **kwargs):
                raise ProviderUnavailableError("Ollama is not running")

        monkeypatch.setattr(Assistant, "ai_provider", lambda self: DownProvider())
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "analyze", job_id, "--ai"]) == 0
        out = capsys.readouterr().out
        assert "ai: FAILED (PROVIDER_UNAVAILABLE)" in out
        assert "deterministic fallback" in out
        assert "requirements:" in out

    def test_a_working_model_reports_its_reading_stored(
        self, sandbox, fixtures_dir, capsys, monkeypatch
    ) -> None:
        from assistant.app import Assistant
        from test_job_interpret import FakeProvider, payload

        monkeypatch.setattr(
            Assistant, "ai_provider", lambda self: FakeProvider(payload=payload())
        )
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "analyze", job_id, "--ai"]) == 0
        out = capsys.readouterr().out
        assert "ai: model reading stored and validated" in out
        assert "5+ years" in out

    def test_json_reports_the_ai_verdict(
        self, sandbox, fixtures_dir, capsys, monkeypatch
    ) -> None:
        from assistant.app import Assistant
        from core.errors import ProviderUnavailableError

        class DownProvider:
            name = "down"
            model = "none"

            def generate_structured(self, *args, **kwargs):
                raise ProviderUnavailableError("not running")

        monkeypatch.setattr(Assistant, "ai_provider", lambda self: DownProvider())
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "analyze", job_id, "--ai", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["ai_attempted"] is True
        assert payload["ai_fallback"] is True
        assert payload["ai_error_code"] == "PROVIDER_UNAVAILABLE"

    def test_model_without_ai_is_refused(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        capsys.readouterr()
        assert main(["job", "analyze", job_id, "--model", "qwen"]) == 78
        assert "--model requires --ai" in capsys.readouterr().err

    def test_the_flags_parse(self) -> None:
        from assistant.cli import build_parser

        args = build_parser().parse_args(["job", "analyze", "job-1", "--ai", "--model", "m"])
        assert args.ai is True
        assert args.model == "m"
        assert build_parser().parse_args(["job", "analyze", "job-1"]).ai is False


class TestJobMatchScorer:
    """``job match --scorer``: which algorithm judged, said out loud."""

    def test_no_scorer_stays_the_default(self, sandbox, fixtures_dir, capsys) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "match", job_id, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["scorer"] == "none"
        assert payload["decision"] == "HARD_MISMATCH"

    def test_the_lexical_scorer_prints_its_identity(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "match", job_id, "--scorer", "lexical"]) == 0
        out = capsys.readouterr().out
        assert "scorer:     lexical (lexical:v1)" in out
        assert "no application was started" in out

    def test_the_json_payload_names_the_lexical_scorer(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "match", job_id, "--scorer", "lexical", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["scorer"] == "lexical"
        assert payload["cached"] is False

    def test_switching_scorers_recomputes_rather_than_replays(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "match", job_id, "--scorer", "lexical", "--json"]) == 0
        first = json.loads(capsys.readouterr().out)
        assert first["cached"] is False
        # Same scorer again: the verdict was stored under its key.
        assert main(["job", "match", job_id, "--scorer", "lexical", "--json"]) == 0
        second = json.loads(capsys.readouterr().out)
        assert second["cached"] is True

    def test_an_embedding_scorer_runs_and_files_its_model_run(
        self, sandbox, fixtures_dir, capsys, monkeypatch
    ) -> None:
        from types import SimpleNamespace

        from assistant.app import Assistant
        from core.enums import AnalysisSource, ModelRunTask
        from core.model_run import ModelRun

        class EmbedProvider:
            name = "fake-embed"
            model = "fake-embed-v1"
            supports_embeddings = True

            def embed(self, texts, *, model=None, prompt_version=""):
                return SimpleNamespace(
                    vectors=[[1.0, 0.0] for _ in texts],
                    model=model or "fake-embed-v1",
                    run=ModelRun(
                        provider="fake-embed",
                        model="fake-embed-v1",
                        task=ModelRunTask.EMBED,
                        input_hash="hash-of-the-texts",
                        analysis_source=AnalysisSource.AI_GENERAL,
                    ),
                )

        monkeypatch.setattr(Assistant, "ai_provider", lambda self: EmbedProvider())
        job_id = ingest_via_cli(capsys, fixtures_dir)

        # Prepare a profile that can actually reach the scorer: clear the
        # experience gate (a vetoed match never scores), and state a claim,
        # because rows with no claim to compare against stay unknown without
        # ever asking the scorer.
        import assistant.cli as cli

        app = cli._assistant(None)
        try:
            for path, value in (
                ("experience.total_years_experience", 10),
                ("skills.proficient", ["Python"]),
            ):
                app.profile_service.update_fact(
                    path,
                    value,
                    status=FactStatus.VERIFIED,
                    source=EvidenceSourceType.RESUME,
                    source_id="resume.txt",
                    evidence=[
                        Evidence(
                            source_type=EvidenceSourceType.RESUME,
                            source_id="resume.txt",
                            text_excerpt=f"SYNTHETIC: {path}",
                        )
                    ],
                    candidate_id="primary",
                    actor="user",
                )
        finally:
            app.close()

        assert main(["job", "match", job_id, "--scorer", "embedding", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["scorer"] == "embedding"
        assert payload["cached"] is False

        # The embeds the scorer performed were filed, not lost.
        app = cli._assistant(None)
        try:
            assert app.model_run_repository.count() >= 1
        finally:
            app.close()

    def test_a_provider_that_cannot_embed_is_refused_with_a_hint(
        self, sandbox, fixtures_dir, capsys, monkeypatch
    ) -> None:
        from assistant.app import Assistant

        class NoEmbedProvider:
            name = "no-embed"
            model = "chat-only"
            supports_embeddings = False

        monkeypatch.setattr(Assistant, "ai_provider", lambda self: NoEmbedProvider())
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "match", job_id, "--scorer", "embedding"]) == 78
        err = capsys.readouterr().err
        assert "does not support embeddings" in err
        assert "lexical" in err


class TestJobReportCommand:
    """``job report``: eleven dimensions, explained, nothing applied."""

    def test_the_text_report_prints_all_eleven_and_stops(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        from jobs.dimensions import DIMENSIONS

        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "report", job_id]) == 0
        out = capsys.readouterr().out
        assert f"Report for {job_id}" in out
        for name in DIMENSIONS:
            assert name in out, name
        assert "no application was started" in out

    def test_the_json_report_carries_every_dimension(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        from jobs.dimensions import DIMENSIONS

        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "report", job_id, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert list(payload["dimension_scores"]) == list(DIMENSIONS)
        assert payload["scorer"] == "none"
        assert payload["decision"] in {"MATCH", "PARTIAL_MATCH", "REVIEW_REQUIRED",
                                       "INSUFFICIENT_EVIDENCE", "HARD_MISMATCH"}
        assert len(payload["explanations"]) == len(DIMENSIONS)

    def test_the_report_accepts_a_scorer_flag(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "report", job_id, "--scorer", "lexical", "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["scorer"] == "lexical"


class TestJobRelevanceCommand:
    """``job relevance``: a recommendation from stored evidence, or none."""

    def test_an_empty_resume_store_says_so_and_stops(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "relevance", job_id]) == 0
        out = capsys.readouterr().out
        assert "INSUFFICIENT_EVIDENCE" in out
        assert "no resumes" in out
        assert "recommended: none" in out
        assert "no application was started" in out

    def test_the_json_payload_carries_the_decision(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "relevance", job_id, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["decision"] == "INSUFFICIENT_EVIDENCE"
        assert payload["recommended_resume_id"] is None
        assert payload["reason"]

    def test_a_stored_resume_covering_the_posting_is_recommended(
        self, sandbox, fixtures_dir, capsys
    ) -> None:
        resume_path = fixtures_dir / "synthetic_resume.txt"
        assert main(["resume", "ingest", str(resume_path)]) == 0
        capsys.readouterr()
        job_id = ingest_via_cli(capsys, fixtures_dir)
        assert main(["job", "relevance", job_id, "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["decision"] == "RECOMMENDED"
        assert payload["recommended_resume_id"]
        assert payload["scores"][0]["coverage"] > 0.0
        assert payload["reason"]


class TestParser:
    def test_the_job_group_is_registered(self) -> None:
        from assistant.cli import build_parser

        args = build_parser().parse_args(["job", "list"])
        assert args.command == "job"
        assert args.subcommand == "list"

    def test_every_job_subcommand_parses(self) -> None:
        from assistant.cli import build_parser

        parser = build_parser()
        assert parser.parse_args(["job", "ingest", "page.html"]).path == Path("page.html")
        assert parser.parse_args(["job", "show", "job-1"]).job_id == "job-1"
        assert parser.parse_args(["job", "analyze", "job-1"]).job_id == "job-1"
        assert parser.parse_args(["job", "match", "job-1"]).job_id == "job-1"
        assert parser.parse_args(["job", "report", "job-1"]).job_id == "job-1"
        assert parser.parse_args(["job", "relevance", "job-1"]).job_id == "job-1"
        assert parser.parse_args(["job", "explain", "job-1"]).job_id == "job-1"
        assert parser.parse_args(["job", "queue"]).subcommand == "queue"
        discovered = parser.parse_args(["job", "discover", "listing.html"])
        assert discovered.path == Path("listing.html")
        assert discovered.source == "local"
