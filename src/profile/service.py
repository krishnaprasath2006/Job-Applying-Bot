"""Candidate profile service.

This is the layer the CLI and later phases call. It coordinates the model, the
validator, the JSON file, and the database, so no caller has to know that a
profile lives in two places at once.

Every write goes through :meth:`ProfileService.update_fact`, which records the
actor. An AI caller passing ``actor="ollama"`` gets its suggestion stored with
``actor_kind = AI`` in the change log; attempting to write a ``VERIFIED`` fact
that way raises :class:`~core.errors.ImmutableFactError`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from core.enums import EvidenceSourceType, FactStatus
from core.errors import ImmutableFactError, ProfileNotFoundError, ProfileValidationError
from core.evidence import Evidence, Fact
from core.hashing import utc_now
from core.logging_config import get_logger, log_event
from database.connection import Database
from database.repositories.profiles import TRUSTED_ACTORS, ProfileRepository, classify_actor
from profile.models import CandidateProfile, build_empty_profile
from profile.validator import CandidateProfileValidator, ValidationReport

__all__ = ["ProfileService"]

#: The candidate whose profile keeps the documented ``candidate_profile.json``
#: name. Any other id gets its own file.
DEFAULT_CANDIDATE_ID = "primary"

_log = get_logger("profile.service")


class ProfileService:
    """Create, load, update, and validate a candidate profile."""

    def __init__(
        self,
        db: Database,
        *,
        storage_path: Optional[Path] = None,
        validator: Optional[CandidateProfileValidator] = None,
    ) -> None:
        self.db = db
        self.repository = ProfileRepository(db)
        self.storage_path = storage_path
        self.validator = validator or CandidateProfileValidator()

    def path_for(self, candidate_id: str = "primary") -> Optional[Path]:
        """Where this candidate's JSON copy lives.

        ``storage_path`` names the default candidate's file. Every other
        candidate gets its own file beside it, derived from the id. One shared
        path would let ``load_profile("acceptance")`` hand back the real
        candidate's file, which is both wrong and, in a test run, a way to
        read someone's real data by accident.

        Args:
            candidate_id: Candidate whose path is wanted.

        Returns:
            The path, or ``None`` when no JSON storage is configured.
        """
        if self.storage_path is None:
            return None
        base = Path(self.storage_path)
        if candidate_id == DEFAULT_CANDIDATE_ID:
            return base
        return base.parent / f"{candidate_id}.json"

    # -- create / load -------------------------------------------------------
    def create_profile(
        self,
        candidate_id: str = "primary",
        *,
        persist_json: bool = True,
        actor: str = "system",
    ) -> CandidateProfile:
        """Create an empty, all-``UNKNOWN`` profile.

        This writes no facts. It is the correct starting point for a real
        person about whom nothing is yet known.

        Args:
            candidate_id: Identifier for this candidate.
            persist_json: Also write the git-ignored JSON working copy.
            actor: Who is creating the profile, recorded in the change log.

        Returns:
            The new :class:`CandidateProfile`.

        Raises:
            ProfilePersistenceError: If a profile already exists.
        """
        profile = build_empty_profile(candidate_id)
        self.repository.create(profile, actor=actor)
        if persist_json:
            target = self.path_for(candidate_id)
            if target is not None:
                profile.save(target)

        log_event(
            _log,
            "profile.created",
            candidate_id=candidate_id,
            profile_id=profile.id,
            facts=profile.fact_count(),
            unknown=len(profile.unknown_fields()),
        )
        return profile

    def load_profile(self, candidate_id: str = "primary") -> CandidateProfile:
        """Load a profile from its stored JSON file.

        Raises:
            ProfileNotFoundError: If neither the file nor the database has a
                profile for this candidate.
        """
        target = self.path_for(candidate_id)
        if target is not None and target.is_file():
            profile = CandidateProfile.load(target)
            if profile.candidate_id != candidate_id:
                raise ProfileNotFoundError(
                    "the stored JSON file belongs to a different candidate; "
                    "refusing to return another person's profile",
                    candidate_id=candidate_id,
                    storage_path=str(target),
                    found_candidate_id=profile.candidate_id,
                )
            return profile
        if self.repository.by_candidate(candidate_id) is not None:
            raise ProfileNotFoundError(
                "profile exists in the database but no JSON file was found; "
                "re-export it rather than rebuilding it, so evidence is not lost",
                candidate_id=candidate_id,
                storage_path=str(self.storage_path) if self.storage_path else None,
            )
        raise ProfileNotFoundError(
            "no profile has been created yet",
            candidate_id=candidate_id,
            hint="run: python assistant.py profile init",
        )

    def load_profile_from_database(self, candidate_id: str = "primary") -> CandidateProfile:
        """Rebuild a profile from the database instead of the JSON copy.

        This is an explicit opt-in. :meth:`load_profile` refuses to fall back
        on its own, because silently preferring a database rebuild over a
        missing file would hide the fact that the human's editable copy is
        gone. Callers that genuinely have no JSON file, such as a test run
        using a temporary database, ask for it by name.

        Args:
            candidate_id: Candidate to rebuild.

        Returns:
            The profile, with its facts as stored.

        Raises:
            ProfileNotFoundError: If the database has no such profile.
        """
        row = self.repository.by_candidate(candidate_id)
        if row is None:
            raise ProfileNotFoundError(
                "no profile for this candidate in the database",
                candidate_id=candidate_id,
            )
        profile = build_empty_profile(candidate_id)
        for fact in self.repository.fact_models(row["id"]):
            # A stored Fact carries its evidence rather than duplicated source
            # columns, so the compact source fields are re-derived from the
            # first evidence record.
            evidence = list(fact.evidence)
            kwargs: dict[str, Any] = {
                "status": fact.status,
                "verified_at": fact.verified_at,
                "evidence": evidence,
            }
            if evidence:
                kwargs.update(
                    source=evidence[0].source_type,
                    source_id=evidence[0].source_id,
                    source_location=evidence[0].source_location,
                    confidence=evidence[0].confidence,
                )
            if fact.note:
                kwargs["note"] = fact.note
            profile = profile.with_update(fact.field_path, fact.value, **kwargs)
        return profile

    def profile_exists(self, candidate_id: str = "primary") -> bool:
        target = self.path_for(candidate_id)
        if target is not None and target.is_file():
            return True
        return self.repository.by_candidate(candidate_id) is not None

    # -- update --------------------------------------------------------------
    def update_fact(
        self,
        path: str,
        value: Any,
        *,
        status: FactStatus = FactStatus.UNKNOWN,
        source: Optional[EvidenceSourceType] = None,
        source_id: Optional[str] = None,
        source_location: Optional[str] = None,
        confidence: float = 1.0,
        evidence: Optional[list[Evidence]] = None,
        actor: str = "user",
        candidate_id: str = "primary",
        validate: bool = False,
    ) -> CandidateProfile:
        """Set one fact and persist the result.

        Args:
            path: Dotted field path, e.g. ``identity.full_name``.
            value: New value, or ``None`` to mark the field ``UNKNOWN``.
            status: Truth status. A non-trusted actor cannot set ``VERIFIED``.
            source: Where the value came from. Required for ``VERIFIED``.
            source_id: Identifier of that source.
            source_location: Position within the source.
            confidence: Evidence confidence in ``[0, 1]``.
            evidence: Citation records. Without at least one, a ``VERIFIED``
                fact stays out of :attr:`Fact.is_application_safe`, because
                "the candidate said so" is not the same as being able to show
                where a value came from.
            actor: ``"user"`` for the human, or a provider name such as
                ``"ollama"`` for machine output.
            candidate_id: Which candidate.
            validate: Validate after writing and raise on ERROR findings.

        Returns:
            The updated profile.

        Raises:
            ImmutableFactError: If a non-trusted actor tries to write a
                ``VERIFIED`` fact.
            ProfileNotFoundError: If no profile exists.
            AttributeError: If ``path`` does not exist.
            ProfileValidationError: If ``validate`` is true and validation fails.
        """
        profile = self.load_profile(candidate_id)
        actor_kind = classify_actor(actor)

        if status is FactStatus.VERIFIED:
            if actor_kind == "AI":
                raise ImmutableFactError(
                    "AI output cannot create a VERIFIED fact; store it as INFERRED "
                    "and require a human to promote it",
                    field_path=path,
                    actor=actor,
                )
            if source is None:
                raise ImmutableFactError(
                    "a VERIFIED fact must cite a source",
                    field_path=path,
                    hint="pass source=EvidenceSourceType.USER_INPUT",
                )

        if actor_kind == "AI" and status is FactStatus.UNKNOWN and value is not None:
            status = FactStatus.INFERRED

        updated = profile.with_update(
            path,
            value,
            status=status,
            source=source,
            source_id=source_id,
            source_location=source_location,
            confidence=confidence,
            verified_at=utc_now() if status is FactStatus.VERIFIED else None,
            # An empty list, not None: evidence describing the value that was
            # just replaced is worse than no evidence, because it still looks
            # like support for the new value.
            evidence=list(evidence) if evidence else [],
        )

        self.repository.save_profile(updated, actor=actor)
        target = self.path_for(updated.candidate_id)
        if target is not None:
            updated.save(target)

        report = None
        if validate:
            report = self.validator.validate(updated)
            report.raise_if_invalid()

        log_event(
            _log,
            "profile.fact_updated",
            field_path=path,
            status=status.value,
            actor_kind=actor_kind,
            candidate_id=candidate_id,
            valid=(report.is_valid if report else None),
        )
        return updated

    def suggest_fact(
        self,
        path: str,
        value: Any,
        *,
        source: Optional[EvidenceSourceType] = None,
        source_id: Optional[str] = None,
        source_location: Optional[str] = None,
        confidence: float = 0.5,
        candidate_id: str = "primary",
    ) -> CandidateProfile:
        """Record a machine suggestion as ``INFERRED``.

        This is the only way AI output may enter the profile. The value is
        stored, traceable, and explicitly not application-safe.
        """
        return self.update_fact(
            path,
            value,
            status=FactStatus.INFERRED,
            source=source,
            source_id=source_id,
            source_location=source_location,
            confidence=confidence,
            actor="ollama",
            candidate_id=candidate_id,
        )

    def import_facts(self, profile: CandidateProfile, *, actor: str = "user") -> CandidateProfile:
        """Replace the stored profile wholesale with ``profile``.

        Raises:
            ImmutableFactError: If a non-trusted actor supplied the profile.
        """
        if classify_actor(actor) == "AI":
            raise ImmutableFactError(
                "an AI actor cannot replace a profile",
                actor=actor,
            )
        self.repository.save_profile(profile, actor=actor)
        target = self.path_for(profile.candidate_id)
        if target is not None:
            profile.save(target)
        return profile

    # -- validate ------------------------------------------------------------
    def validate_profile(self, candidate_id: str = "primary") -> ValidationReport:
        """Validate the stored profile.

        An all-``UNKNOWN`` profile is valid; it is simply incomplete for real
        applications. ``missing_required`` is the actionable part.

        Raises:
            ProfileNotFoundError: If no profile exists.
        """
        profile = self.load_profile(candidate_id)
        report = self.validator.validate(profile)
        if self.repository.by_candidate(candidate_id) is not None:
            status = "VALIDATED" if report.is_valid and not report.missing_required else (
                "INCOMPLETE" if not report.missing_required else "INVALID"
            )
            self.repository.set_status(profile.id, status, validated=report.is_valid)

        log_event(
            _log,
            "profile.validated",
            candidate_id=candidate_id,
            is_valid=report.is_valid,
            errors=len(report.errors),
            warnings=len(report.warnings),
            completeness=report.completeness,
        )
        return report

    def validate_or_raise(self, candidate_id: str = "primary") -> ValidationReport:
        """Validate and raise on ERROR findings."""
        report = self.validate_profile(candidate_id)
        report.raise_if_invalid()
        return report

    # -- read ----------------------------------------------------------------
    def get_fact(self, path: str, candidate_id: str = "primary") -> Optional[Fact]:
        """Return one fact with its evidence, or ``None`` if unknown."""
        # Read the id from the row rather than from the profile file: this is a
        # single-fact lookup and requiring the JSON copy to exist first would
        # make a perfectly good database look empty.
        row = self.repository.by_candidate(candidate_id)
        if row is None:
            return None
        return self.repository.get_fact(row["id"], path)

    def get_fact_with_evidence(self, path: str, candidate_id: str = "primary") -> Optional[dict[str, Any]]:
        """Return a fact rendered for display, with full evidence detail.

        Returns ``None`` when the field is ``UNKNOWN`` rather than
        fabricating something to return.
        """
        fact = self.get_fact(path, candidate_id)
        if fact is None:
            return None
        return {
            "field_path": fact.field_path,
            "value": fact.value,
            "status": fact.status.value,
            "is_application_safe": fact.is_application_safe,
            "verified_at": fact.verified_at.isoformat() if fact.verified_at else None,
            "updated_at": fact.updated_at.isoformat(),
            "evidence": [
                {
                    "source_type": e.source_type.value,
                    "source_id": e.source_id,
                    "source_location": e.source_location,
                    "text_excerpt": e.text_excerpt,
                    "confidence": e.confidence,
                    "created_at": e.created_at.isoformat(),
                    "citation": e.cite(),
                }
                for e in fact.evidence
            ],
        }

    def list_unknown_fields(self, candidate_id: str = "primary") -> list[dict[str, str]]:
        """Every ``UNKNOWN`` field with its dotted path.

        This is the work list for filling in a profile.
        """
        profile = self.load_profile(candidate_id)
        unknown = set(profile.unknown_fields())
        if self.repository.by_candidate(candidate_id) is not None:
            unknown |= set(self.repository.unknown_fields(profile.id))

        required = set(self.validator_required())
        return [
            {"field_path": path, "required_for_application": str(path in required).lower()}
            for path in sorted(unknown)
        ]

    def validator_required(self) -> tuple[str, ...]:
        from profile.validator import REQUIRED_FOR_APPLICATION

        return REQUIRED_FOR_APPLICATION

    def completeness(self, candidate_id: str = "primary") -> float:
        return self.load_profile(candidate_id).completeness()

    def change_log(self, candidate_id: str = "primary") -> list[dict[str, Any]]:
        profile = self.load_profile(candidate_id)
        if self.repository.by_candidate(candidate_id) is None:
            return []
        return self.repository.change_log(profile.id)

    def export_json(self, path: Optional[Path] = None, candidate_id: str = "primary") -> Path:
        """Write the profile JSON to an explicit path."""
        profile = self.load_profile(candidate_id)
        target = path if path is not None else self.path_for(candidate_id)
        if target is None:
            raise ProfileNotFoundError(
                "no path to export to; pass one explicitly",
                candidate_id=candidate_id,
            )
        return profile.save(target)
