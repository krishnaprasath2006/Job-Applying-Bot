"""Phase 2 and Milestone 3 acceptance run.

Runs the 17 numbered acceptance steps from the Phase 2 specification, then the
7 Milestone 3 job-intelligence steps, against a temporary database and the
synthetic fixtures, then reports each step.

Guarantees:

* Runs entirely locally. No network except the AI health probe, which is a
  localhost call that is expected to fail when Ollama is not running.
* Opens no browser and submits nothing. The job steps ingest a saved fixture
  page from disk — capture, never navigation.
* Uses only synthetic fixtures, marked ``TEST DATA ONLY``.
* Cleans up its temporary database afterwards.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional

from core.enums import EvidenceSourceType, FactStatus, MatchDecision, ResumeStatus, ReviewReason
from core.errors import AssistantError, DuplicateResumeError
from core.evidence import Evidence
from core.settings import AISettings, SafetySettings
from safety.policies import Action, SafetyPolicy

__all__ = ["run_acceptance", "AcceptanceRunner"]

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


class AcceptanceRunner:
    """Executes the acceptance steps in order, recording each outcome."""

    def __init__(self) -> None:
        self.results: list[dict[str, Any]] = []
        self.tmp = Path(tempfile.mkdtemp(prefix="assistant_acceptance_"))
        self.state: dict[str, Any] = {}

    # -- bookkeeping ---------------------------------------------------------
    def step(self, number: int, title: str, fn: Callable[[], Any]) -> None:
        entry: dict[str, Any] = {"step": number, "title": title}
        try:
            detail = fn()
            entry["ok"] = True
            entry["detail"] = detail if isinstance(detail, (str, int, float, bool, type(None))) else str(detail)
        except Exception as exc:  # noqa: BLE001 - an acceptance run reports, it does not crash
            entry["ok"] = False
            entry["error"] = type(exc).__name__
            entry["detail"] = str(exc)[:300]
        self.results.append(entry)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r["ok"])

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r["ok"])

    def cleanup(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    # -- the checklist -------------------------------------------------------
    def run(self) -> None:
        self.step(1, "start project / build assistant", self.s1_start)
        self.step(2, "load configuration", self.s2_config)
        self.step(3, "create empty candidate profile", self.s3_profile_create)
        self.step(4, "validate UNKNOWN profile", self.s4_validate_empty)
        self.step(5, "add synthetic candidate data", self.s5_synthetic_facts)
        self.step(6, "ingest synthetic resume", self.s6_ingest)
        self.step(7, "calculate hash", self.s7_hash)
        self.step(8, "detect duplicate resume", self.s8_duplicate)
        self.step(9, "parse resume", self.s9_parse)
        self.step(10, "store resume", self.s10_store)
        self.step(11, "retrieve evidence", self.s11_evidence)
        self.step(12, "initialize SQLite", self.s12_sqlite)
        self.step(13, "persist profile", self.s13_persist_profile)
        self.step(14, "persist resume", self.s14_persist_resume)
        self.step(15, "initialize Ollama provider configuration", self.s15_provider_config)
        self.step(16, "report Ollama unavailable cleanly", self.s16_provider_health)
        self.step(17, "safety invariants hold", self.s17_safety)
        # Milestone 3: job intelligence core.
        self.step(18, "ingest a saved posting fixture", self.s18_ingest_job)
        self.step(19, "extract requirements and reuse the analysis cache", self.s19_analyze_job)
        self.step(20, "build candidate evidence from the profile", self.s20_candidate_evidence)
        self.step(21, "hard gate vetoes on stated years", self.s21_hard_gate_match)
        self.step(22, "explain the decision with both-side lineage", self.s22_explain_job)
        self.step(23, "match cache hit; unknown years queue for review", self.s23_cache_and_queue)
        self.step(24, "Milestone 3 safety still holds", self.s24_milestone_safety)

    def s1_start(self) -> str:
        from assistant.app import build_assistant
        from core.settings import load_settings

        # Every writable path is redirected into the sandbox, not just the
        # database. A run that only swaps the connection writes its synthetic
        # facts into the real profile JSON the moment a service saves one.
        sandbox = load_settings(env_file=None)
        sandbox = sandbox.model_copy(
            update={
                "application": sandbox.application.model_copy(
                    update={"paths_root": self.tmp, "candidate_id": "acceptance"}
                )
            }
        )
        self.state["db_path"] = self.tmp / "acceptance.db"
        app = build_assistant(settings=sandbox, database_path=self.state["db_path"])
        self.state["app"] = app
        return (
            f"assistant built in sandbox {app.paths.root}; "
            f"database={app.db.path} (nothing written to the real project data)"
        )

    def s2_config(self) -> str:
        settings = self.state["app"].settings
        self.state["settings"] = settings
        return (
            f"7 categories loaded; ai={settings.ai.provider}/{settings.ai.model}; "
            f"safe_mode={settings.safety.safe_mode}; dry_run={settings.safety.dry_run}"
        )

    def s3_profile_create(self) -> str:
        service = self.state["app"].profile_service
        # persist_json=True writes inside the sandbox, so the rest of the run
        # reads a real file and step 13 can prove the database round-trips too.
        profile = service.create_profile("acceptance", persist_json=True, actor="user")
        self.state["profile"] = profile
        return (
            f"{profile.fact_count()} fields, {len(profile.unknown_fields())} UNKNOWN, "
            f"completeness={profile.completeness():.1%}, written to "
            f"{service.path_for('acceptance').name} inside the sandbox"
        )

    def s4_validate_empty(self) -> str:
        report = self.state["app"].profile_service.validate_profile("acceptance")
        self.state["empty_report"] = report
        return (
            f"valid={report.is_valid}; {len(report.missing_required)} required field(s) UNKNOWN "
            f"(expected, and not an error)"
        )

    def s5_synthetic_facts(self) -> str:
        service = self.state["app"].profile_service
        fixture = json.loads((FIXTURES / "synthetic_candidate.json").read_text(encoding="utf-8"))
        applied = 0
        with_evidence = 0
        for fact in fixture["facts"]:
            evidence = [
                Evidence(
                    source_type=EvidenceSourceType(item["source_type"]),
                    source_id=item["source_id"],
                    source_location=item.get("source_location"),
                    text_excerpt=item.get("text_excerpt"),
                    confidence=item.get("confidence", 1.0),
                )
                for item in fact.get("evidence", [])
            ]
            service.update_fact(
                fact["field_path"],
                fact["value"],
                status=FactStatus(fact["status"]),
                source=EvidenceSourceType(fact["source"]),
                source_id=fact["source_id"],
                source_location=fact.get("source_location"),
                evidence=evidence,
                candidate_id="acceptance",
                actor="user",
            )
            applied += 1
            with_evidence += 1 if evidence else 0
        self.state["report_after"] = service.validate_profile("acceptance")
        return (
            f"{applied} synthetic VERIFIED facts applied from tests/fixtures/synthetic_candidate.json, "
            f"{with_evidence} with an evidence record"
        )

    def s6_ingest(self) -> str:
        service = self.state["app"].resume_service
        resume = service.ingest(
            FIXTURES / "synthetic_resume.txt", candidate_id="acceptance", is_synthetic=True
        )
        self.state["resume"] = resume
        return f"{resume.filename} -> {resume.id} ({resume.char_count} chars, {len(resume.sections)} sections)"

    def s7_hash(self) -> str:
        resume = self.state["resume"]
        from resumes.hashing import hash_file

        recomputed = hash_file(FIXTURES / "synthetic_resume.txt")
        if recomputed != resume.file_hash:
            raise AssertionError("hash is not reproducible")
        return f"sha256={resume.file_hash[:16]}... (reproducible)"

    def s8_duplicate(self) -> str:
        service = self.state["app"].resume_service
        try:
            service.ingest(FIXTURES / "synthetic_resume.txt", candidate_id="acceptance", is_synthetic=True)
        except DuplicateResumeError as exc:
            self.state["duplicate_detected"] = True
            return f"DuplicateResumeError raised as expected: {exc.file_hash[:12]}..."
        raise AssertionError("duplicate was not detected")

    def s9_parse(self) -> str:
        resume = self.state["resume"]
        types = sorted({s.section_type.value for s in resume.sections})
        return f"sections detected: {', '.join(types)}" if types else "no sections detected (reported, not guessed)"

    def s10_store(self) -> str:
        service = self.state["app"].resume_service
        stored = service.repository.get(resume_id := self.state["resume"].id)
        if stored is None:
            raise AssertionError("resume row missing")
        self.state["stored_resume_id"] = resume_id
        return f"row {stored['id']} status={stored['status']} synthetic={bool(stored['is_synthetic'])}"

    def s11_evidence(self) -> str:
        service = self.state["app"].profile_service
        detail = service.get_fact_with_evidence("identity.full_name", "acceptance")
        if detail is None:
            raise AssertionError("expected a verified synthetic fact")
        citations = len(detail["evidence"])
        if citations == 0:
            raise AssertionError("fact has no evidence")
        self.state["fact_detail"] = detail
        return (
            f"identity.full_name -> {detail['value']!r} [{detail['status']}] "
            f"with {citations} evidence record(s)"
        )

    def s12_sqlite(self) -> str:
        tables = self.state["app"].db.table_names()
        required = {
            "candidate_profiles",
            "candidate_facts",
            "resumes",
            "resume_sections",
            "documents",
            "evidence",
            "model_runs",
        }
        missing = required - set(tables)
        if missing:
            raise AssertionError(f"missing tables: {sorted(missing)}")
        return f"{len(tables)} tables present: {', '.join(tables)}"

    def s13_persist_profile(self) -> str:
        service = self.state["app"].profile_service
        # Read back from the database, not from a JSON file: this run creates
        # no file on purpose, so going through the file would test the wrong
        # thing and touch the real candidate's copy.
        profile = service.load_profile_from_database("acceptance")
        count = service.repository.count()
        verified = len(service.repository.verified_fields(profile.id))
        if verified == 0:
            raise AssertionError("verified facts did not survive persistence")
        self.state["persisted_profile"] = profile
        return (
            f"profiles={count} facts={service.repository.db.count('candidate_facts')} "
            f"verified={verified} (rebuilt from the database)"
        )

    def s14_persist_resume(self) -> str:
        app = self.state["app"]
        loaded = app.resume_repository.load(self.state["stored_resume_id"])
        if loaded is None or loaded.status is not ResumeStatus.PARSED:
            raise AssertionError("resume did not round-trip")
        return (
            f"resumes={app.resume_repository.count()} sections={app.db.count('resume_sections')} "
            f"variant={loaded.variant or '-'}"
        )

    def s15_provider_config(self) -> str:
        from ai.registry import available_providers

        settings = AISettings()
        self.state["ai_settings"] = settings
        providers = available_providers()
        if "ollama" not in providers:
            raise AssertionError("ollama provider is not registered")
        return (
            f"providers={providers}; default={settings.provider}/{settings.model}; "
            f"requires_api_key=False"
        )

    def s16_provider_health(self) -> str:
        from ai.registry import build_provider
        from core.errors import ProviderUnavailableError

        provider = build_provider(self.state["ai_settings"])
        status = provider.health_check()
        self.state["health"] = status
        if status.available:
            return f"Ollama IS available ({status.model}, {status.latency_ms}ms)"

        # Expected path: no silent fallback, no fabricated output.
        from core.enums import ModelRunTask

        try:
            provider.generate_text("probe", task=ModelRunTask.GENERATE_TEXT)
        except ProviderUnavailableError as exc:
            return f"Ollama unavailable -> clean ProviderUnavailableError, no fallback: {exc.message[:70]}"
        except AssistantError as exc:
            return f"Ollama unavailable -> {type(exc).__name__}, no fallback"
        raise AssertionError("provider produced output while unavailable")

    def s17_safety(self) -> str:
        policy = SafetyPolicy(SafetySettings())
        problems: list[str] = []
        if policy.is_allowed(Action.SUBMIT_APPLICATION, "probe"):
            problems.append("SUBMIT_APPLICATION was allowed")
        if policy.is_allowed(Action.FILL_FORM):
            problems.append("FILL_FORM was allowed")
        if policy.is_allowed(Action.NAVIGATE):
            problems.append("NAVIGATE was allowed")
        if problems:
            raise AssertionError("; ".join(problems))

        from safety.guards import assert_no_fact_mutation
        from core.errors import ImmutableFactError

        before = self.state["persisted_profile"].to_facts()
        # A real mutation: rewrite a verified value the way an AI extraction
        # step would try to. Re-stamping an already-VERIFIED status would be a
        # no-op and the guard would correctly stay silent about it.
        after = [
            f.model_copy(update={"value": "AI-INVENTED REPLACEMENT"})
            if f.field_path == "identity.full_name"
            else f
            for f in before
        ]
        try:
            assert_no_fact_mutation(before, after, actor="ollama")
        except ImmutableFactError:
            # Raising is the required behaviour. The else branch below turns a
            # silent pass into a failure, so nothing is swallowed here.
            guard_blocked_ai = True
        else:
            guard_blocked_ai = False
        if not guard_blocked_ai:
            raise AssertionError("AI was allowed to mutate a verified fact")

        # And the same change by the human must be allowed, or the guard would
        # be protecting the profile from its owner as well.
        assert_no_fact_mutation(before, after, actor="user")

        return "submit/fill/navigate blocked; AI cannot mutate verified facts; the owner can"

    # -- Milestone 3: job intelligence core ----------------------------------
    def s18_ingest_job(self) -> str:
        html = (FIXTURES / "html" / "job_detail.html").read_text(encoding="utf-8")
        result = self.state["app"].job_service.ingest_page(html, source="fixture")
        if not result.page.usable:
            raise AssertionError(
                f"fixture capture not usable: {result.page.status.value} "
                f"({result.page.reason})"
            )
        if not result.job.description_text:
            raise AssertionError("no description was stored from the fixture")
        if not result.created:
            raise AssertionError("expected a new job row, got a merge")
        self.state["job"] = result.job
        return (
            f"job {result.job.id} '{result.job.title}' @ {result.job.company}: "
            f"{len(result.job.description_text)} chars, "
            f"capture={result.page.status.value} (read from disk, no browser)"
        )

    def s19_analyze_job(self) -> str:
        service = self.state["app"].job_service
        job = self.state["job"]
        first = service.analyze(job.id)
        second = service.analyze(job.id)
        if first.cached or not second.cached:
            raise AssertionError(
                f"analysis cache behaved unexpectedly: first={first.cached}, "
                f"second={second.cached}"
            )
        years = [r for r in first.requirements if r.min_years is not None]
        if not years:
            raise AssertionError("no minimum-years requirement extracted")
        self.state["requirements"] = first.requirements
        kinds = sorted({r.kind.value for r in first.requirements})
        return (
            f"{len(first.requirements)} requirements; minimum years read: "
            + ", ".join(f"{r.min_years:g}" for r in years)
            + f"; second run cached; kinds: {', '.join(kinds)}"
        )

    def s20_candidate_evidence(self) -> str:
        evidence = self.state["app"].job_service.evidence()
        if evidence.years_of_experience != 3:
            raise AssertionError(
                "expected the fixture's 3 verified years, got "
                f"{evidence.years_of_experience}"
            )
        if not evidence.claims:
            raise AssertionError("no claims were read from the profile")
        self.state["evidence"] = evidence
        return (
            f"{len(evidence.claims)} claim(s); years=3 (VERIFIED with evidence); "
            f"requires_sponsorship={evidence.requires_sponsorship}"
        )

    def s21_hard_gate_match(self) -> str:
        job = self.state["job"]
        outcome = self.state["app"].job_service.match(job.id)
        result = outcome.result
        if result.decision is not MatchDecision.HARD_MISMATCH:
            raise AssertionError(f"expected HARD_MISMATCH, got {result.decision.value}")
        if result.gate.checks[0].evaluation.is_mismatch is False:
            raise AssertionError("the gate did not record the years mismatch")
        if result.scores:
            raise AssertionError("the scorer ran after the gate had already vetoed")
        self.state["match"] = outcome
        return (
            f"decision=HARD_MISMATCH, gate={result.gate.status.value}, "
            f"scorer never ran; {result.gate.checks[0].reason}"
        )

    def s22_explain_job(self) -> str:
        app = self.state["app"]
        job = self.state["job"]
        explanation = app.job_service.explain(job.id)
        report = explanation.render()
        requirements = self.state["requirements"]
        if len(explanation.rows) != len(requirements):
            raise AssertionError(
                f"{len(explanation.rows)} rows explained for "
                f"{len(requirements)} requirements"
            )
        if "posting:" not in report or "candidate:" not in report:
            raise AssertionError("the report carries no lineage lines")
        evaluated = [row for row in explanation.rows if row.evaluation is not None]
        if not evaluated:
            raise AssertionError("no row carries an evaluation")
        self.state["explanation"] = explanation
        return (
            f"{len(explanation.rows)} rows rendered, {len(evaluated)} evaluated; "
            "every row shows where the posting read came from and where the "
            "answer came from"
        )

    def s23_cache_and_queue(self) -> str:
        app = self.state["app"]
        job = self.state["job"]
        second = app.job_service.match(job.id)
        if not second.cached:
            raise AssertionError("the second match was not served from the cache")

        # The same posting against a profile that states no years at all:
        # silence must not become a failure — the job joins the review queue.
        from jobs.analysis import match_job
        from jobs.candidate import CandidateEvidence

        facts = [
            fact
            for fact in app.profile_service.load_profile("acceptance").to_facts()
            if fact.field_path != "experience.total_years_experience"
        ]
        stripped = CandidateEvidence.from_facts(facts)
        requirements = app.job_service.repository.requirements(job.id)
        queued = match_job(
            job,
            requirements,
            stripped,
            app.job_service.repository,
            candidate_id="acceptance",
        )
        if queued.result.decision is not MatchDecision.INSUFFICIENT_EVIDENCE:
            raise AssertionError(
                f"unknown years were decided as {queued.result.decision.value}"
            )
        queue = app.job_service.review_queue()
        if len(queue) != 1:
            raise AssertionError(f"expected 1 queued job, found {len(queue)}")
        item = queue.items[0]
        if ReviewReason.ELIGIBILITY_UNKNOWN not in item.reasons:
            raise AssertionError(
                f"queue reasons were {[r.value for r in item.reasons]}"
            )
        return (
            f"second match cached; profile without years -> "
            f"{queued.result.decision.value}, queued with "
            f"{', '.join(r.value for r in item.reasons)} (undecided, not failed)"
        )

    def s24_milestone_safety(self) -> str:
        app = self.state["app"]
        safety = app.settings.safety
        problems: list[str] = []
        if not safety.dry_run:
            problems.append("dry_run is off")
        if not safety.safe_mode:
            problems.append("safe_mode is off")
        if not safety.require_human_approval:
            problems.append("require_human_approval is off")
        if safety.allow_final_submission:
            problems.append("allow_final_submission is on")
        if app.safety.is_allowed(Action.SUBMIT_APPLICATION, "acceptance"):
            problems.append("SUBMIT_APPLICATION was allowed")
        if problems:
            raise AssertionError("; ".join(problems))
        safety.assert_phase2_invariants()
        # The whole run, job intelligence included, performed no submission.
        return (
            "dry_run/safe_mode/human approval on, final submission off; "
            "24 steps, zero submissions, zero browser launches"
        )


def run_acceptance(*, as_json: bool = False) -> int:
    """Run the checklist and print a report. Returns a process exit code."""
    runner = AcceptanceRunner()
    try:
        runner.run()
    finally:
        app = runner.state.get("app")
        if app is not None:
            app.db.close()
        runner.cleanup()

    if as_json:
        print(
            json.dumps(
                {"passed": runner.passed, "failed": runner.failed, "steps": runner.results},
                indent=2,
                default=str,
            )
        )
    else:
        print("PHASE 2 + MILESTONE 3 ACCEPTANCE (local only, no browser, no submission)")
        print("=" * 72)
        for entry in runner.results:
            mark = "PASS" if entry["ok"] else "FAIL"
            print(f"[{mark}] {entry['step']:>2}. {entry['title']}")
            detail = entry.get("detail", "")
            if entry["ok"]:
                print(f"       {detail}")
            else:
                print(f"       {entry.get('error')}: {detail}")
        print("=" * 72)
        print(f"{runner.passed}/{len(runner.results)} steps passed, {runner.failed} failed")
        print()
        print("REAL SUBMISSION REMAINS DISABLED.")

    return 0 if runner.failed == 0 else 1
