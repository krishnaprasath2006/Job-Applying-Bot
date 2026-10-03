"""Command line interface.

Every command is local and read-mostly. Nothing here opens a browser, visits
LinkedIn, or submits anything. ``job`` runs the Milestone 3 intelligence
commands — ingest a saved page, extract requirements, match, explain, list the
review queue — all against a local database. ``acceptance`` runs the Phase 2
and Milestone 3 checklists end to end against a temporary database.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Optional

from core.enums import EvidenceSourceType, FactStatus
from core.errors import AssistantError, ConfigurationError
from core.logging_config import configure_logging
from core.redaction import REDACTOR
from assistant.app import Assistant, build_assistant

__all__ = ["main", "build_parser"]

_BANNER = "AI Job Assistant - Phase 2 foundation + Milestone 3 job intelligence (no browser, no submission)"


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def _assistant(args: argparse.Namespace) -> Assistant:
    configure_logging(level="ERROR", fmt="silent")
    return build_assistant(env_file=getattr(args, "env_file", None))


def _print(data: Any, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data, indent=2, default=str))
    elif isinstance(data, str):
        print(data)
    else:
        print(json.dumps(data, indent=2, default=str))


def _table(rows: list[tuple[str, ...]], headers: tuple[str, ...]) -> str:
    widths = [len(h) for h in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(str(cell)))
    lines = ["  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)).rstrip()]
    lines.append("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        lines.append("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)).rstrip())
    return "\n".join(lines)


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_status(args: argparse.Namespace) -> int:
    """Print system status: safety, paths, database, configuration."""
    with _assistant(args) as app:
        status = app.status()
        if args.json:
            _print(status, as_json=True)
            return 0

        print(_BANNER)
        print()
        print("SAFETY")
        for key, value in status["safety"].items():
            print(f"  {key}: {value}")
        print()
        print("DATABASE")
        db = status["database"]
        print(f"  path: {db['path']}")
        print(f"  tables: {', '.join(db['tables'])}")
        print(
            f"  rows: profiles={db['profiles']} resumes={db['resumes']} "
            f"evidence={db['evidence']} model_runs={db['model_runs']} "
            f"jobs={db['jobs']} queued={db['queued_for_review']} "
            f"open_reviews={db['open_reviews']}"
        )
        print()
        print("PATHS")
        for key, value in status["paths"].items():
            print(f"  {key}: {value}")
        print()
        print("CONFIGURATION (secrets redacted)")
        for section, values in status["configuration"].items():
            print(f"  {section}:")
            for key, value in values.items():
                print(f"    {key}: {value}")
    return 0


def cmd_safety(args: argparse.Namespace) -> int:
    """Report which privileged actions are currently permitted."""
    with _assistant(args) as app:
        print("SAFETY POLICY")
        print(f"  safe_mode              = {app.settings.safety.safe_mode}")
        print(f"  dry_run                = {app.settings.safety.dry_run}")
        print(f"  require_human_approval = {app.settings.safety.require_human_approval}")
        print()
        for action, allowed in app.safety.status()["actions"].items():
            reason = app.safety.check(_action(action))
            print(f"  {action:<22} allowed={allowed!s:<6} {reason or ''}")
        print()
        print("REAL SUBMISSION IS DISABLED.")
    return 0


def _action(name: str) -> Any:
    from safety.policies import Action

    return Action(name)


def cmd_profile_init(args: argparse.Namespace) -> int:
    """Create an empty, all-UNKNOWN candidate profile."""
    with _assistant(args) as app:
        if app.profile_service.profile_exists(args.candidate_id) and not args.force:
            print(f"a profile already exists for {args.candidate_id!r}; pass --force to replace it")
            return 1
        profile = app.profile_service.create_profile(args.candidate_id, actor="user")
        report = app.profile_service.validate_profile(args.candidate_id)
        print(f"Created profile {profile.id} for candidate {args.candidate_id!r}")
        print(f"  fields:  {profile.fact_count()}")
        print(f"  UNKNOWN: {len(profile.unknown_fields())}")
        print(f"  VERIFIED: {len(profile.verified_fields())}")
        print(f"  valid:   {report.is_valid} (missing {len(report.missing_required)} required field(s))")
        print(f"  written: {app.paths.candidate_profile}")
        print()
        print("No values were invented. Every field is UNKNOWN until you fill it in.")
    return 0


def cmd_profile_show(args: argparse.Namespace) -> int:
    """Print the profile's known and unknown fields."""
    with _assistant(args) as app:
        profile = app.profile_service.load_profile(args.candidate_id)
        if args.json:
            _print(json.loads(profile.to_json()), as_json=True)
            return 0

        print(f"Profile {profile.id}  candidate={profile.candidate_id}  v{profile.version}")
        print(f"  completeness: {profile.completeness():.1%}")
        print(f"  facts:        {profile.fact_count()}")
        print()
        print(_table(
            [
                (
                    path,
                    fact.status.value,
                    json.dumps(fact.value, default=str) if fact.value is not None else "-",
                    fact.source.value if fact.source else "-",
                )
                for path, fact, _section in profile.iter_fact_values()
                if args.all or fact.status is not FactStatus.UNKNOWN
            ]
            or [("-", "-", "-", "-")],
            ("FIELD", "STATUS", "VALUE", "SOURCE"),
        ))
        if not args.all:
            print()
            print(f"({len(profile.unknown_fields())} field(s) still UNKNOWN; use --all to list them)")
    return 0


