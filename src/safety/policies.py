"""Safety policies and guards.

Everything that could cause a real application is gated here. Two independent
mechanisms are used on purpose:

* **Policy** answers "is this operation permitted right now, given settings?"
* **Guard** wraps the operation and refuses it if the policy says no.

Having both means a caller cannot forget to check, and a reviewer can see the
rule in one place. Phase 2 has no submission code, so the guards are currently
exercised by tests rather than by the application; they exist now so later
phases inherit a checked baseline.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Optional, TypeVar

from core.errors import SafetyViolationError, SubmissionBlockedError
from core.settings import SafetySettings

__all__ = [
    "Action",
    "ActionPolicy",
    "SafetyPolicy",
    "ApprovalToken",
    "ApprovalStore",
    "assert_allowed",
    "guard",
    "require_known",
]

T = TypeVar("T")


class Action(str, Enum):
    """Every privileged operation, enumerated.

    An unlisted operation cannot be authorised, which is the safe default.
    """

    NAVIGATE = "navigate"
    READ_PAGE = "read_page"
    FILL_FORM = "fill_form"
    CLICK = "click"
    UPLOAD_FILE = "upload_file"
    SUBMIT_APPLICATION = "submit_application"
    ANSWER_QUESTION = "answer_question"
    USE_VERIFIED_FACT = "use_verified_fact"


@dataclass(frozen=True)
class ActionPolicy:
    """What is required before one action may run.

    Attributes:
        action: The action being considered.
        allow_flag: Settings attribute that must be true.
        needs_approval: Whether a human must approve this specific instance.
        requires_dry_run_off: Whether ``dry_run`` must be false.
        requires_safe_mode_off: Whether ``safe_mode`` must be false.
        blocked_message: Operator-facing explanation on refusal.
    """

    action: Action
    allow_flag: str
    needs_approval: bool = False
    requires_dry_run_off: bool = False
    requires_safe_mode_off: bool = False
    blocked_message: str = ""


#: The policy table. This is the single source of truth for what is allowed.
POLICIES: dict[Action, ActionPolicy] = {
    Action.NAVIGATE: ActionPolicy(
        action=Action.NAVIGATE,
        allow_flag="allow_browser_navigation",
        needs_approval=False,
        blocked_message="browser navigation is disabled (safety.allow_browser_navigation=false)",
    ),
    Action.READ_PAGE: ActionPolicy(
        action=Action.READ_PAGE,
        allow_flag="allow_browser_navigation",
        blocked_message="page reads need browser navigation enabled",
    ),
    Action.FILL_FORM: ActionPolicy(
        action=Action.FILL_FORM,
        allow_flag="allow_form_filling",
        blocked_message="form filling is disabled (safety.allow_form_filling=false)",
    ),
    Action.CLICK: ActionPolicy(
        action=Action.CLICK,
        allow_flag="allow_form_filling",
        blocked_message="clicking is disabled (safety.allow_form_filling=false)",
    ),
    Action.UPLOAD_FILE: ActionPolicy(
        action=Action.UPLOAD_FILE,
        allow_flag="allow_file_upload",
        blocked_message="file upload is disabled (safety.allow_file_upload=false)",
    ),
    Action.ANSWER_QUESTION: ActionPolicy(
        action=Action.ANSWER_QUESTION,
        allow_flag="allow_form_filling",
        needs_approval=True,
        blocked_message="answering questions requires form filling to be enabled",
    ),
    Action.SUBMIT_APPLICATION: ActionPolicy(
        action=Action.SUBMIT_APPLICATION,
        allow_flag="allow_final_submission",
        needs_approval=True,
        requires_dry_run_off=True,
        requires_safe_mode_off=True,
        blocked_message=(
            "REAL SUBMISSION IS DISABLED. enable_final_submission requires "
            "allow_final_submission=true, dry_run=false, safe_mode=false and "
            "per-application human approval."
        ),
    ),
    Action.USE_VERIFIED_FACT: ActionPolicy(
        action=Action.USE_VERIFIED_FACT,
        allow_flag="allow_form_filling",
        blocked_message=(
            "using a verified fact in a real form requires form filling to be "
            "enabled, and each value must be checked with "
            "safety.guards.assert_application_safe first"
        ),
    ),
}


class ApprovalToken:
    """A single-use human approval bound to one application.

    Deliberately not serialisable and deliberately short-lived: it lives in
    memory, names exactly one application id, and expires.
    """

    def __init__(self, application_id: str, granted_by: str, ttl_seconds: int = 900) -> None:
        self.application_id = application_id
        self.granted_by = granted_by
        self.expires_at = time.monotonic() + ttl_seconds
        self.consumed = False

    @property
    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at

    def consume(self) -> None:
        """Mark the approval used. A token is valid exactly once."""
        self.consumed = True

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"ApprovalToken(application_id={self.application_id!r}, "
            f"expired={self.is_expired}, consumed={self.consumed})"
        )


class ApprovalStore:
    """In-memory approvals. Never persisted, never logged."""

    def __init__(self) -> None:
        self._tokens: dict[str, ApprovalToken] = {}

    def grant(self, application_id: str, granted_by: str, ttl_seconds: int = 900) -> ApprovalToken:
        token = ApprovalToken(application_id, granted_by, ttl_seconds)
        self._tokens[application_id] = token
        return token

    def get(self, application_id: str) -> Optional[ApprovalToken]:
        token = self._tokens.get(application_id)
        if token is None or token.is_expired or token.consumed:
            return None
        return token

    def consume(self, application_id: str) -> bool:
        """Consume an approval, returning whether one was valid."""
        token = self.get(application_id)
        if token is None:
            return False
        token.consume()
        return True

    def revoke(self, application_id: str) -> None:
        self._tokens.pop(application_id, None)


class SafetyPolicy:
    """Evaluates :class:`Action` requests against :class:`SafetySettings`."""

    def __init__(self, settings: SafetySettings, approvals: ApprovalStore | None = None) -> None:
        self._settings = settings
        self.approvals = approvals or ApprovalStore()

    @property
    def settings(self) -> SafetySettings:
        return self._settings

    def check(self, action: Action, application_id: str | None = None) -> Optional[str]:
        """Return a refusal reason, or ``None`` when the action is permitted.

        The order of checks matters: the hard switches are evaluated before
        approval, so a disabled flag is reported as a disabled flag rather
        than as a missing approval.
        """
        policy = POLICIES.get(action)
        if policy is None:
            return f"unknown action {action!r}"

        if action is Action.SUBMIT_APPLICATION and self._settings.dry_run:
            return "DRY_RUN is enabled; real submission is impossible"

        allowed = getattr(self._settings, policy.allow_flag, False)
        if not allowed:
            return policy.blocked_message

        if policy.requires_safe_mode_off and self._settings.safe_mode:
            return "SAFE_MODE is enabled"
        if policy.requires_dry_run_off and self._settings.dry_run:
            return "DRY_RUN is enabled"
        if self._settings.safe_mode and action is not Action.READ_PAGE:
            return f"SAFE_MODE blocks {action.value}"
        if policy.needs_approval or self._settings.require_human_approval:
            if application_id is None:
                return "human approval requires an application id"
            if self.approvals.get(application_id) is None:
                return f"no valid human approval for application {application_id!r}"
        return None

    def is_allowed(self, action: Action, application_id: str | None = None) -> bool:
        return self.check(action, application_id) is None

    def assert_allowed(self, action: Action, application_id: str | None = None) -> None:
        """Raise :class:`SubmissionBlockedError` or :class:`SafetyViolationError`.

        Raises:
            SubmissionBlockedError: For a refused submission.
            SafetyViolationError: For any other refused action.
        """
        reason = self.check(action, application_id)
        if reason is None:
            return
        if action is Action.SUBMIT_APPLICATION:
            raise SubmissionBlockedError(reason, action=action.value, application_id=application_id)
        raise SafetyViolationError(reason, action=action.value, application_id=application_id)

    def status(self) -> dict[str, object]:
        """A loggable snapshot of what is currently permitted."""
        return {
            "safe_mode": self._settings.safe_mode,
            "dry_run": self._settings.dry_run,
            "require_human_approval": self._settings.require_human_approval,
            "actions": {
                action.value: self.is_allowed(action, "probe") for action in Action
            },
            "submission_possible": self._settings.allow_final_submission,
        }


def assert_allowed(
    policy: SafetyPolicy, action: Action, application_id: str | None = None
) -> None:
    """Module-level convenience wrapper around :meth:`SafetyPolicy.assert_allowed`."""
    policy.assert_allowed(action, application_id)


def guard(
    policy: SafetyPolicy, action: Action, operation: Callable[[], T], application_id: str | None = None
) -> T:
    """Run ``operation`` only if ``action`` is permitted.

    Raises:
        SubmissionBlockedError: If a submission is not permitted.
        SafetyViolationError: If any other action is not permitted.
    """
    policy.assert_allowed(action, application_id)
    return operation()


def require_known(value, field_path: str) -> None:
    """Refuse to proceed when a fact is missing.

    Thin wrapper kept here so that "unknown means stop" has a single,
    greppable home rather than being re-implemented per call site.
    """
    if value is None:
        raise SafetyViolationError(
            "refusing to proceed with an UNKNOWN value",
            field_path=field_path,
            hint="supply the value explicitly or leave it UNKNOWN for human review",
        )
