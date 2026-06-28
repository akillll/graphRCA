"""Chainlit application entrypoint for GraphRCA.

This module keeps the interactive UI intentionally thin. Each user message maps
to exactly one backend `POST /investigate` request through `ApiClient`, and the
result is rendered with `InvestigationFormatter` into four visible steps.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import chainlit as cl

# Ensure package imports work when Chainlit loads this file as a script target.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from ui.api_client import (
    ApiClient,
    UiApiConnectionError,
    UiApiMalformedResponseError,
    UiApiResponseError,
    UiApiTimeoutError,
)
from ui.formatters import FormattedInvestigation, InvestigationFormatter

class UiApplication:
    """Thin orchestration layer for the Chainlit UI.

    The application owns only:
    - input validation
    - one backend investigation call per user message
    - graceful user-facing error handling
    - rendering formatted investigation steps

    It does not perform any retrieval, prompting, or direct graph access.
    """

    def __init__(
        self,
        api_client: ApiClient | None = None,
        formatter: InvestigationFormatter | None = None,
    ) -> None:
        """Initialize the UI application with thin client-side dependencies."""
        self.api_client = api_client or ApiClient()
        self.formatter = formatter or InvestigationFormatter()

    async def handle_message(self, message: cl.Message) -> None:
        """Validate one user message, call the backend once, and render the result."""
        question = message.content.strip()
        if not question:
            await cl.Message(content="Please enter a non-empty investigation question.").send()
            return

        try:
            response = await asyncio.to_thread(self.api_client.investigate, question)
        except UiApiTimeoutError:
            await cl.Message(
                content="The backend investigation timed out. Check that the backend API and local llama.cpp server are running, then try again."
            ).send()
            return
        except UiApiConnectionError:
            await cl.Message(
                content="The backend API is unavailable. Start the FastAPI server and verify the UI backend URL settings."
            ).send()
            return
        except UiApiMalformedResponseError:
            await cl.Message(
                content="The backend returned an unreadable investigation response. Check the API logs and try again."
            ).send()
            return
        except UiApiResponseError as exc:
            await cl.Message(content=_response_error_message(exc)).send()
            return
        except Exception:
            await cl.Message(
                content="An unexpected UI error occurred while processing the investigation request."
            ).send()
            return

        formatted = self.formatter.format(response)
        await self._render_investigation(formatted)

    async def _render_investigation(self, formatted: FormattedInvestigation) -> None:
        """Render the four investigation sections as visible Chainlit steps."""
        for title, content in (
            ("Incident Resolution", formatted.incident_resolution),
            ("Evidence Summary", formatted.evidence_summary),
            ("Hypothesis Evaluation", formatted.hypothesis_evaluation),
            ("Root Cause Analysis", formatted.root_cause_analysis),
        ):
            with cl.Step(name=title, type="run") as step:
                step.output = content

        await cl.Message(content=formatted.markdown).send()


_APP = UiApplication()


@cl.on_chat_start
async def on_chat_start() -> None:
    """Display a lightweight prompt describing the local demo flow."""
    await cl.Message(
        content=(
            "Ask an investigation question such as "
            '`"Why did catalog-api latency spike on April 21?"`.\n\n'
            "The UI will send one backend `/investigate` request and render the investigation in four steps."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Handle one user message with exactly one backend investigation call."""
    await _APP.handle_message(message)


def _response_error_message(error: UiApiResponseError) -> str:
    """Map backend API errors into short user-facing UI messages."""
    if error.error_code == "incident_not_found":
        return "No matching incident was found for that question. Try a more specific incident, service, or date reference."
    if error.error_code == "graph_unavailable":
        return "The graph backend is unavailable. Check Neo4j connectivity and try again."
    if error.error_code == "model_unavailable":
        return "The local llama.cpp server is unavailable or returned an invalid response. Check the model server and try again."
    if error.error_code == "prompting_failed":
        return "The backend could not complete RCA generation for that investigation. Check the backend logs and try again."
    if error.status_code >= 500:
        return "The backend encountered an internal error while processing the investigation."
    return error.args[0] if error.args else "The investigation request failed."
