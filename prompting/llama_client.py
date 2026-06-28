"""Transport client for a locally running llama.cpp server.

This module isolates HTTP request/response handling for prompt execution. It does
not build prompts, parse RCA structures, or perform retrieval. Callers are
expected to provide a fully prepared `PromptInput` and receive raw model text.
"""

from __future__ import annotations

import json
import os
import socket
from dataclasses import dataclass, field
from typing import Any
from urllib import error, request

from prompting.types import PromptInput


DEFAULT_ENDPOINT_URL = "http://127.0.0.1:8080/v1/chat/completions"
"""Default local llama.cpp HTTP endpoint using the OpenAI-compatible chat route."""

DEFAULT_TIMEOUT_SECONDS = 60.0
"""Default request timeout for local model generation."""


class LlamaCppClientError(RuntimeError):
    """Base error raised when the llama.cpp transport client cannot complete a request."""


class LlamaCppConnectionError(LlamaCppClientError, ConnectionError):
    """Raised when the local llama.cpp server cannot be reached."""


class LlamaCppTimeoutError(LlamaCppClientError, TimeoutError):
    """Raised when the llama.cpp server does not respond before the configured timeout."""


class LlamaCppResponseError(LlamaCppClientError):
    """Raised when the llama.cpp server returns an invalid or unsuccessful response."""


@dataclass(slots=True)
class LlamaCppClient:
    """HTTP transport client for a locally running llama.cpp server.

    The client converts `PromptInput` objects into the OpenAI-compatible chat
    completion payload commonly exposed by `llama-server`, submits the request,
    and returns the raw generated text from the first completion choice.

    Configuration can be supplied directly or loaded from environment variables:

    - `LLAMA_CPP_ENDPOINT_URL`
    - `LLAMA_CPP_TIMEOUT_SECONDS`
    - `LLAMA_CPP_TEMPERATURE`
    - `LLAMA_CPP_MAX_TOKENS`
    - `LLAMA_CPP_TOP_P`
    - `LLAMA_CPP_TOP_K`
    - `LLAMA_CPP_MIN_P`
    """

    endpoint_url: str = field(default_factory=lambda: os.getenv("LLAMA_CPP_ENDPOINT_URL", DEFAULT_ENDPOINT_URL))
    timeout: float = field(
        default_factory=lambda: float(os.getenv("LLAMA_CPP_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS)))
    )
    generation_parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Normalize configuration and load environment defaults when needed."""
        self.endpoint_url = self.endpoint_url.strip()
        if not self.endpoint_url:
            raise ValueError("LlamaCppClient endpoint_url must be a non-empty string.")
        if self.timeout <= 0:
            raise ValueError("LlamaCppClient timeout must be greater than zero.")
        if not self.generation_parameters:
            self.generation_parameters = self._default_generation_parameters()
        else:
            self.generation_parameters = dict(self.generation_parameters)

    def generate(self, prompt_input: PromptInput) -> str:
        """Submit one prompt input to llama.cpp and return the raw model text.

        Args:
            prompt_input: Fully prepared prompt payload containing system and user
                prompt text plus its originating prompt context.

        Returns:
            The raw generated text from the first response choice.

        Raises:
            LlamaCppConnectionError: The local server could not be reached.
            LlamaCppTimeoutError: The request exceeded the configured timeout.
            LlamaCppResponseError: The server returned an error status or an
                unexpected response body.
        """

        payload = self._build_request_payload(prompt_input)
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            self.endpoint_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with request.urlopen(http_request, timeout=self.timeout) as response:
                response_body = response.read().decode("utf-8")
        except error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            raise LlamaCppResponseError(
                f"llama.cpp request failed with HTTP {exc.code} {exc.reason}: {error_body}"
            ) from exc
        except error.URLError as exc:
            if isinstance(exc.reason, socket.timeout):
                raise LlamaCppTimeoutError(
                    f"llama.cpp request to {self.endpoint_url} timed out after {self.timeout:.1f} seconds."
                ) from exc
            raise LlamaCppConnectionError(
                f"Could not connect to llama.cpp server at {self.endpoint_url}: {exc.reason}"
            ) from exc
        except TimeoutError as exc:
            raise LlamaCppTimeoutError(
                f"llama.cpp request to {self.endpoint_url} timed out after {self.timeout:.1f} seconds."
            ) from exc

        return self._extract_text(response_body)

    def _build_request_payload(self, prompt_input: PromptInput) -> dict[str, Any]:
        """Convert a prompt input into the expected llama.cpp chat request payload."""
        return {
            "messages": [
                {
                    "role": "system",
                    "content": prompt_input.system_prompt,
                },
                {
                    "role": "user",
                    "content": prompt_input.user_prompt,
                },
            ],
            **self.generation_parameters,
        }

    def _extract_text(self, response_body: str) -> str:
        """Extract raw model text from a llama.cpp JSON response body."""
        try:
            payload = json.loads(response_body)
        except json.JSONDecodeError as exc:
            raise LlamaCppResponseError("llama.cpp response was not valid JSON.") from exc

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise LlamaCppResponseError("llama.cpp response did not include any completion choices.")

        first_choice = choices[0]
        if not isinstance(first_choice, dict):
            raise LlamaCppResponseError("llama.cpp response choice had an invalid shape.")

        message = first_choice.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                return content

        text = first_choice.get("text")
        if isinstance(text, str) and text.strip():
            return text

        raise LlamaCppResponseError("llama.cpp response did not contain generated text.")

    def _default_generation_parameters(self) -> dict[str, Any]:
        """Return default generation parameters loaded from environment variables."""
        parameters: dict[str, Any] = {}

        temperature = os.getenv("LLAMA_CPP_TEMPERATURE")
        if temperature is not None:
            parameters["temperature"] = float(temperature)

        max_tokens = os.getenv("LLAMA_CPP_MAX_TOKENS")
        if max_tokens is not None:
            parameters["max_tokens"] = int(max_tokens)

        top_p = os.getenv("LLAMA_CPP_TOP_P")
        if top_p is not None:
            parameters["top_p"] = float(top_p)

        top_k = os.getenv("LLAMA_CPP_TOP_K")
        if top_k is not None:
            parameters["top_k"] = int(top_k)

        min_p = os.getenv("LLAMA_CPP_MIN_P")
        if min_p is not None:
            parameters["min_p"] = float(min_p)

        return parameters


__all__ = [
    "DEFAULT_ENDPOINT_URL",
    "DEFAULT_TIMEOUT_SECONDS",
    "LlamaCppClient",
    "LlamaCppClientError",
    "LlamaCppConnectionError",
    "LlamaCppResponseError",
    "LlamaCppTimeoutError",
]
