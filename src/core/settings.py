from dataclasses import dataclass, field
import os

@dataclass
class SafetySettings:
    safe_mode: bool = True
    dry_run: bool = True
    require_human_approval: bool = True
    allow_browser_navigation: bool = False
    allow_file_upload: bool = False
    allow_form_filling: bool = False
    allow_final_submission: bool = False
    max_applications_per_run: int = 5
    applications_today: int = 0
    block_on_captcha: bool = True
    block_on_mfa: bool = True
    record_screenshots: bool = True

@dataclass
class AIProviderConfig:
    provider: str = "huggingface_local"
    model_id: str = "sentence-transformers/all-MiniLM-L6-v2"
    cache_dir: str = os.path.abspath(os.path.join(os.getcwd(), "data", "models", "cache"))
    enabled: bool = True
    device: str = "cpu"
    dimension: int = 384
    runtime: str = "onnx"

@dataclass
class AppSettings:
    safety: SafetySettings = field(default_factory=SafetySettings)
    ai: AIProviderConfig = field(default_factory=AIProviderConfig)

global_settings = AppSettings()
