"""Route modules, aggregated for inclusion in the application.

Kept as a separate ``include_router`` per resource so each router can be read —
and tested — on its own, and so a new resource is one import plus one line here.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes import jobs, profile, resumes, status as status_routes

__all__ = ["api_router", "health_router"]

#: Resource routes, mounted under ``/api``.
api_router = APIRouter()
api_router.include_router(status_routes.router)
api_router.include_router(profile.router)
api_router.include_router(resumes.router)
api_router.include_router(jobs.router)

#: Liveness at the root, so ``GET /`` answers before the API prefix is known.
health_router = APIRouter()
health_router.add_api_route(
    "/", status_routes.health, methods=["GET"], tags=["system"]
)