def cmd_profile_unknown(args: argparse.Namespace) -> int:
    """List the fields still to be filled in."""
    with _assistant(args) as app:
        rows = app.profile_service.list_unknown_fields(args.candidate_id)
        if args.json:
            _print(rows, as_json=True)
            return 0
        print(f"{len(rows)} UNKNOWN field(s):")
        print(_table(
            [(r["field_path"], r["required_for_application"]) for r in rows],
            ("FIELD", "REQUIRED"),
        ))
    return 0


def cmd_profile_set(args: argparse.Namespace) -> int:
    """Set one fact on the profile."""
    with _assistant(args) as app:
        status = FactStatus[args.status.upper()]
        source = EvidenceSourceType[args.source.upper()] if args.source else None
        if status is FactStatus.VERIFIED and source is None:
            print("--source is required when setting a VERIFIED fact", file=sys.stderr)
            return 2
        profile = app.profile_service.update_fact(
            args.field,
            args.value,
            status=status,
            source=source,
            source_id=args.source_id,
            source_location=args.source_location,
            actor="user",
            candidate_id=args.candidate_id,
            validate=args.validate,
        )
        fact = next(f for p, f, _ in profile.iter_fact_values() if p == args.field)
        print(f"{args.field} = {fact.value!r} [{fact.status.value}]")
        if args.validate:
            report = app.profile_service.validate_profile(args.candidate_id)
            print(f"  valid: {report.is_valid}  completeness: {report.completeness:.1%}")
    return 0


def cmd_profile_validate(args: argparse.Namespace) -> int:
    """Validate the profile and report findings."""
    with _assistant(args) as app:
        report = app.profile_service.validate_profile(args.candidate_id)
        if args.json:
            _print(report.summary(), as_json=True)
            return 0 if report.is_valid else 1

        print(f"Profile: {report.profile_id}")
        print(f"  valid:        {report.is_valid}")
        print(f"  errors:       {len(report.errors)}")
        print(f"  warnings:     {len(report.warnings)}")
        print(f"  completeness: {report.completeness:.1%}")
        print()
        if report.missing_required:
            print(f"MISSING REQUIRED ({len(report.missing_required)}):")
            for path in report.missing_required:
                print(f"  {path}")
            print()
        if report.issues:
            print("FINDINGS:")
            for issue in report.issues:
                print(f"  {issue}")
        else:
            print("No findings.")
        print()
        print("The validator reports problems; it never fixes them.")
    return 0 if report.is_valid else 1


def cmd_resume_ingest(args: argparse.Namespace) -> int:
    """Ingest one or more resume files."""
    with _assistant(args) as app:
        service = app.resume_service
        if len(args.paths) > 1:
            result = service.ingest_many(
                args.paths, candidate_id=args.candidate_id, is_synthetic=args.synthetic
            )
            print(json.dumps(result, indent=2, default=str))
            return 0 if result["failed"] == 0 else 1

        path = args.paths[0]
        try:
            resume = service.ingest(
                path,
                variant=args.variant,
                candidate_id=args.candidate_id,
                is_synthetic=args.synthetic,
                allow_duplicate=args.allow_duplicate,
                role_focus=args.role_focus,
                skills=[s.strip() for s in args.skills.split(",") if s.strip()]
                if args.skills
                else None,
                version=args.version,
            )
        except AssistantError as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1

        print(f"Ingested {resume.filename}")
        print(f"  id:       {resume.id}")
        print(f"  hash:     {resume.file_hash[:16]}...")
        print(f"  type:     {resume.file_type.value}")
        print(f"  chars:    {resume.char_count}")
        print(f"  variant:  {resume.variant or '-'}")
        print(f"  focus:    {resume.role_focus or '-'}")
        print(f"  version:  {resume.version or '-'}")
        if resume.skills:
            print(f"  skills:   {', '.join(resume.skills)}")
        print(f"  original: {resume.storage_path}")
        print(f"  text:     {resume.raw_text_path}")
        print(f"  sections: {len(resume.sections)}")
        for section in resume.sections:
            print(f"    - {section.section_type.value:<16} {section.char_count:>5} chars  {section.heading or ''}")
        print()
        print("The original file was not modified.")
    return 0


