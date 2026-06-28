"""Shared retrieval data shapes and evidence bundle contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


NodePayload = dict[str, Any]
"""Generic serializable node-like payload used by retrieval without DB coupling."""

EdgePayload = dict[str, Any]
"""Generic serializable edge-like payload used by retrieval without DB coupling."""

EvidenceRecords = list[dict[str, Any]]
"""Generic evidence collection grouped by source type."""


@dataclass(slots=True)
class ExtractedEntities:
    """Deterministic entity hints parsed directly from a user question."""

    raw_question: str
    normalized_question: str = ""
    incident_ids: list[str] = field(default_factory=list)
    services: list[str] = field(default_factory=list)
    symptoms: list[str] = field(default_factory=list)
    time_references: list[str] = field(default_factory=list)
    service_mentions: list[str] = field(default_factory=list)
    symptom_mentions: list[str] = field(default_factory=list)
    operational_terms: list[str] = field(default_factory=list)
    semantic_terms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class IncidentCandidate:
    """Ranked incident match produced during incident resolution."""

    incident_id: str
    score: float
    reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class TraversalResult:
    """Incident-centered evidence neighborhood returned by graph traversal."""

    incident_id: str
    nodes: list[NodePayload] = field(default_factory=list)
    edges: list[EdgePayload] = field(default_factory=list)
    hypotheses: list[dict[str, Any]] = field(default_factory=list)
    runbooks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CitationCandidate:
    """Potential citation mapped back to a concrete evidence record or graph node."""

    citation_id: str
    node_id: str
    node_label: str
    source_type: str
    excerpt: str | None = None
    rationale: str | None = None


@dataclass(slots=True)
class EvidenceBundle:
    """Grouped evidence assembled from traversal output for RCA generation or inspection."""

    incident: dict[str, Any] | None = None
    deployments: EvidenceRecords = field(default_factory=list)
    commits: EvidenceRecords = field(default_factory=list)
    metrics: EvidenceRecords = field(default_factory=list)
    logs: EvidenceRecords = field(default_factory=list)
    timeline: EvidenceRecords = field(default_factory=list)
    services: EvidenceRecords = field(default_factory=list)
    configurations: EvidenceRecords = field(default_factory=list)
    hypotheses: EvidenceRecords = field(default_factory=list)
    runbooks: EvidenceRecords = field(default_factory=list)
    citations: list[CitationCandidate] = field(default_factory=list)


@dataclass(slots=True)
class RetrievalSummary:
    """Top-level retrieval output spanning extraction, resolution, traversal, and assembly."""

    extracted_entities: ExtractedEntities
    incident_candidates: list[IncidentCandidate] = field(default_factory=list)
    selected_incident_id: str | None = None
    traversal_result: TraversalResult | None = None
    evidence_bundle: EvidenceBundle | None = None
    warnings: list[str] = field(default_factory=list)
