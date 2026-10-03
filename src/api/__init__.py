"""FastAPI boundary over the canonical Python assistant.

This package is an adapter, not a second application. Every route validates
input, delegates to an existing service or repository on
:class:`assistant.app.Assistant`, and serialises what those services return.

Three rules are load-bearing:

1. **No domain logic lives here.** Matching, extraction, evidence rules,
   profile validation, and lifecycle transitions stay in ``jobs/``,
   ``profile/``, ``safety/``, and the repositories. A route that has to make a
   decision is a route that is doing too much.
2. **Safety is server-controlled.** There is no route that writes safety
   settings, and none that starts an application. The only submission route
   exists to consult :class:`safety.policies.SafetyPolicy` and refuse.
3. **Reports are truthful.** ``/health`` is liveness, ``/ready`` proves SQLite
   is actually readable, and ``/status`` reports configuration plus what was
   verified. Nothing asserts a capability that was not exercised.
"""

from __future__ import annotations

from api.app import create_app

__all__ = ["create_app"]