def cmd_resume_list(args: argparse.Namespace) -> int:
    """List ingested resumes."""
    with _assistant(args) as app:
        rows = app.resume_service.list_resumes(args.candidate_id)
        if args.json:
            _print(rows, as_json=True)
            return 0
        if not rows:
            print("No resumes ingested yet.")
            return 0
        print(_table(
            [
                (
                    r["id"],
                    r["filename"],
                    r["file_type"],
                    r["variant"] or "-",
                    r["status"],
                    r["char_count"],
                    "yes" if r["is_synthetic"] else "no",
                )
                for r in rows
            ],
            ("ID", "FILENAME", "TYPE", "VARIANT", "STATUS", "CHARS", "SYNTH"),
        ))
        print()
        print(f"{len(rows)} resume(s); variants: {', '.join(app.resume_service.list_variants(args.candidate_id)) or '-'}")
    return 0


def cmd_resume_show(args: argparse.Namespace) -> int:
    """Print one resume's sections."""
    with _assistant(args) as app:
        resume = app.resume_service.get_resume(args.resume_id)
        if resume is None:
            print(f"resume not found: {args.resume_id}", file=sys.stderr)
            return 1
        if args.text:
            print(resume.all_text())
            return 0
        print(f"{resume.filename}  [{resume.id}]")
        print(f"  hash: {resume.file_hash}")
        print()
        for section in resume.sections:
            print(f"== {section.section_type.value} ({section.char_count} chars)")
            preview = (section.raw_text or "")[:400]
            print(preview)
            print()
    return 0


def cmd_db_init(args: argparse.Namespace) -> int:
    """Create or migrate the database."""
    with _assistant(args) as app:
        applied = app.db.initialize()
        print(f"database: {app.db.path}")
        print(f"applied:  {applied or 'already up to date'}")
        print(f"tables:   {', '.join(app.db.table_names())}")
    return 0


def cmd_db_tables(args: argparse.Namespace) -> int:
    """List tables and their columns."""
    with _assistant(args) as app:
        for table in app.db.table_names():
            columns = app.db.column_names(table)
            print(f"{table}  ({app.db.count(table)} rows)")
            print(f"  {', '.join(columns)}")
            print()
    return 0


def cmd_ai_health(args: argparse.Namespace) -> int:
    """Check whether the configured AI provider is reachable."""
    with _assistant(args) as app:
        provider = app.ai_provider()
        status = provider.health_check()
        print(f"provider: {status.provider}")
        print(f"model:    {status.model}")
        print(f"status:   {'AVAILABLE' if status.available else 'UNAVAILABLE'}")
        if status.detail:
            print(f"detail:   {status.detail}")
        if status.models_available:
            print(f"models:   {', '.join(status.models_available)}")
        if not status.available:
            print()
            print("The assistant will not substitute another provider or fabricate output.")
            print("Start Ollama with 'ollama serve', then pull the model:")
            print(f"  ollama pull {status.model}")
    return 0 if status.available else 1


def cmd_ai_models(args: argparse.Namespace) -> int:
    """List the models the local provider has."""
    with _assistant(args) as app:
        provider = app.ai_provider()
        try:
            models = provider.list_models()
        except AssistantError as exc:
            print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
        print("\n".join(models) if models else "no models pulled")
    return 0


