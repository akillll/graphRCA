"""Normalized API error types and exception mapping helpers."""

from __future__ import annotations

from typing import Any

from api.types import ApiErrorResponse


class ApiError(Exception):
    """Base API exception carrying a stable message, details, and HTTP status code."""

    error = "api_error"
    default_status_code = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
    ) -> None:
        normalized_message = str(message).strip()
        if not normalized_message:
            raise ValueError("ApiError message must be a non-empty string.")

        self.message = normalized_message
        self.details = dict(details) if details is not None else None
        self.status_code = status_code if status_code is not None else self.default_status_code
        super().__init__(self.message)


class BadRequestError(ApiError):
    """Raised when the API request is invalid or incomplete."""

    error = "bad_request"
    default_status_code = 400


class IncidentNotFoundError(ApiError):
    """Raised when no matching incident can be resolved or the incident is absent."""

    error = "incident_not_found"
    default_status_code = 404


class QuestionOutOfScopeError(ApiError):
    """Raised when a question does not belong to the GraphRCA investigation scope."""

    error = "question_out_of_scope"
    default_status_code = 422


class GraphUnavailableError(ApiError):
    """Raised when the graph backend cannot be reached or queried."""

    error = "graph_unavailable"
    default_status_code = 503


class ModelUnavailableError(ApiError):
    """Raised when the local llama.cpp backend cannot be reached."""

    error = "model_unavailable"
    default_status_code = 503


class PromptingFailedError(ApiError):
    """Raised when prompt assembly, model output parsing, or RCA shaping fails."""

    error = "prompting_failed"
    default_status_code = 502


class UnexpectedApiError(ApiError):
    """Raised when an unexpected internal API failure must be normalized."""

    error = "unexpected_api_error"
    default_status_code = 500


def to_error_response(error: Exception) -> ApiErrorResponse:
    """Convert one exception into the stable API error response envelope."""
    if isinstance(error, ApiError):
        return ApiErrorResponse(
            error=error.error,
            message=error.message,
            details=error.details,
        )

    return ApiErrorResponse(
        error=UnexpectedApiError.error,
        message="An unexpected API error occurred.",
        details=None,
    )


__all__ = [
    "ApiError",
    "BadRequestError",
    "GraphUnavailableError",
    "IncidentNotFoundError",
    "ModelUnavailableError",
    "PromptingFailedError",
    "QuestionOutOfScopeError",
    "UnexpectedApiError",
    "to_error_response",
]
