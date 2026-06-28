"""Centralized application and dependency configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DEFAULT_APP_NAME = "GraphRCA API"
DEFAULT_APP_ENV = "development"
DEFAULT_NEO4J_DATABASE = "neo4j"
DEFAULT_LLAMA_BASE_URL = "http://127.0.0.1:8080/v1/chat/completions"
DEFAULT_LLAMA_TIMEOUT_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class ApiSettings:
    """Centralized runtime settings for the API layer and its local dependencies."""

    app_name: str
    app_env: str
    neo4j_uri: str
    neo4j_user: str
    neo4j_password: str
    neo4j_database: str
    llama_base_url: str
    llama_timeout_seconds: float
    retrieval_debug_enabled: bool


@lru_cache(maxsize=1)
def get_settings(env_path: str | Path = ".env") -> ApiSettings:
    """Load and cache API settings from `.env` plus process environment overrides."""
    path = Path(env_path)
    try:
        from dotenv import load_dotenv
    except ImportError as exc:
        raise ImportError(
            "The python-dotenv package is required to load API settings from .env."
        ) from exc
    load_dotenv(dotenv_path=path if path.exists() else None, override=False)

    app_name = _get_str("APP_NAME", default=DEFAULT_APP_NAME)
    app_env = _get_str("APP_ENV", default=DEFAULT_APP_ENV)
    neo4j_uri = _get_required_str("NEO4J_URI")
    neo4j_user = _get_required_str("NEO4J_USER", aliases=("NEO4J_USERNAME",))
    neo4j_password = _get_required_str("NEO4J_PASSWORD")
    neo4j_database = _get_str("NEO4J_DATABASE", default=DEFAULT_NEO4J_DATABASE)
    llama_base_url = _get_str(
        "LLAMA_BASE_URL",
        aliases=("LLAMA_CPP_ENDPOINT_URL",),
        default=DEFAULT_LLAMA_BASE_URL,
    )
    llama_timeout_seconds = _get_float(
        "LLAMA_TIMEOUT_SECONDS",
        aliases=("LLAMA_CPP_TIMEOUT_SECONDS",),
        default=DEFAULT_LLAMA_TIMEOUT_SECONDS,
    )
    retrieval_debug_enabled = _get_bool("RETRIEVAL_DEBUG_ENABLED", default=False)

    if llama_timeout_seconds <= 0:
        raise ValueError("LLAMA_TIMEOUT_SECONDS must be greater than zero.")

    return ApiSettings(
        app_name=app_name,
        app_env=app_env,
        neo4j_uri=neo4j_uri,
        neo4j_user=neo4j_user,
        neo4j_password=neo4j_password,
        neo4j_database=neo4j_database,
        llama_base_url=llama_base_url,
        llama_timeout_seconds=llama_timeout_seconds,
        retrieval_debug_enabled=retrieval_debug_enabled,
    )


def _get_required_str(name: str, *, aliases: tuple[str, ...] = ()) -> str:
    """Read one required non-empty string setting."""
    value = _find_env_value(name, aliases=aliases)
    if value is None:
        alias_list = ", ".join((name, *aliases))
        raise ValueError(f"Missing required environment setting: {alias_list}")
    return value


def _get_str(name: str, *, aliases: tuple[str, ...] = (), default: str) -> str:
    """Read one optional string setting with a default."""
    value = _find_env_value(name, aliases=aliases)
    return default if value is None else value


def _get_float(name: str, *, aliases: tuple[str, ...] = (), default: float) -> float:
    """Read one float setting with validation."""
    value = _find_env_value(name, aliases=aliases)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        alias_list = ", ".join((name, *aliases))
        raise ValueError(f"Environment setting {alias_list} must be a valid float.") from exc


def _get_bool(name: str, *, aliases: tuple[str, ...] = (), default: bool) -> bool:
    """Read one boolean setting from common truthy and falsy strings."""
    value = _find_env_value(name, aliases=aliases)
    if value is None:
        return default

    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False

    alias_list = ", ".join((name, *aliases))
    raise ValueError(f"Environment setting {alias_list} must be a valid boolean.")


def _find_env_value(name: str, *, aliases: tuple[str, ...] = ()) -> str | None:
    """Return the first non-empty value from the environment for one setting."""
    for key in (name, *aliases):
        value = os.getenv(key)
        if value is not None:
            stripped = value.strip()
            if stripped:
                return stripped
    return None


__all__ = ["ApiSettings", "get_settings"]