def cmd_job_list(args: argparse.Namespace) -> int:
    """List saved jobs."""
    with _assistant(args) as app:
        jobs = app.job_service.list_jobs(limit=args.limit)
        if args.json:
            _print(
                [
                    {
                        "id": job.id,
                        "status": job.status.value,
                        "title": job.title,
                        "company": job.company,
                        "source": job.source,
                    }
                    for job in jobs
                ],
                as_json=True,
            )
            return 0
        if not jobs:
            print("No jobs saved yet.")
            print("Ingest a saved posting page:  job ingest path/to/page.html")
            return 0
        print(_table(
            [(job.id, job.status.value, job.title or "-", job.company or "-") for job in jobs],
            ("ID", "STATUS", "TITLE", "COMPANY"),
        ))
        print()
        print(f"{len(jobs)} job(s).")
    return 0


def cmd_job_discover(args: argparse.Namespace) -> int:
    """Discover jobs from saved listing page(s). Read-only: no browser."""
    with _assistant(args) as app:
        paths = _listing_files(args.path)
        if not paths:
            print(f"no readable pages at: {args.path}", file=sys.stderr)
            return 1
        failures = 0
        new_total = 0
        merged_total = 0
        for path in paths:
            html = path.read_text(encoding="utf-8", errors="replace")
            outcome = app.job_service.discover_listing(
                html,
                source=args.source,
                page_url=args.url or "",
                source_path=str(path),
            )
            result = outcome.result
            new_total += outcome.stored_count
            merged_total += outcome.merged_count
            counts = (
                f"{result.count} job(s): {outcome.stored_count} new, "
                f"{outcome.merged_count} merged"
            )
            line = f"{path.name}: {counts} [{result.status.value}]"
            if result.error_code:
                line += f" {result.error_code}"
            print(line)
            if result.reason:
                print(f"  reason: {result.reason}")
            if not result.ok:
                failures += 1
        print()
        print(f"{new_total} new, {merged_total} merged across {len(paths)} page(s).")
        if failures:
            print(
                f"{failures} page(s) did not yield a usable answer; "
                "see the codes above.",
                file=sys.stderr,
            )
            return 1
        if new_total == 0:
            print("Nothing new stored; the pages held no unseen postings.")
    return 0


