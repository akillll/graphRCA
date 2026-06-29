"""Request and response data shapes for GraphRCA HTTP endpoints."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from prompting.types import EvidenceRecord, JsonValue, PromptBaseModel, RcaCitation


NonEmptyString = Annotated[str, Field(min_length=1)]
"""Reusable constrained string type for required API string fields."""


class InvestigateRequest(PromptBaseModel):
    """Incoming RCA investigation request."""

    question: NonEmptyString
    incident_id: str | None = None
    include_debug: bool = False


class InvestigateResponse(PromptBaseModel):
    """Stable RCA response returned by the investigation endpoint."""

    question: NonEmptyString
    incident_id: NonEmptyString
    answer: NonEmptyString
    question_resolution: dict[str, JsonValue] | None = None
    evidence_nodes: list[EvidenceRecord] = Field(default_factory=list)
    hypotheses: list[EvidenceRecord] = Field(default_factory=list)
    citations: list[RcaCitation] = Field(default_factory=list)
    evidence_summary: list[NonEmptyString] = Field(default_factory=list)
    supported_hypotheses: list[NonEmptyString] = Field(default_factory=list)
    ruled_out_hypotheses: list[NonEmptyString] = Field(default_factory=list)
    recommended_actions: list[NonEmptyString] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    confidence_rationale: NonEmptyString
    traversal_summary: dict[str, JsonValue] | None = None
    warnings: list[str] = Field(default_factory=list)


class GraphStatsResponse(PromptBaseModel):
    """Summary counts for the current runtime graph."""

    node_count: int = Field(ge=0)
    edge_count: int = Field(ge=0)
    incident_count: int = Field(ge=0)
    label_counts: dict[str, int] | None = None


class IncidentGraphResponse(PromptBaseModel):
    """Incident-centered graph payload for inspection endpoints."""

    incident_id: NonEmptyString
    nodes: list[EvidenceRecord] = Field(default_factory=list)
    edges: list[EvidenceRecord] = Field(default_factory=list)
    hypotheses: list[EvidenceRecord] = Field(default_factory=list)
    runbooks: list[EvidenceRecord] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ApiErrorResponse(PromptBaseModel):
    """Normalized error envelope returned by API handlers."""

    error: NonEmptyString
    message: NonEmptyString
    details: dict[str, JsonValue] | None = None


__all__ = [
    "ApiErrorResponse",
    "GraphStatsResponse",
    "IncidentGraphResponse",
    "InvestigateRequest",
    "InvestigateResponse",
]
