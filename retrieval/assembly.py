"""Assemble raw traversal output into compact evidence bundles."""

from __future__ import annotations

from typing import Any

from retrieval.types import CitationCandidate, EvidenceBundle, TraversalResult


class EvidenceAssembler:
    """Convert a traversal result into a compact grouped evidence bundle."""

    def assemble(self, traversal_result: TraversalResult) -> EvidenceBundle:
        """Group traversal nodes into a compact evidence bundle."""
        node_by_id = {node["node_id"]: node for node in traversal_result.nodes}
        edges_by_source = _group_edges_by_source(traversal_result.edges)
        edges_by_target = _group_edges_by_target(traversal_result.edges)

        incident = _compact_node(node_by_id.get(traversal_result.incident_id))
        deployments = _sort_records(
            [
                _deployment_record(node, edges_by_source)
                for node in traversal_result.nodes
                if _has_label(node, "Deployment")
            ],
            "timestamp",
        )
        commits = _sort_records(
            [
                _commit_record(node, edges_by_source)
                for node in traversal_result.nodes
                if _has_label(node, "Commit")
            ],
            "timestamp",
        )
        metrics = _sort_records(
            [
                _metric_record(node, edges_by_source)
                for node in traversal_result.nodes
                if _has_label(node, "MetricSeries")
            ],
            "first_anomalous_at",
            fallback_key="window_start",
        )
        logs = _sort_records(
            [
                _log_record(node, edges_by_source)
                for node in traversal_result.nodes
                if _has_label(node, "LogEvent")
            ],
            "timestamp",
        )
        timeline = _sort_records(
            [
                _timeline_record(node, edges_by_source)
                for node in traversal_result.nodes
                if _has_label(node, "TimelineEvent")
            ],
            "timestamp",
        )
        services = _sort_records(
            [
                _service_record(node, edges_by_source, edges_by_target)
                for node in traversal_result.nodes
                if _has_label(node, "Service")
            ],
            "name",
        )
        configurations = _sort_records(
            [
                _configuration_record(node, edges_by_target)
                for node in traversal_result.nodes
                if _has_label(node, "Configuration")
            ],
            "kind",
            fallback_key="text",
        )
        hypotheses = _sort_records(
            [
                _hypothesis_record(entry)
                for entry in traversal_result.hypotheses
            ],
            "status",
            fallback_key="text",
        )
        runbooks = _sort_records(
            [
                _runbook_record(entry)
                for entry in traversal_result.runbooks
            ],
            "filename",
            fallback_key="title",
        )
        citations = _citation_candidates(traversal_result.nodes)

        return EvidenceBundle(
            incident=incident,
            deployments=deployments,
            commits=commits,
            metrics=metrics,
            logs=logs,
            timeline=timeline,
            services=services,
            configurations=configurations,
            hypotheses=hypotheses,
            runbooks=runbooks,
            citations=citations,
        )

    def __call__(self, traversal_result: TraversalResult) -> EvidenceBundle:
        """Allow the assembler to be used as a small callable helper."""
        return self.assemble(traversal_result)


def _compact_node(node: dict[str, Any] | None) -> dict[str, Any] | None:
    """Return a compact node representation suitable for grouped evidence."""
    if node is None:
        return None
    properties = dict(node.get("properties", {}))
    return {
        "node_id": node.get("node_id"),
        "node_labels": list(node.get("node_labels", [])),
        **properties,
    }


