"""Tests for candidate profile edit preservation and validation.

These tests verify that:
1. Profile edits are preserved through the model
2. Safety invariants are maintained
3. Approval tracking works correctly
"""

from __future__ import annotations

from core.enums import FactStatus
from core.evidence import FactValue, EvidenceSourceType
from core.errors import ImmutableFactError
from core.settings import SafetySettings
from safety.policies import POLICIES, Action, ApprovalStore, SafetyPolicy
from safety.policies import assert_allowed
from candidate_profile.models import build_empty_profile, with_fact_update


def test_profile_edit_preservation_through_model():
    """Verify that model-level edits preserve user changes."""
    profile = build_empty_profile()
    
    # Edit a field - use with_fact_update instead of model_copy
    edited = with_fact_update(profile, 'identity.full_name', 'John Doe', 
                              status=FactStatus.VERIFIED, 
                              source=EvidenceSourceType.USER_INPUT)
    
    # The edit should be preserved
    assert edited.identity.full_name.value == 'John Doe'
    # Unknown fields should decrease
    assert len(edited.unknown_fields()) < len(profile.unknown_fields())


def test_safety_invariants_unchanged():
    """Verify that the Phase 2 invariants are properly configured."""
    from core.settings import SafetySettings
    
    settings = SafetySettings()
    # All four safety requirements should be True by default
    assert settings.dry_run is True
    assert settings.safe_mode is True
    assert settings.require_human_approval is True
    assert settings.allow_final_submission is False


def test_approval_tracking_basic():
    """Verify that the approval store works correctly."""
    from safety.policies import ApprovalStore
    
    store = ApprovalStore()
    store.grant('app-1', granted_by='candidate')
    assert store.get('app-1') is not None
    assert store.consume('app-1') is True
    assert store.get('app-1') is None
    assert store.consume('app-1') is False


def test_readonly_actions_basic():
    """Verify basic read-only action behavior."""
    from safety.policies import SafetyPolicy, Action
    from core.settings import SafetySettings
    
    # READING is allowed when browser navigation is enabled
    policy = SafetyPolicy(
        SafetySettings(require_human_approval=False, allow_browser_navigation=True)
    )
    assert policy.is_allowed(Action.READ_PAGE) is True
    
    # Without navigation enabled, reading is blocked
    policy2 = SafetyPolicy(SafetySettings(require_human_approval=False))
    assert policy2.is_allowed(Action.READ_PAGE) is False


if __name__ == '__main__':
    test_profile_edit_preservation_through_model()
    test_safety_invariants_unchanged()
    test_approval_tracking_basic()
    test_readonly_actions_basic()
    print()
    print('=== R12.0 Phase 1 Tests PASSED ===')
