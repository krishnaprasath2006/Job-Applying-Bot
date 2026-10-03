"""Service and version identity.

Kept in one place so the liveness report, the OpenAPI document, and the logs
cannot disagree about what is running.
"""

from __future__ import annotations

SERVICE_NAME = "job-applying-bot-api"
SERVICE_VERSION = "1.0.0-r1b"

__all__ = ["SERVICE_NAME", "SERVICE_VERSION"]