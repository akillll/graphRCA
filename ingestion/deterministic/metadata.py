"""Parse metadata.json into Incident, Service, Hypothesis, and Configuration payloads."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ingestion.common.ids import configuration_id, hypothesis_id, incident_id, runbook_id, service_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


def parse_metadata(metadata_path: str | Path) -> IngestionResult:
    """Parse one incident metadata.json file into canonical nodes and edges."""
    path = Path(metadata_path)
    _validate_metadata_path(path)

    metadata = json.loads(path.read_text())
    source = str(path)
    provenance = rule_provenance(source)
    result = IngestionResult()

    incident = GraphNode(
        label="Incident",
        properties={
            "id": incident_id(str(metadata["id"])),
            "title": metadata["title"],
            "difficulty": metadata["difficulty"],
            "service": metadata["service"],
            "severity": metadata["severity"],
            "start_time": metadata["start_time"],
            "end_time": metadata["end_time"],
            **_optional_incident_properties(metadata),
        },
        provenance=provenance,
    )
    result.nodes.append(incident)

    service_names = _collect_service_names(metadata)
    for service_name in service_names:
        service_node = GraphNode(
            label="Service",
            properties={
                "id": service_id(service_name),
                "name": service_name,
            },
            provenance=provenance,
        )
        result.nodes.append(service_node)
        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_ON",
                source_id=incident.id,
                target_id=service_node.id,
                provenance=provenance,
            )
        )

    for hypothesis_text in metadata.get("primary_hypotheses", []):
        hypothesis_node = GraphNode(
            label="Hypothesis",
            properties={
                "id": hypothesis_id(str(metadata["id"]), hypothesis_text),
                "incident_id": incident.id,
                "text": hypothesis_text,
                "status": "candidate",
            },
            provenance=provenance,
        )
        result.nodes.append(hypothesis_node)
        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_IN",
                source_id=hypothesis_node.id,
                target_id=incident.id,
                provenance=provenance,
            )
        )

    for index, context_entry in enumerate(metadata.get("operational_context", [])):
        configuration_node = GraphNode(
            label="Configuration",
            properties=_configuration_properties(metadata, context_entry, index),
            provenance=provenance,
        )
        result.nodes.append(configuration_node)
        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_IN",
                source_id=configuration_node.id,
                target_id=incident.id,
                provenance=provenance,
            )
        )

    for filename in metadata.get("relevant_runbooks", []):
        result.edges.append(
            GraphEdge(
                edge_type="MATCHES",
                source_id=incident.id,
                target_id=runbook_id(filename),
                provenance=provenance,
            )
        )

    return result


def _validate_metadata_path(path: Path) -> None:
    """Reject non-metadata paths and evaluation-only inputs."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as runtime metadata.")
    if path.name != "metadata.json":
        raise ValueError(f"Expected a metadata.json path, got {path.name!r}.")


def _optional_incident_properties(metadata: Mapping[str, Any]) -> dict[str, Any]:
    """Return optional Incident properties when present."""
    properties: dict[str, Any] = {}
    if "summary" in metadata:
        properties["summary"] = metadata["summary"]
    if "tags" in metadata:
        properties["tags"] = metadata["tags"]
    return properties


def _collect_service_names(metadata: Mapping[str, Any]) -> list[str]:
    """Return stable, de-duplicated primary and affected service names."""
    names: list[str] = []
    seen: set[str] = set()

    for raw_name in [metadata.get("service"), *metadata.get("affected_services", [])]:
        if not isinstance(raw_name, str):
            continue
        service_name = raw_name.strip()
        if not service_name or service_name in seen:
            continue
        seen.add(service_name)
        names.append(service_name)

    return names


def _configuration_properties(metadata: Mapping[str, Any], entry: Any, index: int) -> dict[str, Any]:
    """Normalize one operational-context entry into Configuration properties."""
    incident_key = str(metadata["id"])

    if isinstance(entry, str):
        return {
            "id": configuration_id(incident_key, entry),
            "incident_id": incident_id(incident_key),
            "text": entry,
            "kind": "operational_context",
            "source_field": "operational_context",
        }

    if isinstance(entry, Mapping):
        text = str(entry.get("text", f"operational_context_{index}"))
        properties: dict[str, Any] = {
            "id": configuration_id(incident_key, text),
            "incident_id": incident_id(incident_key),
            "text": text,
            "kind": str(entry.get("kind", "operational_context")),
            "source_field": str(entry.get("source_field", "operational_context")),
        }
        if entry.get("service") is not None:
            properties["service"] = entry["service"]
        if entry.get("timestamp") is not None:
            properties["timestamp"] = entry["timestamp"]
        return properties

    text = f"operational_context_{index}"
    return {
        "id": configuration_id(incident_key, text),
        "incident_id": incident_id(incident_key),
        "text": text,
        "kind": "operational_context",
        "source_field": "operational_context",
    }
