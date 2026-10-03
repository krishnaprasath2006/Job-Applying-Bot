class JobAssistantError(Exception):
    """Base exception for all Job Assistant domain errors."""
    pass

class ModelProviderError(JobAssistantError):
    """Base exception for model provider failures."""
    pass

class ModelUnavailableError(ModelProviderError):
    def __init__(self, provider: str, reason: str):
        super().__init__(f"Model provider '{provider}' is unavailable: {reason}")
        self.provider = provider
        self.reason = reason

class ModelLoadError(ModelProviderError):
    def __init__(self, model_id: str, cause: Exception):
        super().__init__(f"Failed to load model '{model_id}': {cause}")
        self.model_id = model_id
        self.cause = cause

class EmbeddingGenerationError(ModelProviderError):
    def __init__(self, model_id: str, message: str):
        super().__init__(f"Embedding generation failed for model '{model_id}': {message}")
        self.model_id = model_id

class DimensionMismatchError(ModelProviderError):
    def __init__(self, expected: int, received: int):
        super().__init__(f"Embedding vector dimension mismatch: expected {expected}, got {received}")
        self.expected = expected
        self.received = received

class SafetyViolationError(JobAssistantError):
    """Raised when an operation violates active SafetyPolicy invariants."""
    pass
