from enum import Enum
from src.core.errors import SafetyViolationError
from src.core.settings import SafetySettings, global_settings

class Action(str, Enum):
    NAVIGATE = "NAVIGATE"
    READ_DOM = "READ_DOM"
    FILL_FORM = "FILL_FORM"
    UPLOAD_FILE = "UPLOAD_FILE"
    SUBMIT_APPLICATION = "SUBMIT_APPLICATION"

class SafetyPolicy:
    def __init__(self, settings: SafetySettings = None):
        self.settings = settings or global_settings.safety

    def assert_phase2_invariants(self) -> None:
        """Enforces that real application submission remains permanently disabled."""
        if self.settings.allow_final_submission:
            raise SafetyViolationError("Invariant violation: allow_final_submission must remain False.")
        if not self.settings.dry_run:
            raise SafetyViolationError("Invariant violation: dry_run must remain True.")

    def check(self, action: Action) -> None:
        self.assert_phase2_invariants()
        if action == Action.SUBMIT_APPLICATION:
            raise SafetyViolationError("Safety violation: SUBMIT_APPLICATION is permanently blocked.")
        if action == Action.FILL_FORM and not self.settings.allow_form_filling:
            raise SafetyViolationError("Safety violation: Form filling is disabled.")
        if action == Action.UPLOAD_FILE and not self.settings.allow_file_upload:
            raise SafetyViolationError("Safety violation: File upload is disabled.")
        if action == Action.NAVIGATE and not self.settings.allow_browser_navigation:
            raise SafetyViolationError("Safety violation: Browser navigation is disabled.")

global_safety_policy = SafetyPolicy()
