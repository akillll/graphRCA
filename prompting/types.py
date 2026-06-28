"""Shared prompting data shapes for context assembly, prompt input, and grounded RCA output.

These models are intentionally transport-agnostic. They do not depend on FastAPI,
llama.cpp bindings, HTTP request objects, or CLI concerns. The same types can be
used by prompt builders, parsers, API handlers, and offline evaluation code.
"""

from __future__ import annotations
from typing import Annotated, Any, Literal, TypeAlias
from pydantic import BaseModel, ConfigDict, Field


NonEmptyString = Annotated[str, Field(min_length=1)]
JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = Any
EvidenceRecord: TypeAlias = dict[str, Any]
PromptRole: TypeAlias = Literal["system", "user", "assistant"]



class PromptBaseModel(BaseModel):
    """Base model that enforces strict validation and forbids undeclared fields."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        validate_assignment=True,
    )


class RcaCitation(PromptBaseModel):
    """Citation attached to the generated RCA.

    A citation points back to a concrete graph node or evidence record so the final
    RCA remains replayable and grounded in the evidence graph rather than model-only
    reasoning.
    """

    node_id: NonEmptyString
    node_label: NonEmptyString
    explanation: NonEmptyString


class PromptContext(PromptBaseModel):
    """Structured evidence context used to render a grounded RCA prompt.

    This model is the prompt-facing representation of a retrieval result. It keeps
    evidence grouped by source type so prompt builders can serialize the context in
    a deterministic order while preserving node-level provenance.
    """

    question: NonEmptyString
    incident_id: NonEmptyString
    incident_summary: EvidenceRecord = Field(default_factory=dict)
    deployments: list[EvidenceRecord] = Field(default_factory=list)
    commits: list[EvidenceRecord] = Field(default_factory=list)
    metrics: list[EvidenceRecord] = Field(default_factory=list)
    logs: list[EvidenceRecord] = Field(default_factory=list)
    timeline: list[EvidenceRecord] = Field(default_factory=list)
    services: list[EvidenceRecord] = Field(default_factory=list)
    configurations: list[EvidenceRecord] = Field(default_factory=list)
    hypotheses: list[EvidenceRecord] = Field(default_factory=list)
    runbooks: list[EvidenceRecord] = Field(default_factory=list)
    citations: list[RcaCitation] = Field(default_factory=list)


class PromptInput(PromptBaseModel):
    """Complete prompt payload prepared for a model invocation.

    The prompting layer can build this object before any model client is involved.
    `system_prompt` and `user_prompt` carry the rendered instructions, `context`
    preserves the structured evidence that informed those instructions, and
    `metadata` stores implementation-neutral tracing data such as template versions
    or prompt assembly options.
    """

    system_prompt: NonEmptyString
    user_prompt: NonEmptyString
    context: PromptContext
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PromptMessage(PromptBaseModel):
    """Single chat-style prompt message.

    This shape is reusable across prompt renderers and model clients that expect
    role-based conversational input.
    """

    role: PromptRole
    content: NonEmptyString


class RcaDraft(PromptBaseModel):
    """Structured RCA draft parsed from model output.

    The draft keeps the model response grounded and inspectable by separating the
    likely root cause from supporting evidence, eliminated alternatives, recommended
    actions, and explicit citations. `raw_model_output` preserves the original model
    text for debugging and parser iteration.
    """

    root_cause: NonEmptyString
    evidence_summary: list[NonEmptyString] = Field(default_factory=list)
    supported_hypotheses: list[NonEmptyString] = Field(default_factory=list)
    ruled_out_hypotheses: list[NonEmptyString] = Field(default_factory=list)
    recommended_actions: list[NonEmptyString] = Field(default_factory=list)
    citations: list[RcaCitation] = Field(default_factory=list)
    raw_model_output: NonEmptyString


class PromptingSummary(PromptBaseModel):
    """Compact summary of how a prompt was assembled.

    This summary is intended for logging, debugging, and UI inspection. It explains
    what question was prepared, which incident was selected, how much evidence was
    included, how many prompt messages were produced, and whether any prompt-time
    warnings were raised.
    """

    question: NonEmptyString
    incident_id: NonEmptyString
    message_count: int = Field(ge=0, default=0)
    evidence_record_counts: dict[str, int] = Field(default_factory=dict)
    citation_count: int = Field(ge=0, default=0)
    warnings: list[NonEmptyString] = Field(default_factory=list)
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


__all__ = [
    "EvidenceRecord",
    "JsonScalar",
    "JsonValue",
    "PromptContext",
    "PromptInput",
    "PromptMessage",
    "PromptRole",
    "PromptingSummary",
    "RcaCitation",
    "RcaDraft",
]