def _listing_files(path: Path) -> list[Path]:
    """One listing file, or every ``*.html`` under a directory, sorted."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(
            p for p in path.iterdir() if p.is_file() and p.suffix.lower() in {".html", ".htm"}
        )
    return []


def cmd_job_ingest(args: argparse.Namespace) -> int:
    """Parse and store a job from a local page file. No browser."""
    with _assistant(args) as app:
        path = Path(args.path)
        if not path.is_file():
            print(f"not a file: {path}", file=sys.stderr)
            return 1
        html = path.read_text(encoding="utf-8", errors="replace")
        result = app.job_service.ingest_page(
            html,
            source=args.source,
            page_url=args.url or "",
            source_path=str(path),
        )
        page = result.page
        print(f"{'Ingested' if result.created else 'Merged'} job {result.job.id}")
        print(f"  title:       {result.job.title or '-'}")
        print(f"  company:     {result.job.company or '-'}")
        print(f"  capture:     {page.status.value}" + (f" ({page.reason})" if page.reason else ""))
        print(f"  description: {page.description_length} chars")
        if not page.usable:
            print()
            print("The capture was not usable; no description was stored.")
            return 1
        print()
        print(f"Next: job analyze {result.job.id}")
    return 0


def cmd_job_show(args: argparse.Namespace) -> int:
    """Show one job: identity, provenance, description, requirements, match."""
    with _assistant(args) as app:
        job = app.job_service.get(args.job_id)
        requirements = app.job_service.repository.requirements(job.id)
        matches = app.job_service.repository.matches(job_id=job.id, limit=1)
        latest = matches[0] if matches else None
        provenance = job.metadata.get("provenance") or None
        reconciliation = job.metadata.get("reconciliation") or None
        review_status = app.job_service.review_status(job.id)
        if args.json:
            _print(
                {
                    "id": job.id,
                    "status": job.status.value,
                    "title": job.title,
                    "company": job.company,
                    "url": job.canonical_url or job.url,
                    "source": job.source,
                    "provenance": provenance,
                    "description_chars": len(job.description_text or ""),
                    "extraction_status": job.metadata.get("extraction_status"),
                    "reconciliation": reconciliation,
                    "requirements": len(requirements),
                    "latest_decision": latest["decision"] if latest else None,
                    "review_status": review_status,
                },
                as_json=True,
            )
            return 0
        print(f"Job {job.id}  [{job.status.value}]")
        print(f"  title:        {job.title or '-'}")
        print(f"  company:      {job.company or '-'}")
        print(f"  url:          {job.canonical_url or job.url or '-'}")
        print(f"  source:       {job.source or '-'}")
        if provenance:
            origin = provenance.get("source_url") or "-"
            print(
                f"  provenance:   {provenance.get('retrieval_method', '?')}"
                f"/{provenance.get('retrieval_status', '?')} from {origin}"
                + (
                    f" at {provenance.get('retrieved_at')}"
                    if provenance.get("retrieved_at")
                    else ""
                )
            )
        if reconciliation:
            print(
                f"  cross-check:  {reconciliation.get('conflicts', 0)} conflict(s)"
                f" ({reconciliation.get('deterministic', 0)} deterministic vs"
                f" {reconciliation.get('ai', 0)} ai requirements)"
            )
        print(f"  discovered:   {job.discovered_at.isoformat()}")
        print(
            f"  description:  {len(job.description_text or '')} chars "
            f"(extraction: {job.metadata.get('extraction_status') or 'not recorded'})"
        )
        print(f"  requirements: {len(requirements)}")
        print(
            f"  latest match: {latest['decision'] if latest else 'none'}"
            + (f" at {latest['created_at']}" if latest else "")
        )
        if review_status:
            print(f"  review:       {review_status}")
    return 0


def cmd_job_analyze(args: argparse.Namespace) -> int:
    """Extract the job's requirements, reusing the cache when possible."""
    with _assistant(args) as app:
        ai = bool(getattr(args, "ai", False))
        model = getattr(args, "model", None)
        if model and not ai:
            raise ConfigurationError(
                "--model requires --ai",
                hint="drop --model for the deterministic path",
            )
        provider = app.ai_provider() if ai else None
        outcome = app.job_service.analyze(
            args.job_id, ai=ai, provider=provider, model=model
        )
        requirements = outcome.requirements
        if args.json:
            _print(
                {
                    "job_id": args.job_id,
                    "cached": outcome.cached,
                    "analysis_id": outcome.analysis_id,
                    "content_hash": outcome.content_hash,
                    "requirements": len(requirements),
                    "ai_attempted": ai,
                    "ai_fallback": outcome.ai_fallback,
                    "ai_error_code": outcome.ai_error_code,
                },
                as_json=True,
            )
            return 0
        print(f"Analyzed {args.job_id}" + (" (cache hit)" if outcome.cached else ""))
        if ai:
            if outcome.ai_fallback:
                print(
                    "  ai: FAILED ("
                    + (outcome.ai_error_code or "unknown")
                    + ") -> deterministic fallback; the attempt is recorded"
                )
            elif not outcome.cached:
                print("  ai: model reading stored and validated")
            else:
                print("  ai: model reading served from cache")
        print(f"  requirements: {len(requirements)}")
        for priority in ("REQUIRED", "PREFERRED", "UNKNOWN"):
            count = sum(1 for r in requirements if r.priority.value == priority)
            if count:
                print(f"    {priority.lower():<10} {count}")
        print(f"  content hash: {outcome.content_hash[:16]}...")
        print()
        for index, requirement in enumerate(requirements):
            suffix = (
                f" (min {requirement.min_years:g} years)"
                if requirement.min_years is not None
                else ""
            )
            print(
                f"  [{index}] {requirement.priority.value} "
                f"{requirement.kind.value}: {requirement.text}{suffix}"
            )
    return 0


def cmd_job_match(args: argparse.Namespace) -> int:
    """Match the job against the candidate profile. Verdict only."""
    with _assistant(args) as app:
        kind = getattr(args, "scorer", "none")
        scorer = app.build_scorer(kind)
        outcome = app.job_service.match(args.job_id, scorer=scorer)
        result = outcome.result
        if args.json:
            payload = result.model_dump(mode="json")
            payload["cached"] = outcome.cached
            payload["scorer"] = kind
            payload["review_reasons"] = [r.value for r in outcome.review_reasons]
            _print(payload, as_json=True)
            return 0
        print(f"Matched {args.job_id}" + (" (cache hit)" if outcome.cached else ""))
        print(f"  decision:   {result.decision.value}")
        if kind != "none":
            print(f"  scorer:     {kind} ({outcome.scorer_fingerprint})")
        print(
            f"  gate:       {result.gate.status.value} "
            f"({len(result.gate.checks)} check(s))"
        )
        print(f"  scored:     {len(result.scores)} row(s)")
        if result.similarity_score is not None:
            print(f"  similarity: {result.similarity_score:.2f}")
        if outcome.review_reasons:
            print(
                "  review:     "
                + ", ".join(r.value for r in outcome.review_reasons)
            )
        print()
        print("Match verdict only - no application was started or submitted.")
    return 0


