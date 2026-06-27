"""Shared ingestion data shapes and payload contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ingestion.provenance import Provenance


NodeLabel = Literal[
    "Incident",
    "Service",
    "Deployment",
    "Commit",
    "Metric",
    "MetricSeries",
    "LogEvent",
    "TimelineEvent",
    "Runbook",
    "Action",
    "Hypothesis",
    "Configuration",
    "LogPattern",
]

EdgeType = Literal[
    "OBSERVED_IN",
    "OBSERVED_ON",
    "OCCURRED_AFTER",
    "INCLUDED_IN",
    "DEPENDS_ON",
    "MATCHES",
    "REFERENCES",
    "RECOMMENDS",
    "CHANGED",
    "SUPPORTS",
    "RULES_OUT",
]


NODE_REQUIRED_FIELDS: dict[NodeLabel, frozenset[str]] = {
    "Incident": frozenset({"id", "title", "difficulty", "service", "severity", "start_time", "end_time"}),
    "Service": frozenset({"id", "name"}),
    "Deployment": frozenset(
        {"id", "deployment_id", "timestamp", "service", "environment", "version", "strategy", "status"}
    ),
    "Commit": frozenset({"id", "commit_id", "timestamp", "message", "files_changed"}),
    "Metric": frozenset({"id", "name"}),
    "MetricSeries": frozenset(
        {"id", "metric", "incident_id", "window_start", "window_end", "resolution", "points", "unit"}
    ),
    "LogEvent": frozenset({"id", "timestamp", "level", "service", "component", "message"}),
    "TimelineEvent": frozenset({"id", "incident_id", "timestamp", "actor", "event"}),
    "Runbook": frozenset({"id", "filename", "title", "content"}),
    "Action": frozenset({"id", "text", "kind"}),
    "Hypothesis": frozenset({"id", "incident_id", "text", "status"}),
    "Configuration": frozenset({"id", "incident_id", "text", "kind"}),
    "LogPattern": frozenset({"id", "incident_id", "pattern", "level", "first_seen", "count"}),
}

EDGE_REQUIRED_FIELDS: dict[EdgeType, frozenset[str]] = {
    "OBSERVED_IN": frozenset({"source", "created_by", "deterministic"}),
    "OBSERVED_ON": frozenset({"source", "created_by", "deterministic"}),
    "OCCURRED_AFTER": frozenset({"source", "created_by", "deterministic"}),
    "INCLUDED_IN": frozenset({"source", "created_by", "deterministic"}),
    "DEPENDS_ON": frozenset({"source", "created_by", "deterministic"}),
    "MATCHES": frozenset({"source", "created_by", "deterministic"}),
    "REFERENCES": frozenset({"source", "created_by", "deterministic"}),
    "RECOMMENDS": frozenset({"source", "created_by", "deterministic"}),
    "CHANGED": frozenset({"source", "created_by", "deterministic"}),
    "SUPPORTS": frozenset({"source", "created_by", "deterministic"}),
    "RULES_OUT": frozenset({"source", "created_by", "deterministic"}),
}


@dataclass(slots=True)
class GraphNode:
    """Canonical graph node payload independent of any graph database driver."""

    label: NodeLabel
    properties: dict[str, Any]
    provenance: Provenance

    def __post_init__(self) -> None:
        """Validate the node payload shape."""
        validate_node(self)

    @property
    def id(self) -> str:
        """Return the canonical node ID."""
        return str(self.properties["id"])

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable node payload."""
        return {
            "label": self.label,
            "properties": dict(self.properties),
            "provenance": provenance_to_dict(self.provenance),
        }


@dataclass(slots=True)
class GraphEdge:
    """Canonical graph edge payload independent of any graph database driver."""

    edge_type: EdgeType
    source_id: str
    target_id: str
    provenance: Provenance
    properties: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Validate the edge payload shape."""
        validate_edge(self)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable edge payload."""
        return {
            "edge_type": self.edge_type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "properties": dict(self.properties),
            "provenance": provenance_to_dict(self.provenance),
        }


@dataclass(slots=True)
class IngestionResult:
    """Container for nodes, edges, and non-fatal validation issues from one ingestion step."""

    nodes: list[GraphNode] = field(default_factory=list)
    edges: list[GraphEdge] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def extend(self, other: "IngestionResult") -> None:
        """Merge another ingestion result into this one."""
        self.nodes.extend(other.nodes)
        self.edges.extend(other.edges)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable representation of the result."""
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "warnings": list(self.warnings),
        }


def provenance_to_dict(provenance: Provenance) -> dict[str, Any]:
    """Return serializable provenance fields for payload export or validation."""
    payload: dict[str, Any] = {
        "source": provenance.source,
        "created_by": provenance.created_by,
        "deterministic": provenance.deterministic,
    }
    if provenance.model is not None:
        payload["model"] = provenance.model
    if provenance.confidence is not None:
        payload["confidence"] = provenance.confidence
    if provenance.rationale is not None:
        payload["rationale"] = provenance.rationale
    return payload


def validate_node(node: GraphNode) -> None:
    """Validate a GraphNode against the shared contract."""
    required = NODE_REQUIRED_FIELDS[node.label]
    missing = sorted(field_name for field_name in required if field_name not in node.properties)
    if missing:
        raise ValueError(f"Node {node.label} is missing required fields: {', '.join(missing)}")
    if not node.properties.get("id"):
        raise ValueError(f"Node {node.label} must include a non-empty id.")


def validate_edge(edge: GraphEdge) -> None:
    """Validate a GraphEdge against the shared contract."""
    if not edge.source_id:
        raise ValueError(f"Edge {edge.edge_type} must include a non-empty source_id.")
    if not edge.target_id:
        raise ValueError(f"Edge {edge.edge_type} must include a non-empty target_id.")
    required = EDGE_REQUIRED_FIELDS[edge.edge_type]
    provenance_payload = provenance_to_dict(edge.provenance)
    missing = sorted(field_name for field_name in required if field_name not in provenance_payload)
    if missing:
        raise ValueError(f"Edge {edge.edge_type} is missing required provenance fields: {', '.join(missing)}")
