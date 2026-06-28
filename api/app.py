"""FastAPI application wiring for GraphRCA.

This module owns only HTTP application setup: FastAPI creation, router
registration, lightweight health endpoints, and global exception handlers.
Business logic remains in the API service layer.
"""

from __future__ import annotations

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from api.config import get_settings
from api.errors import ApiError, UnexpectedApiError, to_error_response
from api.routes.graph import router as graph_router
from api.routes.investigate import router as investigate_router


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
)


@app.exception_handler(ApiError)
def handle_api_error(_: Request, exc: ApiError) -> JSONResponse:
    """Return a stable JSON error envelope for known API exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=to_error_response(exc).model_dump(),
    )


@app.exception_handler(Exception)
def handle_unexpected_error(_: Request, exc: Exception) -> JSONResponse:
    """Return a stable JSON error envelope for uncaught internal failures."""
    error = UnexpectedApiError(
        "An unexpected API error occurred.",
        details={"reason": str(exc)} if settings.app_env != "production" else None,
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=to_error_response(error).model_dump(),
    )


@app.get("/health", summary="Liveness check")
def health() -> dict[str, str]:
    """Return a lightweight liveness signal for the API process."""
    return {
        "status": "ok",
        "service": settings.app_name,
        "environment": settings.app_env,
    }


@app.get("/ready", summary="Readiness check")
def ready() -> dict[str, str | bool]:
    """Return a lightweight readiness signal based on configuration availability."""
    return {
        "status": "ready",
        "service": settings.app_name,
        "environment": settings.app_env,
        "config_loaded": True,
    }


app.include_router(investigate_router)
app.include_router(graph_router)


__all__ = ["app"]