def cmd_job_report(args: argparse.Namespace) -> int:
    """Print the eleven-dimension report. Explanation only, no action."""
    from jobs.dimensions import DIMENSIONS

    with _assistant(args) as app:
        kind = getattr(args, "scorer", "none")
        report = app.job_service.report(args.job_id, scorer=app.build_scorer(kind))
        if args.json:
            payload = report.model_dump(mode="json")
            payload["scorer"] = kind
            _print(payload, as_json=True)
            return 0
        print(f"Report for {args.job_id}")
        print(
            f"  decision:   {report.decision.value} "
            f"(gate: {report.gate_status.value})"
        )
        overall = (
            "not scored"
            if report.overall_match is None
            else f"{report.overall_match:.2f}"
        )
        print(f"  overall:    {overall}")
        print(f"  confidence: {report.confidence:.2f}")
        for blocker in report.hard_blockers:
            print(f"  blocker:    {blocker}")
        for alarm in report.alarms:
            print(f"  ALARM:      {alarm}")
        print("  dimensions:")
        for name in DIMENSIONS:
            dimension = report.dimension_scores[name]
            score = (
                "not scored"
                if dimension.score is None
                else f"{dimension.score:.2f}"
            )
            print(
                f"    {name:24} {dimension.status.value:15} {score:>10}  "
                f"{dimension.explanation}"
            )
        print()
        print("Match report only - no application was started or submitted.")
    return 0


def cmd_job_relevance(args: argparse.Namespace) -> int:
    """Recommend a stored resume for the job, or explain why none fits."""
    with _assistant(args) as app:
        relevance = app.job_service.relevance(args.job_id)
        if args.json:
            _print(relevance.model_dump(mode="json"), as_json=True)
            return 0
        print(f"Resume relevance for {args.job_id}")
        print(f"  decision:    {relevance.decision.value}")
        print(
            f"  recommended: {relevance.recommended_resume_id or 'none'}"
        )
        if relevance.runner_up_resume_id:
            print(f"  runner-up:   {relevance.runner_up_resume_id}")
        print(f"  confidence:  {relevance.confidence:.2f}")
        print(f"  reason:      {relevance.reason}")
        for score in relevance.scores:
            print(
                f"    {score.resume_id}  {score.coverage:>5.0%}  "
                f"covered {len(score.covered)}, missed {len(score.missed)}"
            )
        print()
        print("Resume relevance only - no application was started or submitted.")
    return 0


def cmd_job_explain(args: argparse.Namespace) -> int:
    """Print the stored match's explanation, one row per requirement."""
    with _assistant(args) as app:
        explanation = app.job_service.explain(args.job_id)
        print(explanation.render())
        print()
        print("No application was started or submitted.")
    return 0


def cmd_job_queue(args: argparse.Namespace) -> int:
    """List the jobs waiting for a human decision."""
    with _assistant(args) as app:
        queue = app.job_service.review_queue()
        if args.json:
            _print([item.model_dump(mode="json") for item in queue.items], as_json=True)
            return 0
        if len(queue) == 0:
            print("Review queue is empty.")
            return 0
        print(_table(
            [
                (
                    item.job_id,
                    item.title or "-",
                    item.decision.value,
                    ", ".join(r.value for r in item.reasons) or "-",
                )
                for item in queue.items
            ],
            ("JOB", "TITLE", "DECISION", "REASONS"),
        ))
        print()
        for reason, count in queue.counts_by_reason().items():
            print(f"  {reason.value}: {count}")
        print()
        print(f"{len(queue)} job(s) waiting for a human.")
        print("A queued job is undecided, not rejected.")
    return 0


def cmd_job_resolve(args: argparse.Namespace) -> int:
    """Mark this job's review resolved: a human has looked, and answered."""
    with _assistant(args) as app:
        note = getattr(args, "note", "") or ""
        resolved = app.job_service.resolve_review(args.job_id, note=note)
        if args.json:
            _print(
                {
                    "job_id": args.job_id,
                    "resolved": resolved,
                    "status": app.job_service.review_status(args.job_id),
                },
                as_json=True,
            )
            return 0
        if resolved:
            print(f"Review resolved for {args.job_id}.")
            if note:
                print(f"  note: {note}")
        else:
            current = app.job_service.review_status(args.job_id)
            if current is None:
                print(f"No review is on record for {args.job_id}.")
            else:
                print(f"Review for {args.job_id} is already {current}.")
        print("Resolution recorded only - no application was started or submitted.")
    return 0


