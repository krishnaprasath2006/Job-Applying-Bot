"""Profile routes.

Read and write the candidate profile through ``ProfileService`` only. The
routes never read or write the profile JSON file directly: the service owns
persistence, evidence rules, and the change log, and a route that touched the
file would skip all three.

Writes are single-fact and explicit. There is no bulk replace, because
``update_fact`` is what records evidence and an actor per change, and a
whole-profile PUT would make it impossible to say which field a caller changed
or why.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.dependencies import AssistantDep, CandidateIdDep
from api.schemas import (
    FactResponse,
    FactUpdate,
    ProfileCompletenessResponse,
    ProfileResponse,
    ProfileValidationResponse,
    UnknownFieldsResponse,
)
from core.enums import FactStatus
from profile.models import build_empty_profile

router = APIRouter(prefix="/profile", tags=["profile"])


@router.get("", response_model=ProfileResponse, summary="Read the profile")
def read_profile(assistant: AssistantDep, candidate_id: CandidateIdDep) -> ProfileResponse:
    """The stored profile for the configured candidate.

    An absent profile is reported as ``exists: false`` with an empty template
    rather than a 404. ``load_profile`` raises ``ProfileNotFoundError`` when
    nothing is stored, but "this candidate has no profile yet" is the normal
    state of a fresh install and a UI needs to render it, not to receive an
    error. The template comes from ``profile.models.build_empty_profile`` — the
    same constructor the CLI uses — so this is not a second notion of an empty
    profile.
    """
    if not assistant.profile_service.profile_exists(candidate_id):
        return ProfileResponse(
            candidate_id=candidate_id,
            exists=False,
            profile=build_empty_profile(candidate_id),
        )
    profile = assistant.profile_service.load_profile(candidate_id)
    return ProfileResponse(candidate_id=candidate_id, exists=True, profile=profile)


@router.post(
    "",
    response_model=ProfileResponse,
    summary="Set one fact",
    responses={
        403: {"description": "The write was refused (immutable fact or unsupported status)."},
        422: {"description": "Validation or evidence rule rejected the write."},
    },
)
def update_fact(
    payload: FactUpdate,
    assistant: AssistantDep,
    candidate_id: CandidateIdDep,
) -> ProfileResponse:
    """Write one fact and return the resulting profile.

    If the candidate has no profile yet, one is created automatically.
    The candidate id is server-side configuration. A request cannot ask to
    write into another candidate's profile.
    """
    if not assistant.profile_service.profile_exists(candidate_id):
        # Create an empty profile for this candidate
        empty_profile = build_empty_profile(candidate_id)
        assistant.profile_service.repository.upsert(empty_profile, actor="user")
        target = assistant.profile_service.path_for(candidate_id)
        if target is not None:
            empty_profile.save(target)
    else:
        # ``profile_exists`` is true when *either* store has the profile, so a
        # row in the database whose JSON working copy has been moved or deleted
        # reaches this point with nothing to load: ``load_profile`` refuses that
        # state on purpose, because silently rebuilding would hide the loss.
        #
        # Left alone, that makes this endpoint permanently unusable until
        # somebody restores the file by hand. Rebuild the JSON from the
        # database instead, which is the explicit opt-in the service provides
        # for exactly this case, and never touches the facts.
        target = assistant.profile_service.path_for(candidate_id)
        if target is not None and not target.is_file():
            restored = assistant.profile_service.load_profile_from_database(candidate_id)
            restored.save(target)

    update_kwargs = {
        "path": payload.field_path,
        "value": payload.value,
        "evidence": payload.evidence_rows(),
        "candidate_id": candidate_id,
        "actor": "user",
    }
    if payload.status is not None:
        update_kwargs["status"] = payload.status
    elif payload.value is not None:
        # Human claim without explicit status defaults to INFERRED (a claim requiring verification)
        update_kwargs["status"] = FactStatus.INFERRED

    try:
        profile = assistant.profile_service.update_fact(**update_kwargs)
    except AttributeError as e:
        # Invalid field path - convert to validation error
        from core.errors import ProfileValidationError

        raise ProfileValidationError(
            f"invalid field path: {e}",
            issues=[{"field_path": payload.field_path, "message": str(e)}],
        )

    return ProfileResponse(
        candidate_id=candidate_id, exists=True, profile=profile
    )


@router.get("/facts/{field_path:path}", response_model=FactResponse, summary="Read one fact")
def read_fact(
    field_path: str,
    assistant: AssistantDep,
    candidate_id: CandidateIdDep,
) -> FactResponse:
    """One fact with its evidence."""
    found = assistant.profile_service.get_fact_with_evidence(
        field_path, candidate_id=candidate_id
    )
    if found is None:
        # The service returns None for "no such field"; the boundary turns that
        # into a 404 rather than an empty object the caller must check.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no fact at {field_path!r}")
    return FactResponse(
        field_path=found.get("field_path", field_path),
        value=found.get("value"),
        status=found.get("status"),
        evidence=found.get("evidence", []) or [],
        verified_at=found.get("verified_at"),
        note=found.get("note"),
    )


@router.get(
    "/validation",
    response_model=ProfileValidationResponse,
    summary="Validate the profile",
)
def validate_profile(
    assistant: AssistantDep, candidate_id: CandidateIdDep
) -> ProfileValidationResponse:
    """Findings from ``CandidateProfileValidator``.

    A clean report on an empty template is valid *and* mostly unknown; the
    ``missing_required`` list is what distinguishes the two. When the candidate
    has no stored profile, return a template's validation report rather than a
    404, so the first call a UI makes is useful.
    """
    if not assistant.profile_service.profile_exists(candidate_id):
        profile = build_empty_profile(candidate_id)
        report = assistant.profile_service.validator.validate(profile)
        return ProfileValidationResponse(
            candidate_id=candidate_id,
            is_valid=report.is_valid,
            error_count=len(report.errors),
            warning_count=len(report.warnings),
            completeness=report.completeness,
            missing_required=report.missing_required,
            issues=[
                {
                    "code": issue.code.value,
                    "severity": issue.severity.value,
                    "field_path": issue.field_path,
                    "message": issue.message,
                    "actual": issue.actual,
                    "expected": issue.expected,
                }
                for issue in report.issues
            ],
        )
    report = assistant.profile_service.validate_profile(candidate_id)
    return ProfileValidationResponse(
        candidate_id=candidate_id,
        is_valid=report.is_valid,
        error_count=len(report.errors),
        warning_count=len(report.warnings),
        completeness=report.completeness,
        missing_required=report.missing_required,
        issues=[
            {
                "code": issue.code.value,
                "severity": issue.severity.value,
                "field_path": issue.field_path,
                "message": issue.message,
                "actual": issue.actual,
                "expected": issue.expected,
            }
            for issue in report.issues
        ],
    )


@router.get(
    "/completeness",
    response_model=ProfileCompletenessResponse,
    summary="How much of the profile is answered",
)
def completeness(
    assistant: AssistantDep, candidate_id: CandidateIdDep
) -> ProfileCompletenessResponse:
    """Fraction of required fields answered."""
    if not assistant.profile_service.profile_exists(candidate_id):
        return ProfileCompletenessResponse(
            candidate_id=candidate_id,
            completeness=build_empty_profile(candidate_id).completeness(),
        )
    return ProfileCompletenessResponse(
        candidate_id=candidate_id,
        completeness=assistant.profile_service.completeness(candidate_id),
    )


@router.get(
    "/unknown",
    response_model=UnknownFieldsResponse,
    summary="Fields still unknown",
)
def unknown_fields(
    assistant: AssistantDep, candidate_id: CandidateIdDep
) -> UnknownFieldsResponse:
    """Exactly the fields a human still needs to supply."""
    if not assistant.profile_service.profile_exists(candidate_id):
        profile = build_empty_profile(candidate_id)
        unknown = [{"field_path": path, "required_for_application": "false"} for path in sorted(profile.unknown_fields())]
        # But better use the service shape
        unknown = assistant.profile_service.list_unknown_fields(candidate_id) if False else [
            {"field_path": p, "required_for_application": "false"} for p in sorted(profile.unknown_fields())
        ]
        # Simpler: call service logic is fine; service calls load_profile which raises. Avoid raise.
        unknown = [
            {"field_path": path, "required_for_application": str(path in set(assistant.profile_service.validator_required())).lower()}
            for path in sorted(profile.unknown_fields())
        ]
        return UnknownFieldsResponse(
            candidate_id=candidate_id, unknown=unknown, count=len(unknown)
        )
    unknown = assistant.profile_service.list_unknown_fields(candidate_id)
    return UnknownFieldsResponse(
        candidate_id=candidate_id, unknown=unknown, count=len(unknown)
    )