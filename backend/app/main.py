"""FastAPI application factory."""

from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .api import routes_agents, routes_events, routes_incidents, routes_meta, routes_settings
from .config import get_settings
from .database import init_database

logger = logging.getLogger("deadloop")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="DEADLOOP",
        description=(
            "Deterministic detection of repetitive, unproductive AI-agent execution patterns, "
            "with explainable evidence and human-approved interventions."
        ),
        version=__version__,
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "X-Admin-Token", "X-API-Key"],
    )

    @app.middleware("http")
    async def security_and_size_limits(request: Request, call_next):
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > settings.max_request_bytes:
                    return JSONResponse(
                        status_code=413,
                        content={
                            "detail": (
                                f"Request body exceeds the {settings.max_request_bytes} byte "
                                "limit."
                            )
                        },
                    )
            except ValueError:
                return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length."})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if response.headers.get("content-type", "").startswith("text/html"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
                "script-src 'self'; connect-src 'self'; font-src 'self' data:; "
                "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
            )
        return response

    for router in (
        routes_meta.router,
        routes_events.router,
        routes_agents.router,
        routes_incidents.router,
        routes_settings.router,
    ):
        app.include_router(router)

    @app.on_event("startup")
    def on_startup() -> None:
        settings.validate_runtime()
        if settings.auto_create_schema:
            init_database()
            logger.warning(
                "DEADLOOP_AUTO_CREATE is enabled. For production, run Alembic migrations and "
                "set DEADLOOP_AUTO_CREATE=0."
            )
        if settings.database_url.startswith("sqlite") and settings.environment != "test":
            logger.warning("DEADLOOP is using SQLite; bind to localhost unless you intend otherwise.")

    dist = settings.frontend_dist
    index_file = dist / "index.html"
    if index_file.exists():
        assets = dist / "assets"
        if assets.exists():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "Not found."})
            candidate = (dist / full_path).resolve()
            try:
                candidate.relative_to(dist.resolve())
            except ValueError:
                return JSONResponse(status_code=404, content={"detail": "Not found."})
            if candidate.is_file() and candidate != index_file:
                return FileResponse(candidate)
            return FileResponse(index_file)
    else:

        @app.get("/", include_in_schema=False)
        def root():
            return {
                "name": "DEADLOOP",
                "version": __version__,
                "docs": "/docs",
                "note": "Frontend build not found. Run `npm run build` in frontend/ or use the dev server.",
            }

    return app


app = create_app()
