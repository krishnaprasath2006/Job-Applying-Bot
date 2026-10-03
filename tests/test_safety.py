"""Tests for the safety layer: what is refused, and what stays impossible.

These are the tests that matter most in this project. Every privileged action
must be blocked by the default settings, and the only way to unblock one must
be an explicit, human, per-application decision.
"""

from __future__ import annotations

import pytest

from core.enums import EvidenceSourceType, FactStatus
from core.errors import SafetyViolationError, SubmissionBlockedError
from core.evidence import Evidence, Fact
from safety.policies import POLICIES, Action, ApprovalStore, SafetyPolicy
from safety.policies import assert_allowed
from core.settings import SafetySettings


def all_actions() -> list[Action]:
    return list(Action)


class TestDefaults:
    def test_every_switch_is_safe_by_default(self) -> None:
        settings = SafetySettings()
        assert settings.dry_run is True
        assert settings.safe_mode is True
        assert settings.require_human_approval is True
        assert settings.allow_final_submission is False

    def test_no_privileged_action_is_permitted_by_default(self) -> None:
        policy = SafetyPolicy(SafetySettings())
        blocked = [a.value for a in all_actions() if not policy.is_allowed(a, "probe")]
        assert set(blocked) == {a.value for a in all_actions()}

    def test_final_submission_is_rejected_while_dry_run_is_on(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SafetySettings(dry_run=True, allow_final_submission=True)

    def test_status_snapshot_never_leaks_a_token(self) -> None:
        policy = SafetyPolicy(SafetySettings())
        policy.approvals.grant("app-1", granted_by="candidate")
        snapshot = policy.status()
        assert snapshot["submission_possible"] is False
        assert "granted_by" not in str(snapshot)


class TestPolicyTable:
    def test_every_action_has_a_policy(self) -> None:
        assert set(POLICIES) == set(Action)

    def test_no_policy_refers_to_a_flag_that_does_not_exist(self) -> None:
        # A typo in allow_flag would otherwise silently resolve to False and
        # look like a working refusal.
        fields = set(SafetySettings.model_fields)
        for policy in POLICIES.values():
            assert policy.allow_flag in fields, policy.action

    def test_every_blocked_action_explains_itself(self) -> None:
        for policy in POLICIES.values():
            assert policy.blocked_message.strip()


class TestDryRun:
    def test_dry_run_blocks_submission_outright(self) -> None:
        policy = SafetyPolicy(SafetySettings(dry_run=True))
        reason = policy.check(Action.SUBMIT_APPLICATION, "app-1")
        assert "DRY_RUN" in reason

    def test_dry_run_blocks_submission_even_with_an_approval(self) -> None:
        settings = SafetySettings(dry_run=True, safe_mode=False, require_human_approval=False)
        policy = SafetyPolicy(settings)
        policy.approvals.grant("app-1", granted_by="candidate")
        with pytest.raises(SubmissionBlockedError):
            policy.assert_allowed(Action.SUBMIT_APPLICATION, "app-1")

    def test_submission_needs_a_valid_human_approval(self) -> None:
        settings = SafetySettings(
            dry_run=False,
            safe_mode=False,
            require_human_approval=True,
            allow_final_submission=True,
            allow_form_filling=True,
        )
        policy = SafetyPolicy(settings)
        assert "approval" in policy.check(Action.SUBMIT_APPLICATION, "app-1")
        policy.approvals.grant("app-1", granted_by="candidate")
        assert policy.check(Action.SUBMIT_APPLICATION, "app-1") is None

    def test_an_approval_for_another_application_does_not_help(self) -> None:
        settings = SafetySettings(
            dry_run=False,
            safe_mode=False,
            allow_final_submission=True,
            allow_form_filling=True,
        )
        policy = SafetyPolicy(settings)
        policy.approvals.grant("app-1", granted_by="candidate")
        assert policy.check(Action.SUBMIT_APPLICATION, "app-2") is not None

    def test_approval_is_required_even_when_the_flag_is_off(self) -> None:
        # require_human_approval is the global floor; per-action approval
        # cannot be turned off underneath it.
        settings = SafetySettings(
            dry_run=False,
            safe_mode=False,
            require_human_approval=True,
            allow_final_submission=True,
            allow_form_filling=True,
        )
        policy = SafetyPolicy(settings)
        assert policy.check(Action.NAVIGATE, "app-1") is not None


class TestApprovalStore:
    def test_a_token_is_valid_once(self) -> None:
        store = ApprovalStore()
        store.grant("app-1", granted_by="candidate")
        assert store.get("app-1") is not None
        assert store.consume("app-1") is True
        assert store.get("app-1") is None
        assert store.consume("app-1") is False

    def test_an_expired_token_is_invalid(self) -> None:
        store = ApprovalStore()
        store.grant("app-1", granted_by="candidate", ttl_seconds=-1)
        assert store.get("app-1") is None

    def test_revocation_removes_the_approval(self) -> None:
        store = ApprovalStore()
        store.grant("app-1", granted_by="candidate")
        store.revoke("app-1")
        assert store.get("app-1") is None

    def test_tokens_are_never_persisted_or_logged(self) -> None:
        store = ApprovalStore()
        token = store.grant("app-1", granted_by="candidate")
        rendered = repr(token)
        assert "candidate" not in rendered
        assert "candidate" not in str(store.__dict__.keys())


class TestReadOnlyActions:
    def test_reading_a_page_needs_no_approval_in_safe_mode(self) -> None:
        # Reading is how a human sees what would happen, so it is the one action
        # SAFE_MODE still allows. It is still off by default, because reading
        # requires browser navigation to be enabled at all.
        policy = SafetyPolicy(
            SafetySettings(require_human_approval=False, allow_browser_navigation=True)
        )
        assert policy.is_allowed(Action.READ_PAGE) is True

    def test_page_reads_are_off_until_navigation_is_enabled(self) -> None:
        policy = SafetyPolicy(SafetySettings(require_human_approval=False))
        assert policy.is_allowed(Action.READ_PAGE) is False
        assert "navigation" in policy.check(Action.READ_PAGE)

    def test_navigation_is_blocked_in_safe_mode(self) -> None:
        policy = SafetyPolicy(SafetySettings(require_human_approval=False))
        assert policy.is_allowed(Action.NAVIGATE) is False


class TestVerifiedFactGuard:
    def _facts(self, value: str, status: FactStatus = FactStatus.VERIFIED) -> list[Fact]:
        return [
            Fact(
                field_path="identity.full_name",
                value=value,
                status=status,
                evidence=[
                    Evidence(
                        source_type=EvidenceSourceType.USER_INPUT,
                        source_id="test-session",
                    )
                ],
            )
        ]

    def test_an_ai_actor_cannot_demote_a_verified_fact(self) -> None:
        from core.errors import ImmutableFactError
        from safety.guards import assert_no_fact_mutation

        with pytest.raises(ImmutableFactError):
            assert_no_fact_mutation(
                self._facts("SYNTHETIC NAME"), self._facts("x", FactStatus.INFERRED), actor="ollama"
            )

    def test_an_ai_actor_cannot_delete_a_verified_fact(self) -> None:
        from core.errors import ImmutableFactError
        from safety.guards import assert_no_fact_mutation

        with pytest.raises(ImmutableFactError):
            assert_no_fact_mutation(self._facts("SYNTHETIC NAME"), [], actor="gpt-4")

    def test_a_human_may_demote_their_own_fact(self) -> None:
        from safety.guards import assert_no_fact_mutation

        assert_no_fact_mutation(
            self._facts("SYNTHETIC NAME"),
            self._facts("x", FactStatus.INFERRED),
            actor="candidate",
        )

    def test_an_inferred_fact_is_not_protected(self) -> None:
        from safety.guards import assert_no_fact_mutation

        assert_no_fact_mutation(
            self._facts("A GUESS", FactStatus.INFERRED), [], actor="ollama"
        )

    def test_assert_application_safe_refuses_an_inferred_fact(self) -> None:
        from core.errors import MissingEvidenceError
        from safety.guards import assert_application_safe

        with pytest.raises(MissingEvidenceError):
            assert_application_safe(self._facts("A GUESS", FactStatus.INFERRED)[0])

    def test_assert_application_safe_accepts_a_verified_fact(self) -> None:
        from safety.guards import assert_application_safe

        assert_application_safe(self._facts("SYNTHETIC NAME")[0])

    def test_assert_all_application_safe_stops_at_the_first_bad_fact(self) -> None:
        from core.errors import MissingEvidenceError
        from safety.guards import assert_all_application_safe

        with pytest.raises(MissingEvidenceError):
            assert_all_application_safe(
                [*self._facts("SYNTHETIC NAME"), *self._facts("A GUESS", FactStatus.INFERRED)]
            )

    def test_verified_only_names_the_offending_field(self) -> None:
        from safety.guards import assert_verified_only

        assert_verified_only(self._facts("SYNTHETIC NAME"), "identity.full_name")
        from core.errors import MissingEvidenceError

        with pytest.raises(MissingEvidenceError) as caught:
            assert_verified_only(
                self._facts("A GUESS", FactStatus.INFERRED), "identity.full_name"
            )
        assert caught.value.details["field_path"] == "identity.full_name"


class TestGuardConvenience:
    def test_module_level_assert_allowed_matches_the_method(self) -> None:
        policy = SafetyPolicy(SafetySettings())
        with pytest.raises(SafetyViolationError):
            assert_allowed(policy, Action.UPLOAD_FILE, "app-1")

    def test_read_page_is_not_refused_by_safe_mode(self) -> None:
        policy = SafetyPolicy(
            SafetySettings(require_human_approval=False, allow_browser_navigation=True)
        )
        assert_allowed(policy, Action.READ_PAGE)

    def test_an_unknown_value_is_refused_rather_than_assumed(self) -> None:
        # "unknown means stop" needs one greppable home, so require_known is it.
        from safety.policies import require_known

        with pytest.raises(SafetyViolationError) as caught:
            require_known(None, "identity.full_name")
        assert caught.value.details["field_path"] == "identity.full_name"

    def test_a_supplied_value_passes_require_known(self) -> None:
        from safety.policies import require_known

        assert require_known("SYNTHETIC NAME", "identity.full_name") is None
