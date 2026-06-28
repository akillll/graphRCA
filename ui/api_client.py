"""Thin HTTP client for the backend `/investigate` endpoint.

This module is the sole HTTP boundary for the UI layer. It validates outgoing
requests, parses backend responses into typed UI models, and converts transport
or backend failures into readable UI exceptions.
"""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from pydantic import ValidationError

from api.types import ApiErrorResponse
from ui.settings import Settings, get_settings
from ui.types import UiInvestigateRequest, UiInvestigateResponse


class UiApiClientError(RuntimeError):
    """Base error raised when the UI client cannot complete an API request."""


class UiApiTimeoutError(UiApiClientError, TimeoutError):
    """Raised when the backend API does not respond before the configured timeout."""


class UiApiConnectionError(UiApiClientError, ConnectionError):
    """Raised when the backend API cannot be reached."""


class UiApiResponseError(UiApiClientError):
    """Raised when the backend returns a 4xx or 5xx error response."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.status_code = status_code
        self.error_code = error_code
        self.details = dict(details) if details is not None else None
        super().__init__(message)


class UiApiMalformedResponseError(UiApiClientError):
    """Raised when the backend returns invalid JSON or an unexpected payload shape."""


@dataclass(slots=True)
class ApiClient:
    """Validated thin client for the backend investigation endpoint.

    The client owns:
    - backend URL configuration
    - request serialization
    - response deserialization
    - transport and backend error normalization

    It does not render UI messages and does not depend on Chainlit handlers.
    """

    settings: Settings | None = None

    def __post_init__(self) -> None:
        """Load default UI settings when none were supplied explicitly."""
        if self.settings is None:
            self.settings = get_settings()

    def investigate(self, question: str) -> UiInvestigateResponse:
        """Send one investigation question to the backend and return a typed response.

        Args:
            question: Natural-language RCA investigation question submitted by the UI.

        Returns:
            A validated `UiInvestigateResponse` parsed from the backend API payload.

        Raises:
            UiApiTimeoutError: The backend did not respond before the configured timeout.
            UiApiConnectionError: The backend could not be reached.
            UiApiResponseError: The backend returned a 4xx or 5xx API error.
            UiApiMalformedResponseError: The backend returned invalid JSON or an
                unexpected response payload shape.
        """
        payload = UiInvestigateRequest(question=question)
        raw_response = self._post_json(
            url=self._investigate_url,
            body=payload.model_dump(),
        )
        return self._parse_success_response(raw_response)

    @property
    def _investigate_url(self) -> str:
        """Return the fully qualified backend investigate URL."""
        assert self.settings is not None
        return f"{self.settings.backend_base_url}{self.settings.investigate_endpoint}"

    def _post_json(self, *, url: str, body: dict[str, Any]) -> dict[str, Any]:
        """Submit one JSON POST request and return the decoded JSON body."""
        assert self.settings is not None

        encoded_body = json.dumps(body).encode("utf-8")
        http_request = request.Request(
            url,
            data=encoded_body,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.settings.request_timeout_seconds) as response:
                return self._decode_json_response(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            response_body = exc.read().decode("utf-8", errors="replace")
            self._raise_http_error(status_code=exc.code, response_body=response_body)
            raise AssertionError("Unreachable after _raise_http_error.")  # pragma: no cover
        except error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise UiApiTimeoutError(
                    f"Backend API request to {url} timed out after {self.settings.request_timeout_seconds:.1f} seconds."
                ) from exc
            raise UiApiConnectionError(f"Could not connect to backend API at {url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise UiApiTimeoutError(
                f"Backend API request to {url} timed out after {self.settings.request_timeout_seconds:.1f} seconds."
            ) from exc

    def _parse_success_response(self, payload: dict[str, Any]) -> UiInvestigateResponse:
        """Validate one successful backend payload as a UI investigation response."""
        try:
            return UiInvestigateResponse.from_api_payload(payload)
        except ValidationError as exc:
            raise UiApiMalformedResponseError(
                f"Backend API returned an invalid investigate response payload: {exc}"
            ) from exc
        except Exception as exc:
            raise UiApiMalformedResponseError(
                f"Backend API returned an unexpected investigate response payload: {exc}"
            ) from exc

    def _raise_http_error(self, *, status_code: int, response_body: str) -> None:
        """Parse one backend error response and raise a readable UI exception."""
        payload = self._decode_json_response(response_body, error_context=True)
        try:
            api_error = ApiErrorResponse.model_validate(payload)
        except ValidationError:
            raise UiApiResponseError(
                f"Backend API returned HTTP {status_code} with an unrecognized error payload.",
                status_code=status_code,
                details={"raw_body": response_body},
            )

        raise UiApiResponseError(
            api_error.message,
            status_code=status_code,
            error_code=api_error.error,
            details=api_error.details,
        )

    def _decode_json_response(self, response_body: str, *, error_context: bool = False) -> dict[str, Any]:
        """Decode one response body as a JSON object."""
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            context = "error response" if error_context else "response"
            raise UiApiMalformedResponseError(f"Backend API returned malformed JSON in the {context}.") from exc

        if not isinstance(payload, dict):
            context = "error response" if error_context else "response"
            raise UiApiMalformedResponseError(f"Backend API returned a non-object JSON {context}.")
        return payload


__all__ = [
    "ApiClient",
    "UiApiClientError",
    "UiApiConnectionError",
    "UiApiMalformedResponseError",
    "UiApiResponseError",
    "UiApiTimeoutError",
]
