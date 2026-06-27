"""Parse logs.json into LogEvent payloads and service relationships."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ingestion.common.ids import log_event_id, log_event_sequence, service_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


def parse_logs(logs_path: str | Path, *, incident_id: str) -> IngestionResult:
    """Parse one incident logs.json file into canonical nodes and deterministic edges."""
    path = Path(logs_path)
    _validate_logs_path(path)

    logs = json.loads(path.read_text())
    provenance = rule_provenance(str(path))
    result = IngestionResult()
    incident_key = _incident_key(incident_id)
    seen_services: set[str] = set()
    seen_log_ids: set[str] = set()

    for index, record in enumerate(logs):
        trace_or_sequence = _trace_or_sequence(record, index, incident_key, seen_log_ids)
        log_node = GraphNode(
            label="LogEvent",
            properties=_log_event_properties(record, incident_key, trace_or_sequence),
            provenance=provenance,
        )
        result.nodes.append(log_node)
        seen_log_ids.add(log_node.id)
        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_IN",
                source_id=log_node.id,
                target_id=incident_id,
                provenance=provenance,
            )
        )

        service_name = str(record["service"])
        service_node_id = service_id(service_name)
        if service_node_id not in seen_services:
            result.nodes.append(
                GraphNode(
                    label="Service",
                    properties={
                        "id": service_node_id,
                        "name": service_name,
                    },
                    provenance=provenance,
                )
            )
            seen_services.add(service_node_id)

        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_ON",
                source_id=log_node.id,
                target_id=service_node_id,
                provenance=provenance,
            )
        )

    return result


def _validate_logs_path(path: Path) -> None:
    """Reject non-log paths and evaluation-only inputs."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as runtime logs.")
    if path.name != "logs.json":
        raise ValueError(f"Expected a logs.json path, got {path.name!r}.")


def _log_event_properties(
    record: Mapping[str, Any],
    incident_key: str,
    trace_or_sequence: str,
) -> dict[str, Any]:
    """Build canonical LogEvent node properties from a fixture record."""
    properties: dict[str, Any] = {
        "id": log_event_id(incident_key, str(record["timestamp"]), trace_or_sequence),
        "timestamp": record["timestamp"],
        "level": record["level"],
        "service": record["service"],
        "component": record["component"],
        "message": record["message"],
    }
    if "trace_id" in record and record["trace_id"] is not None:
        properties["trace_id"] = record["trace_id"]
    return properties


def _trace_or_sequence(
    record: Mapping[str, Any],
    index: int,
    incident_key: str,
    seen_log_ids: set[str],
) -> str:
    """Return the stable trace token or deterministic sequence fallback for a log record."""
    trace_id = record.get("trace_id")
    if isinstance(trace_id, str) and trace_id.strip():
        candidate = trace_id.strip()
        candidate_id = log_event_id(incident_key, str(record["timestamp"]), candidate)
        if candidate_id not in seen_log_ids:
            return candidate
        return f"{candidate}:{log_event_sequence(index)}"
    return log_event_sequence(index)


def _incident_key(incident_id: str) -> str:
    """Return the raw incident identifier portion used by canonical ID helpers."""
    if incident_id.startswith("incident:"):
        return incident_id.split("incident:", 1)[1]
    return incident_id
