"""Incident-centered graph traversal and neighborhood expansion."""

from __future__ import annotations

from typing import Any

from ingestion.common.ids import incident_id as canonical_incident_id
from retrieval.client import Neo4jReadClient
from retrieval.queries import (
    COMMITS_FOR_INCIDENT_QUERY,
    DEPLOYMENTS_FOR_INCIDENT_QUERY,
    HYPOTHESES_FOR_INCIDENT_QUERY,
    INCIDENT_BY_ID_QUERY,
    INCIDENT_EVIDENCE_NEIGHBORHOOD_QUERY,
    LOGS_FOR_INCIDENT_QUERY,
    METRICS_FOR_INCIDENT_QUERY,
    RUNBOOKS_FOR_INCIDENT_QUERY,
    SERVICE_TOPOLOGY_FOR_INCIDENT_QUERY,
    TIMELINE_EVENTS_FOR_INCIDENT_QUERY,
)
from retrieval.types import EdgePayload, NodePayload, TraversalResult


class IncidentTraversal:
    """Retrieve a bounded, incident-centered evidence neighborhood from Neo4j."""

    def __init__(self, client: Neo4jReadClient) -> None:
        """Initialize the traversal layer with a read-only Neo4j client."""
        self._client = client

    @classmethod
    def from_env(cls, env_path: str = ".env") -> "IncidentTraversal":
        """Build a traversal helper from `.env`-backed Neo4j settings."""
        return cls(Neo4jReadClient.from_env(env_path))

    def traverse(self, incident_id: str) -> TraversalResult:
        """Return the bounded evidence neighborhood for one selected incident."""
        canonical_id = _to_canonical_incident_id(incident_id)
        node_index: dict[str, NodePayload] = {}
        edge_index: dict[tuple[str, str, str], EdgePayload] = {}
        hypotheses: list[dict[str, Any]] = []
        runbooks: list[dict[str, Any]] = []
        warnings: list[str] = []

        incident_rows = self._client.run_query(INCIDENT_BY_ID_QUERY, {"incident_id": canonical_id})
        if not incident_rows:
            return TraversalResult(
                incident_id=canonical_id,
                warnings=[f"Incident not found: {canonical_id}"],
            )

        for row in incident_rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("incident"))

        self._merge_neighborhood(canonical_id, node_index, edge_index)
        self._merge_deployments(canonical_id, node_index, edge_index)
        commit_count = self._merge_commits(canonical_id, node_index, edge_index)
        metric_count = self._merge_metrics(canonical_id, node_index, edge_index)
        log_count = self._merge_logs(canonical_id, node_index, edge_index)
        timeline_count = self._merge_timeline(canonical_id, node_index, edge_index)
        hypothesis_count = self._merge_hypotheses(canonical_id, node_index, edge_index, hypotheses)
        runbook_count = self._merge_runbooks(canonical_id, node_index, edge_index, runbooks)
        self._merge_service_topology(canonical_id, node_index, edge_index)

        category_counts = {
            "services": _count_labels(node_index, "Service"),
            "deployments": _count_labels(node_index, "Deployment"),
            "commits": commit_count,
            "metrics": metric_count,
            "logs": log_count,
            "timeline events": timeline_count,
            "hypotheses": hypothesis_count,
            "configurations": _count_labels(node_index, "Configuration"),
            "runbooks": runbook_count,
        }
        for label, count in category_counts.items():
            if count == 0:
                warnings.append(f"No {label} found for incident {canonical_id}.")

        if _count_depends_on_edges(edge_index) == 0:
            warnings.append(f"No service topology edges found for incident {canonical_id}.")

        return TraversalResult(
            incident_id=canonical_id,
            nodes=sorted(node_index.values(), key=_node_sort_key),
            edges=sorted(edge_index.values(), key=_edge_sort_key),
            hypotheses=hypotheses,
            runbooks=runbooks,
            warnings=warnings,
        )

    def __call__(self, incident_id: str) -> TraversalResult:
        """Allow traversal to be used as a small callable helper."""
        return self.traverse(incident_id)

    def _merge_neighborhood(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
    ) -> None:
        """Merge the default bounded neighborhood query into the traversal result."""
        rows = self._client.run_query(INCIDENT_EVIDENCE_NEIGHBORHOOD_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("incident"))
            for node in payload.get("nodes", []):
                self._add_node(node_index, node)
            for edge in payload.get("edges", []):
                self._add_edge(edge_index, edge)

    def _merge_deployments(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
    ) -> int:
        """Merge deployment evidence for one incident."""
        rows = self._client.run_query(DEPLOYMENTS_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("deployment"))
            self._add_node(node_index, payload.get("service"))
            self._add_edge(edge_index, payload.get("observed_in_edge"))
            self._add_edge(edge_index, payload.get("observed_on_edge"))
            for commit in payload.get("included_commits", []):
                self._add_node(node_index, commit)
            for edge in payload.get("included_in_edges", []):
                self._add_edge(edge_index, edge)
        return len(rows)

    def _merge_commits(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
    ) -> int:
        """Merge commit evidence for one incident."""
        rows = self._client.run_query(COMMITS_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("commit"))
            self._add_edge(edge_index, payload.get("observed_in_edge"))
            for configuration in payload.get("changed_configurations", []):
                self._add_node(node_index, configuration)
            for edge in payload.get("changed_edges", []):
                self._add_edge(edge_index, edge)
            for deployment in payload.get("deployments", []):
                self._add_node(node_index, deployment)
            for edge in payload.get("included_in_edges", []):
                self._add_edge(edge_index, edge)
        return len(rows)

    def _merge_metrics(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
    ) -> int:
        """Merge metric-series evidence for one incident."""
        rows = self._client.run_query(METRICS_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("metric_series"))
            self._add_node(node_index, payload.get("metric"))
            self._add_node(node_index, payload.get("service"))
            self._add_edge(edge_index, payload.get("observed_in_edge"))
            self._add_edge(edge_index, payload.get("metric_reference_edge"))
            self._add_edge(edge_index, payload.get("observed_on_edge"))
        return len(rows)

    def _merge_logs(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
    ) -> int:
        """Merge log evidence for one incident."""
        rows = self._client.run_query(LOGS_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("log"))
            self._add_node(node_index, payload.get("service"))
            self._add_edge(edge_index, payload.get("observed_in_edge"))
            self._add_edge(edge_index, payload.get("observed_on_edge"))
            for node in payload.get("references", []):
                self._add_node(node_index, node)
            for edge in payload.get("reference_edges", []):
                self._add_edge(edge_index, edge)
        return len(rows)

    def _merge_timeline(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
    ) -> int:
        """Merge timeline evidence for one incident."""
        rows = self._client.run_query(TIMELINE_EVENTS_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("timeline_event"))
            self._add_node(node_index, payload.get("previous_event"))
            self._add_edge(edge_index, payload.get("observed_in_edge"))
            self._add_edge(edge_index, payload.get("occurred_after_edge"))
            for node in payload.get("references", []):
                self._add_node(node_index, node)
            for edge in payload.get("reference_edges", []):
                self._add_edge(edge_index, edge)
        return len(rows)

    def _merge_hypotheses(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
        hypotheses: list[dict[str, Any]],
    ) -> int:
        """Merge hypothesis nodes and their bounded support or rule-out signals."""
        rows = self._client.run_query(HYPOTHESES_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            hypothesis = payload.get("hypothesis")
            self._add_node(node_index, hypothesis)
            self._add_edge(edge_index, payload.get("observed_in_edge"))
            for node in payload.get("supporting_evidence", []):
                self._add_node(node_index, node)
            for edge in payload.get("support_edges", []):
                self._add_edge(edge_index, edge)
            for node in payload.get("ruling_out_evidence", []):
                self._add_node(node_index, node)
            for edge in payload.get("rules_out_edges", []):
                self._add_edge(edge_index, edge)
            if hypothesis is not None:
                hypotheses.append(
                    {
                        "hypothesis": hypothesis,
                        "supporting_evidence": payload.get("supporting_evidence", []),
                        "support_edges": payload.get("support_edges", []),
                        "ruling_out_evidence": payload.get("ruling_out_evidence", []),
                        "rules_out_edges": payload.get("rules_out_edges", []),
                    }
                )
        return len(rows)

    def _merge_runbooks(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
        runbooks: list[dict[str, Any]],
    ) -> int:
        """Merge runbook nodes and their recommended actions."""
        rows = self._client.run_query(RUNBOOKS_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            runbook = payload.get("runbook")
            self._add_node(node_index, runbook)
            self._add_edge(edge_index, payload.get("matched_by_edge"))
            for node in payload.get("recommended_actions", []):
                self._add_node(node_index, node)
            for edge in payload.get("recommendation_edges", []):
                self._add_edge(edge_index, edge)
            if runbook is not None:
                runbooks.append(
                    {
                        "runbook": runbook,
                        "recommended_actions": payload.get("recommended_actions", []),
                        "recommendation_edges": payload.get("recommendation_edges", []),
                    }
                )
        return len(rows)

    def _merge_service_topology(
        self,
        incident_id: str,
        node_index: dict[str, NodePayload],
        edge_index: dict[tuple[str, str, str], EdgePayload],
    ) -> None:
        """Merge bounded service topology for the incident's observed services."""
        rows = self._client.run_query(SERVICE_TOPOLOGY_FOR_INCIDENT_QUERY, {"incident_id": incident_id})
        for row in rows:
            payload = row.get("result", {})
            self._add_node(node_index, payload.get("incident"))
            for node in payload.get("services", []):
                self._add_node(node_index, node)
            for edge in payload.get("edges", []):
                self._add_edge(edge_index, edge)

    @staticmethod
    def _add_node(node_index: dict[str, NodePayload], node: dict[str, Any] | None) -> None:
        """Insert one node payload into the traversal result when present."""
        if not node:
            return
        node_id = str(node.get("node_id", "")).strip()
        if not node_id:
            return
        if node_id not in node_index:
            node_index[node_id] = {
                "node_id": node_id,
                "node_labels": list(node.get("node_labels", [])),
                "properties": dict(node.get("properties", {})),
            }

    @staticmethod
    def _add_edge(edge_index: dict[tuple[str, str, str], EdgePayload], edge: dict[str, Any] | None) -> None:
        """Insert one edge payload into the traversal result when present."""
        if not edge:
            return
        relationship_type = str(edge.get("relationship_type", "")).strip()
        source_id = str(edge.get("source_id", "")).strip()
        target_id = str(edge.get("target_id", "")).strip()
        if not relationship_type or not source_id or not target_id:
            return
        key = (relationship_type, source_id, target_id)
        if key not in edge_index:
            edge_index[key] = {
                "relationship_type": relationship_type,
                "source_id": source_id,
                "target_id": target_id,
                "properties": dict(edge.get("properties", {})),
            }


def _to_canonical_incident_id(value: str) -> str:
    """Normalize a raw fixture incident ID into the canonical graph ID."""
    return value if value.startswith("incident:") else canonical_incident_id(value)


def _count_labels(node_index: dict[str, NodePayload], label: str) -> int:
    """Count nodes having the requested graph label."""
    return sum(1 for node in node_index.values() if label in node.get("node_labels", []))


def _count_depends_on_edges(edge_index: dict[tuple[str, str, str], EdgePayload]) -> int:
    """Count service-topology edges in the current traversal result."""
    return sum(1 for edge in edge_index.values() if edge.get("relationship_type") == "DEPENDS_ON")


def _node_sort_key(node: NodePayload) -> tuple[str, str]:
    """Return a stable sort key for node payloads."""
    labels = node.get("node_labels", [])
    primary_label = labels[0] if labels else ""
    return (primary_label, str(node.get("node_id", "")))


def _edge_sort_key(edge: EdgePayload) -> tuple[str, str, str]:
    """Return a stable sort key for edge payloads."""
    return (
        str(edge.get("relationship_type", "")),
        str(edge.get("source_id", "")),
        str(edge.get("target_id", "")),
    )
