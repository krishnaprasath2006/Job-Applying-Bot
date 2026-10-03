"""Request-scoped access to the assembled assistant.

The assistant is constructed once, in the lifespan, and stored on
``app.state``. Routes receive it through :func:`get_assistant` rather than
building their own object graph, which is what keeps a test run and the server
from quietly disagreeing about which SQLite file is in use.

Routes also receive :func:`get_candidate_id` rather than reading
``settings.application.candidate_id`` inline. It is the single place the
"one candidate per profile" convention is expressed at the HTTP edge.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from assistant.app import Assistant

__all__ = ["get_assistant", "get_candidate_id", "AssistantDep", "CandidateIdDep"]


def get_assistant(request: Request) -> Assistant:
    """Return the assistant built at startup.

    Raises:
        RuntimeError: If called before the lifespan ran. Handled centrally as a
            500 rather than being silently replaced with a fresh container.
    """
    assistant = getattr(request.app.state, "assistant", None)
    if assistant is None:  # pragma: no cover - only reachable on a broken lifespan
        raise RuntimeError("the assistant is not available; the server did not start cleanly")
    return assistant


def get_candidate_id(assistant: Annotated[Assistant, Depends(get_assistant)]) -> str:
    """The configured candidate id, read from server-side settings only."""
    return assistant.settings.application.candidate_id


AssistantDep = Annotated[Assistant, Depends(get_assistant)]
CandidateIdDep = Annotated[str, Depends(get_candidate_id)]