"""Orchestrate prompt construction, model transport, and RCA parsing.

This module wires together the prompting pipeline without introducing CLI,
FastAPI, retrieval logic, or prompt-template business rules beyond deterministic
composition of the existing prompting components.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from prompting.context_builder import PromptContextBuilder
from prompting.llama_client import LlamaCppClient, LlamaCppClientError
from prompting.parser import RcaParser, RcaParsingError
from prompting.templates import render_system_prompt, render_user_prompt
from prompting.types import PromptInput, RcaDraft
from retrieval.types import EvidenceBundle


class PromptGenerationError(RuntimeError):
    """Base error raised when the prompting pipeline cannot complete successfully."""


class PromptContextBuildError(PromptGenerationError):
    """Raised when the evidence bundle cannot be converted into prompt context."""


class PromptTemplateRenderError(PromptGenerationError):
    """Raised when prompt templates cannot be rendered deterministically."""


class PromptModelCallError(PromptGenerationError):
    """Raised when the model transport client fails."""


class PromptParseError(PromptGenerationError):
    """Raised when raw model output cannot be parsed into a structured RCA."""


@dataclass(slots=True)
class PromptGenerator:
    """Coordinate the full prompting workflow from evidence bundle to `RcaDraft`.

    The generator owns no retrieval logic and no prompt business logic of its own.
    It only orchestrates the already isolated steps:

    1. Build `PromptContext`
    2. Render deterministic prompt strings
    3. Construct `PromptInput`
    4. Invoke the llama.cpp transport client
    5. Parse the raw model output into `RcaDraft`
    """

    context_builder: PromptContextBuilder = field(default_factory=PromptContextBuilder)
    llama_client: LlamaCppClient = field(default_factory=LlamaCppClient)
    parser: RcaParser = field(default_factory=RcaParser)
    prompt_metadata: dict[str, Any] = field(default_factory=dict)

    def generate(self, question: str, evidence_bundle: EvidenceBundle) -> RcaDraft:
        """Run the full prompting pipeline and return a structured RCA draft."""
        prompt_input = self.build_prompt_input(question, evidence_bundle)
        raw_model_output = self._call_model(prompt_input)
        return self._parse_output(raw_model_output)

    def build_prompt_input(self, question: str, evidence_bundle: EvidenceBundle) -> PromptInput:
        """Build a deterministic `PromptInput` from one user question and evidence bundle."""
        context = self._build_context(question, evidence_bundle)
        return self._render_prompt_input(context)

    def _build_context(self, question: str, evidence_bundle: EvidenceBundle):
        """Build prompt context and wrap failures with a stage-specific error."""
        try:
            return self.context_builder.build(evidence_bundle, question)
        except Exception as exc:  # pragma: no cover - defensive stage wrapper
            raise PromptContextBuildError(f"Failed to build prompt context: {exc}") from exc

    def _render_prompt_input(self, context) -> PromptInput:
        """Render system and user prompts and package them into `PromptInput`."""
        try:
            system_prompt = render_system_prompt()
            user_prompt = render_user_prompt(context, question=context.question)
            metadata = self._prompt_metadata(context)
            return PromptInput(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                context=context,
                metadata=metadata,
            )
        except Exception as exc:  # pragma: no cover - defensive stage wrapper
            raise PromptTemplateRenderError(f"Failed to render prompt input: {exc}") from exc

    def _call_model(self, prompt_input: PromptInput) -> str:
        """Invoke the llama.cpp client and wrap transport failures."""
        try:
            return self.llama_client.generate(prompt_input)
        except LlamaCppClientError as exc:
            raise PromptModelCallError(f"Model call failed: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive stage wrapper
            raise PromptModelCallError(f"Unexpected model call failure: {exc}") from exc

    def _parse_output(self, raw_model_output: str) -> RcaDraft:
        """Parse raw model output and surface parser failures clearly."""
        try:
            return self.parser.parse(raw_model_output)
        except RcaParsingError as exc:
            raise PromptParseError(f"Failed to parse model output: {exc}") from exc
        except Exception as exc:  # pragma: no cover - defensive stage wrapper
            raise PromptParseError(f"Unexpected parsing failure: {exc}") from exc

    def _prompt_metadata(self, context) -> dict[str, Any]:
        """Return stable metadata describing deterministic prompt construction."""
        evidence_record_counts = {
            "deployments": len(context.deployments),
            "commits": len(context.commits),
            "metrics": len(context.metrics),
            "logs": len(context.logs),
            "timeline": len(context.timeline),
            "services": len(context.services),
            "configurations": len(context.configurations),
            "hypotheses": len(context.hypotheses),
            "runbooks": len(context.runbooks),
            "citations": len(context.citations),
        }

        metadata: dict[str, Any] = {
            "incident_id": context.incident_id,
            "question": context.question,
            "evidence_record_counts": evidence_record_counts,
        }
        metadata.update(self.prompt_metadata)
        return metadata


__all__ = [
    "PromptContextBuildError",
    "PromptGenerationError",
    "PromptGenerator",
    "PromptModelCallError",
    "PromptParseError",
    "PromptTemplateRenderError",
]
