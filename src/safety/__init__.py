"""Safety layer: policies and guards.

This is the only place that decides whether a privileged operation may happen.
Everything defaults to blocked.
"""

from safety.guards import (
    assert_all_application_safe,
    assert_application_safe,
    assert_no_fact_mutation,
    assert_verified_only,
    diff_verified_facts,
)
from safety.policies import (
    POLICIES,
    Action,
    ActionPolicy,
    ApprovalStore,
    ApprovalToken,
    SafetyPolicy,
    assert_allowed,
    guard,
    require_known,
)

__all__ = [
    "Action",
    "ActionPolicy",
    "ApprovalStore",
    "ApprovalToken",
    "POLICIES",
    "SafetyPolicy",
    "assert_all_application_safe",
    "assert_allowed",
    "assert_application_safe",
    "assert_no_fact_mutation",
    "assert_verified_only",
    "diff_verified_facts",
    "guard",
    "require_known",
]
