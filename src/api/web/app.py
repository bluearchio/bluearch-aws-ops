"""FastAPI application factory — matching tag-manager-cli patterns.

Usage:
    uvicorn web.app:create_app --factory --host 0.0.0.0 --port 8095 --workers 1
"""

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

from aws.misc.version_controller import CURRENT_VERSION
from utils.logger_config import log


def _get_static_dir() -> Path:
    """Resolve the static directory for both dev and PyInstaller binary."""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "web" / "static"
    return Path(__file__).parent / "static"


def _get_version() -> str:
    return CURRENT_VERSION


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if request.headers.get("x-forwarded-proto") == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def create_app() -> FastAPI:
    """Factory function — creates and configures the FastAPI application."""
    is_dev = _get_version() == "LOCAL"

    app = FastAPI(
        title="BlueArch CLI Dashboard",
        version=_get_version(),
        docs_url="/docs" if is_dev else None,
        redoc_url="/redoc" if is_dev else None,
    )

    # --- Middleware (order matters: first registered = innermost at runtime) ---
    # Runtime flow: CORS -> SecurityHeaders -> route
    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"] if is_dev else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- Exception handlers (ClientError before BotoCoreError — specificity order) ---
    from web.middleware import handle_client_error, handle_no_credentials, handle_botocore_error

    app.add_exception_handler(ClientError, handle_client_error)
    app.add_exception_handler(NoCredentialsError, handle_no_credentials)
    app.add_exception_handler(BotoCoreError, handle_botocore_error)

    # --- Routers ---
    from web.routers.setup import router as setup_router
    from web.routers.health import router as health_router
    from web.routers.system import router as system_router
    from web.routers.recommendations import router as recommendations_router
    from web.routers.scans import router as scans_router
    from web.routers.accounts import router as accounts_router
    from web.routers.resources import router as resources_router
    from web.routers.assume_role import router as assume_role_router
    from web.routers.context import router as context_router
    from web.routers.alarms import router as alarms_router
    from web.routers.optin import router as optin_router
    from web.routers.jobs import router as jobs_router
    from web.routers.event_tracking import router as event_tracking_router
    from web.routers.infrastructure import router as infrastructure_router
    from web.routers.templates import router as templates_router
    from web.routers.graph import router as graph_router
    from web.routers.ai import router as ai_router
    from web.routers.logs import router as logs_router
    from web.routers.notifications import router as notifications_router

    app.include_router(setup_router)
    app.include_router(health_router)
    app.include_router(recommendations_router)
    app.include_router(scans_router)
    app.include_router(accounts_router)
    app.include_router(resources_router)
    app.include_router(assume_role_router)
    app.include_router(context_router)
    app.include_router(alarms_router)
    app.include_router(optin_router)
    app.include_router(jobs_router)
    app.include_router(event_tracking_router)
    app.include_router(infrastructure_router)
    app.include_router(templates_router)
    app.include_router(graph_router)
    app.include_router(ai_router)
    app.include_router(logs_router)
    app.include_router(notifications_router)
    app.include_router(system_router)

    # --- Startup ---
    @app.on_event("startup")
    async def bootstrap():
        _ensure_tables()

    # --- Serve frontend static files (matches Tag Manager CLI) ---
    static_dir = _get_static_dir()
    if static_dir.exists() and (static_dir / "index.html").exists():
        # Mount /assets for Vite's hashed JS/CSS bundles
        assets_dir = static_dir / "assets"
        if assets_dir.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="static-assets")

        # No-cache for index.html; Vite-hashed assets cache-bust naturally
        _NO_CACHE_HEADERS = {
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        }

        # SPA catch-all: serve index.html for any non-API route
        @app.get("/{full_path:path}")
        async def spa_fallback(request: Request, full_path: str):
            """Serve Vue SPA for all non-API routes (client-side routing)."""
            file_path = static_dir / full_path
            # Prevent path traversal: resolved path must stay within static_dir
            try:
                resolved = file_path.resolve()
                static_resolved = static_dir.resolve()
                if not str(resolved).startswith(str(static_resolved)):
                    return FileResponse(str(static_dir / "index.html"), headers=_NO_CACHE_HEADERS)
            except (OSError, ValueError):
                return FileResponse(str(static_dir / "index.html"), headers=_NO_CACHE_HEADERS)
            if full_path and resolved.exists() and resolved.is_file():
                return FileResponse(str(resolved))
            # Fall through to Vue Router — serve index.html
            return FileResponse(str(static_dir / "index.html"), headers=_NO_CACHE_HEADERS)

    return app


def _ensure_tables():
    """Verify bluearch-core on startup; core owns all database tables."""
    import logging
    logger = logging.getLogger("bluearch.web")

    try:
        from utils.core_client import request_core

        health = request_core("GET", "/api/v1/core/health", timeout=3.0)
        logger.info(
            "bluearch-core connected: version=%s db=%s",
            health.get("version", "unknown"),
            health.get("db_status", health.get("database", "unknown")),
        )
    except Exception as e:
        logger.warning("bluearch-core startup verification warning: %s", e)