def _deployment_record(node: dict[str, Any], edges_by_source: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return a compact deployment evidence record."""
    record = _compact_node(node) or {}
    record["service_ids"] = _related_target_ids(edges_by_source, record["node_id"], "OBSERVED_ON")
    record["commit_ids"] = _related_source_ids_for_target(edges_by_source, record["node_id"], "INCLUDED_IN")
    return record


def _commit_record(node: dict[str, Any], edges_by_source: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return a compact commit evidence record."""
    record = _compact_node(node) or {}
    record["changed_configuration_ids"] = _related_target_ids(edges_by_source, record["node_id"], "CHANGED")
    record["deployment_ids"] = _related_target_ids(edges_by_source, record["node_id"], "INCLUDED_IN")
    return record


def _metric_record(node: dict[str, Any], edges_by_source: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return a compact metric-series evidence record."""
    record = _compact_node(node) or {}
    record["metric_ids"] = _related_target_ids(edges_by_source, record["node_id"], "REFERENCES")
    record["service_ids"] = _related_target_ids(edges_by_source, record["node_id"], "OBSERVED_ON")
    return record


def _log_record(node: dict[str, Any], edges_by_source: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return a compact log evidence record."""
    record = _compact_node(node) or {}
    record["service_ids"] = _related_target_ids(edges_by_source, record["node_id"], "OBSERVED_ON")
    reference_ids = _related_target_ids(edges_by_source, record["node_id"], "REFERENCES")
    if reference_ids:
        record["reference_ids"] = reference_ids
    return record


def _timeline_record(node: dict[str, Any], edges_by_source: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return a compact timeline evidence record."""
    record = _compact_node(node) or {}
    previous_ids = _related_target_ids(edges_by_source, record["node_id"], "OCCURRED_AFTER")
    if previous_ids:
        record["previous_event_ids"] = previous_ids
    reference_ids = _related_target_ids(edges_by_source, record["node_id"], "REFERENCES")
    if reference_ids:
        record["reference_ids"] = reference_ids
    return record


def _service_record(
    node: dict[str, Any],
    edges_by_source: dict[str, list[dict[str, Any]]],
    edges_by_target: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Return a compact service evidence record."""
    record = _compact_node(node) or {}
    depends_on_ids = _related_target_ids(edges_by_source, record["node_id"], "DEPENDS_ON")
    depended_on_by_ids = _related_source_ids(edges_by_target, record["node_id"], "DEPENDS_ON")
    if depends_on_ids:
        record["depends_on_ids"] = depends_on_ids
    if depended_on_by_ids:
        record["depended_on_by_ids"] = depended_on_by_ids
    return record


def _configuration_record(node: dict[str, Any], edges_by_target: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """Return a compact configuration evidence record."""
    record = _compact_node(node) or {}
    changed_by_commit_ids = _related_source_ids(edges_by_target, record["node_id"], "CHANGED")
    if changed_by_commit_ids:
        record["changed_by_commit_ids"] = changed_by_commit_ids
    return record


def _hypothesis_record(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a compact hypothesis bundle entry."""
    hypothesis = _compact_node(entry.get("hypothesis")) or {}
    hypothesis["supporting_evidence_ids"] = [
        node.get("node_id")
        for node in entry.get("supporting_evidence", [])
        if node.get("node_id")
    ]
    hypothesis["ruling_out_evidence_ids"] = [
        node.get("node_id")
        for node in entry.get("ruling_out_evidence", [])
        if node.get("node_id")
    ]
    hypothesis["support_edge_types"] = sorted(
        {
            edge.get("relationship_type")
            for edge in entry.get("support_edges", [])
            if edge.get("relationship_type")
        }
    )
    hypothesis["rule_out_edge_types"] = sorted(
        {
            edge.get("relationship_type")
            for edge in entry.get("rules_out_edges", [])
            if edge.get("relationship_type")
        }
    )
    return hypothesis


def _runbook_record(entry: dict[str, Any]) -> dict[str, Any]:
    """Return a compact runbook bundle entry."""
    runbook = _compact_node(entry.get("runbook")) or {}
    runbook["recommended_action_ids"] = [
        node.get("node_id")
        for node in entry.get("recommended_actions", [])
        if node.get("node_id")
    ]
    return runbook


def _citation_candidates(nodes: list[dict[str, Any]]) -> list[CitationCandidate]:
    """Return citation-ready candidates derived from traversal nodes."""
    ordered_nodes = sorted(nodes, key=lambda node: str(node.get("node_id", "")))
    citations: list[CitationCandidate] = []
    for node in ordered_nodes:
        labels = list(node.get("node_labels", []))
        label = labels[0] if labels else "Node"
        node_id = str(node.get("node_id", ""))
        if not node_id:
            continue
        citations.append(
            CitationCandidate(
                citation_id=node_id,
                node_id=node_id,
                node_label=label,
                source_type=label.lower(),
            )
        )
    return citations


def _group_edges_by_source(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group edges by source node ID."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        source_id = str(edge.get("source_id", ""))
        if not source_id:
            continue
        grouped.setdefault(source_id, []).append(edge)
    return grouped


def _group_edges_by_target(edges: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group edges by target node ID."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for edge in edges:
        target_id = str(edge.get("target_id", ""))
        if not target_id:
            continue
        grouped.setdefault(target_id, []).append(edge)
    return grouped


def _related_target_ids(
    edges_by_source: dict[str, list[dict[str, Any]]],
    source_id: str,
    relationship_type: str,
) -> list[str]:
    """Return stable target IDs for one source and relationship type."""
    return sorted(
        {
            str(edge.get("target_id"))
            for edge in edges_by_source.get(source_id, [])
            if edge.get("relationship_type") == relationship_type and edge.get("target_id")
        }
    )


def _related_source_ids(
    edges_by_target: dict[str, list[dict[str, Any]]],
    target_id: str,
    relationship_type: str,
) -> list[str]:
    """Return stable source IDs for one target and relationship type."""
    return sorted(
        {
            str(edge.get("source_id"))
            for edge in edges_by_target.get(target_id, [])
            if edge.get("relationship_type") == relationship_type and edge.get("source_id")
        }
    )


def _related_source_ids_for_target(
    edges_by_source: dict[str, list[dict[str, Any]]],
    target_id: str,
    relationship_type: str,
) -> list[str]:
    """Return stable source IDs whose edge points to the given target."""
    matches: set[str] = set()
    for source_id, edges in edges_by_source.items():
        for edge in edges:
            if edge.get("relationship_type") == relationship_type and edge.get("target_id") == target_id:
                matches.add(source_id)
    return sorted(matches)


def _sort_records(records: list[dict[str, Any]], primary_key: str, fallback_key: str | None = None) -> list[dict[str, Any]]:
    """Return records sorted by explicit keys where available and node ID otherwise."""
    def sort_key(record: dict[str, Any]) -> tuple[int, str, str]:
        primary = record.get(primary_key)
        if primary not in (None, ""):
            return (0, str(primary), str(record.get("node_id", "")))
        if fallback_key is not None:
            fallback = record.get(fallback_key)
            if fallback not in (None, ""):
                return (1, str(fallback), str(record.get("node_id", "")))
        return (2, "", str(record.get("node_id", "")))

    return sorted(records, key=sort_key)


def _has_label(node: dict[str, Any], label: str) -> bool:
    """Return True when the node has the requested graph label."""
    return label in node.get("node_labels", [])