def cmd_acceptance(args: argparse.Namespace) -> int:
    """Run the Phase 2 and Milestone 3 acceptance checklists locally."""
    from assistant.acceptance import run_acceptance

    return run_acceptance(as_json=args.json)


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="job_assistant.py",
        description=_BANNER,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--env-file", default=None, help="path to a .env file")
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, help_text: str, fn: Any) -> argparse.ArgumentParser:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=fn)
        return p

    p = add("status", "system status: safety, paths, database, config", cmd_status)
    p.add_argument("--json", action="store_true")

    add("safety", "report which privileged actions are permitted", cmd_safety)

    # profile
    pprofile = sub.add_parser("profile", help="candidate profile commands")
    pprofile.set_defaults(func=cmd_profile_show)
    psub = pprofile.add_subparsers(dest="subcommand", required=True)

    p = psub.add_parser("init", help="create an empty all-UNKNOWN profile")
    p.set_defaults(func=cmd_profile_init)
    p.add_argument("--candidate-id", default="primary")
    p.add_argument("--force", action="store_true", help="replace an existing profile")

    p = psub.add_parser("show", help="show known fields")
    p.set_defaults(func=cmd_profile_show)
    p.add_argument("--candidate-id", default="primary")
    p.add_argument("--all", action="store_true", help="include UNKNOWN fields")
    p.add_argument("--json", action="store_true")

    p = psub.add_parser("unknown", help="list fields still to fill in")
    p.set_defaults(func=cmd_profile_unknown)
    p.add_argument("--candidate-id", default="primary")
    p.add_argument("--json", action="store_true")

    p = psub.add_parser("set", help="set one fact")
    p.set_defaults(func=cmd_profile_set)
    p.add_argument("field")
    p.add_argument("value")
    p.add_argument("--candidate-id", default="primary")
    p.add_argument("--status", default="VERIFIED", choices=[s.value for s in FactStatus])
    p.add_argument("--source", default=None, choices=[s.value for s in EvidenceSourceType])
    p.add_argument("--source-id", default=None)
    p.add_argument("--source-location", default=None)
    p.add_argument("--validate", action="store_true")

    p = psub.add_parser("validate", help="validate the profile")
    p.set_defaults(func=cmd_profile_validate)
    p.add_argument("--candidate-id", default="primary")
    p.add_argument("--json", action="store_true")

    # resume
    presume = sub.add_parser("resume", help="resume ingestion commands")
    presume.set_defaults(func=cmd_resume_list)
    rsub = presume.add_subparsers(dest="subcommand", required=True)

    p = rsub.add_parser("ingest", help="ingest resume file(s)")
    p.set_defaults(func=cmd_resume_ingest)
    p.add_argument("paths", nargs="+", type=Path)
    p.add_argument("--variant", default=None, help='e.g. "AI Engineer"')
    p.add_argument(
        "--role-focus",
        default=None,
        help='slug of the role this variant targets, e.g. "ml-engineer"',
    )
    p.add_argument(
        "--skills",
        default=None,
        help="comma-separated skills this variant emphasises",
    )
    p.add_argument(
        "--version",
        default=None,
        help="variant version label, e.g. v2",
    )
    p.add_argument("--candidate-id", default="primary")
    p.add_argument("--synthetic", action="store_true", help="mark as test data")
    p.add_argument("--allow-duplicate", action="store_true")

    p = rsub.add_parser("list", help="list ingested resumes")
    p.set_defaults(func=cmd_resume_list)
    p.add_argument("--candidate-id", default="primary")
    p.add_argument("--json", action="store_true")

    p = rsub.add_parser("show", help="show one resume")
    p.set_defaults(func=cmd_resume_show)
    p.add_argument("resume_id")
    p.add_argument("--text", action="store_true", help="print raw text only")

    # db
    pdb = sub.add_parser("db", help="database commands")
    pdb.set_defaults(func=cmd_db_init)
    dsub = pdb.add_subparsers(dest="subcommand", required=True)

    p = dsub.add_parser("init", help="create or migrate")
    p.set_defaults(func=cmd_db_init)

    p = dsub.add_parser("tables", help="list tables and columns")
    p.set_defaults(func=cmd_db_tables)

    # ai
    pai = sub.add_parser("ai", help="AI provider commands")
    pai.set_defaults(func=cmd_ai_health)
    isub = pai.add_subparsers(dest="subcommand", required=True)

    p = isub.add_parser("health", help="check provider availability")
    p.set_defaults(func=cmd_ai_health)

    p = isub.add_parser("models", help="list local models")
    p.set_defaults(func=cmd_ai_models)

    # job intelligence (Milestone 3: local pages, no browser;
    # Milestone 4: read-only discovery from saved listing pages)
    pjob = sub.add_parser(
        "job",
        help="job intelligence: discover, ingest, analyze, match, explain, queue",
    )
    pjob.set_defaults(func=cmd_job_list)
    jsub = pjob.add_subparsers(dest="subcommand", required=True)

    p = jsub.add_parser("list", help="list saved jobs")
    p.set_defaults(func=cmd_job_list)
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--json", action="store_true")

    p = jsub.add_parser(
        "discover",
        help="discover jobs from saved listing page(s): read-only, offline",
    )
    p.set_defaults(func=cmd_job_discover)
    p.add_argument("path", type=Path, help="listing page file, or a directory of pages")
    p.add_argument("--source", default="local", help="source key recorded on each job")
    p.add_argument("--url", default=None, help="listing page URL, when known")

    p = jsub.add_parser("ingest", help="store a job from a local page file")
    p.set_defaults(func=cmd_job_ingest)
    p.add_argument("path", type=Path)
    p.add_argument("--source", default="local", help="source key recorded on the job")
    p.add_argument("--url", default=None, help="page URL, when known")

    p = jsub.add_parser("show", help="show one job")
    p.set_defaults(func=cmd_job_show)
    p.add_argument("job_id")
    p.add_argument("--json", action="store_true")

    p = jsub.add_parser("analyze", help="extract requirements (cached)")
    p.set_defaults(func=cmd_job_analyze)
    p.add_argument("job_id")
    p.add_argument(
        "--ai",
        action="store_true",
        help="read requirements with the configured AI provider; on failure "
        "the deterministic extractor runs instead and the attempt is recorded",
    )
    p.add_argument(
        "--model",
        default=None,
        help="model override for this call (requires --ai)",
    )
    p.add_argument("--json", action="store_true")

    p = jsub.add_parser("match", help="match against the profile (verdict only)")
    p.set_defaults(func=cmd_job_match)
    p.add_argument("job_id")
    p.add_argument(
        "--scorer",
        choices=["none", "lexical", "embedding"],
        default="none",
        help="semantic scorer to score with (default: none - claims and facts only)",
    )
    p.add_argument("--json", action="store_true")

    p = jsub.add_parser(
        "report", help="eleven-dimension report for the job (explanation only)"
    )
    p.set_defaults(func=cmd_job_report)
    p.add_argument("job_id")
    p.add_argument(
        "--scorer",
        choices=["none", "lexical", "embedding"],
        default="none",
        help="semantic scorer to score with (default: none - claims and facts only)",
    )
    p.add_argument("--json", action="store_true")

    p = jsub.add_parser(
        "relevance",
        help="which stored resume fits this job (recommendation only)",
    )
    p.set_defaults(func=cmd_job_relevance)
    p.add_argument("job_id")
    p.add_argument("--json", action="store_true")

    p = jsub.add_parser(
        "resolve", help="mark the job's review resolved (records your answer)"
    )
    p.set_defaults(func=cmd_job_resolve)
    p.add_argument("job_id")
    p.add_argument("--note", default="", help="why this doubt is settled")
    p.add_argument("--json", action="store_true")

    p = jsub.add_parser("explain", help="print the stored match's explanation")
    p.set_defaults(func=cmd_job_explain)
    p.add_argument("job_id")

    p = jsub.add_parser("queue", help="list jobs waiting for a human")
    p.set_defaults(func=cmd_job_queue)
    p.add_argument("--json", action="store_true")

    # acceptance
    p = add("acceptance", "run the acceptance checklists", cmd_acceptance)
    p.add_argument("--json", action="store_true")

    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except ConfigurationError as exc:
        print(f"ConfigurationError: {exc}", file=sys.stderr)
        return 78
    except AssistantError as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130
