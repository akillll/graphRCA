"""UI-facing request and response data shapes for the investigate flow.

These models define the reusable contracts consumed by the thin UI layer. They
mirror the backend `POST /investigate` payload closely while remaining
independent from HTTP clients and Chainlit-specific rendering concerns.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from api.types import InvestigateRequest
from prompting.types import EvidenceRecord, JsonValue, NonEmptyString, PromptBaseModel, RcaCitation


class UiCitation(RcaCitation):
    """Citation rendered in the UI for one grounded RCA claim.

    This reuses the backend citation shape directly so UI code can display node
    identifiers, labels, and short explanations without translation layers.
    """


class UiWarning(PromptBaseModel):
    """One investigation warning surfaced by the backend.

    The backend returns warnings as plain strings. The UI wraps them in a small
    model so renderers can treat warnings as first-class typed objects.
    """

    message: NonEmptyString


class UiHypothesis(PromptBaseModel):
    """Typed hypothesis record rendered in the UI investigation steps.

    This model reflects the compact hypothesis records currently returned by the
    backend investigation service and keeps common evidence-link fields explicit
    for validation and UI formatting.
    """

    node_id: NonEmptyString
    node_labels: list[NonEmptyString] = Field(default_factory=list)
    text: NonEmptyString
    status: str | None = None
    supporting_evidence_ids: list[NonEmptyString] = Field(default_factory=list)
    ruling_out_evidence_ids: list[NonEmptyString] = Field(default_factory=list)
    support_edge_types: list[NonEmptyString] = Field(default_factory=list)
    rule_out_edge_types: list[NonEmptyString] = Field(default_factory=list)
    support_score: float | None = None
    rule_out_score: float | None = None
    reason_codes: list[NonEmptyString] = Field(default_factory=list)
    investigation_outcome: Literal["supported", "ruled_out", "considered"] = "considered"


class UiInvestigateRequest(InvestigateRequest):
    """UI request payload for the backend investigation endpoint.

    This intentionally reuses the backend request contract so the UI submits the
    exact same validated fields accepted by `POST /investigate`.
    """


class UiInvestigateResponse(PromptBaseModel):
    """Validated UI representation of the backend investigation response.

    The model matches the backend response shape while making citations,
    hypotheses, and warnings explicitly typed for downstream UI formatting.
    """

    question: NonEmptyString
    incident_id: NonEmptyString
    answer: NonEmptyString
    question_resolution: dict[str, JsonValue] | None = None
    evidence_nodes: list[EvidenceRecord] = Field(default_factory=list)
    hypotheses: list[UiHypothesis] = Field(default_factory=list)
    citations: list[UiCitation] = Field(default_factory=list)
    evidence_summary: list[NonEmptyString] = Field(default_factory=list)
    supported_hypotheses: list[NonEmptyString] = Field(default_factory=list)
    ruled_out_hypotheses: list[NonEmptyString] = Field(default_factory=list)
    recommended_actions: list[NonEmptyString] = Field(default_factory=list)
    confidence: Literal["low", "medium", "high"]
    confidence_rationale: NonEmptyString
    traversal_summary: dict[str, JsonValue] | None = None
    warnings: list[UiWarning] = Field(default_factory=list)

    @classmethod
    def from_api_payload(cls, payload: dict[str, JsonValue]) -> "UiInvestigateResponse":
        """Build one UI response model from raw backend JSON payload.

        This helper keeps the UI response model aligned with the backend API's
        wire format by translating warning strings into `UiWarning` objects while
        preserving the rest of the payload structure unchanged.
        """
        normalized = dict(payload)
        raw_warnings = normalized.get("warnings", [])
        if isinstance(raw_warnings, list):
            normalized["warnings"] = [
                {"message": item}
                for item in raw_warnings
                if isinstance(item, str) and item.strip()
            ]
        return cls.model_validate(normalized)


__all__ = [
    "UiCitation",
    "UiHypothesis",
    "UiInvestigateRequest",
    "UiInvestigateResponse",
    "UiWarning",
]
