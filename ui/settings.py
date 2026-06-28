"""Environment and runtime settings for the Chainlit UI.

This module provides configuration loading for the thin UI client layer. It is
intentionally independent from Chainlit handlers and HTTP client code so the
same settings contract can be reused by future chat handlers, CLI smoke checks,
or small local scripts that need to talk to the backend API.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field

from prompting.types import PromptBaseModel


DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8000"
"""Default local FastAPI base URL used by the UI in development."""

DEFAULT_INVESTIGATE_ENDPOINT = "/investigate"
"""Default backend path for the main RCA investigation endpoint."""

DEFAULT_REQUEST_TIMEOUT_SECONDS = 120.0
"""Default backend request timeout suitable for local llama.cpp inference."""


class Settings(PromptBaseModel):
    """Validated runtime settings for the UI foundation layer.

    Attributes:
        backend_base_url: Base URL for the backend API service, excluding the
            endpoint path.
        investigate_endpoint: Relative path used for the backend investigation
            endpoint.
        request_timeout_seconds: Timeout budget for one backend request.
    """

    backend_base_url: str = Field(min_length=1)
    investigate_endpoint: str = Field(min_length=1)
    request_timeout_seconds: float = Field(gt=0)


@lru_cache(maxsize=1)
def get_settings(env_path: str | Path = ".env") -> Settings:
    """Load and cache UI settings from `.env` plus process environment overrides.

    Environment variables:
        UI_BACKEND_BASE_URL: Backend API base URL.
        UI_INVESTIGATE_ENDPOINT: Relative investigate endpoint path.
        UI_REQUEST_TIMEOUT_SECONDS: Request timeout in seconds.
    """
    path = Path(env_path)
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise ImportError(
            "The python-dotenv package is required to load UI settings from .env."
        ) from exc

    load_dotenv(dotenv_path=path if path.exists() else None, override=False)

    backend_base_url = _get_str("UI_BACKEND_BASE_URL", default=DEFAULT_BACKEND_BASE_URL).rstrip("/")
    investigate_endpoint = _normalize_endpoint(
        _get_str("UI_INVESTIGATE_ENDPOINT", default=DEFAULT_INVESTIGATE_ENDPOINT)
    )
    request_timeout_seconds = _get_float(
        "UI_REQUEST_TIMEOUT_SECONDS",
        default=DEFAULT_REQUEST_TIMEOUT_SECONDS,
    )

    return Settings(
        backend_base_url=backend_base_url,
        investigate_endpoint=investigate_endpoint,
        request_timeout_seconds=request_timeout_seconds,
    )


def _get_str(name: str, *, default: str) -> str:
    """Return one non-empty string setting or its default."""
    value = os.getenv(name)
    if value is None:
        return default
    stripped = value.strip()
    return stripped or default


def _get_float(name: str, *, default: float) -> float:
    """Return one float setting with explicit validation."""
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = float(value)
    except ValueError as exc:
        raise ValueError(f"Environment setting {name} must be a valid float.") from exc
    if parsed <= 0:
        raise ValueError(f"Environment setting {name} must be greater than zero.")
    return parsed


def _normalize_endpoint(value: str) -> str:
    """Normalize one endpoint path into a stable absolute-path form."""
    stripped = value.strip()
    if not stripped:
        raise ValueError("UI investigate endpoint must be a non-empty string.")
    return stripped if stripped.startswith("/") else f"/{stripped}"


__all__ = ["Settings", "get_settings"]
