"""Parse deployments.json into Deployment payloads and deterministic edges."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ingestion.common.ids import commit_id, deployment_id, service_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


def parse_deployments(
    deployments_path: str | Path,
    *,
    incident_id: str,
    incident_start_time: str,
    incident_end_time: str,
) -> IngestionResult:
    """Parse one incident deployments.json file into canonical nodes and edges."""
    path = Path(deployments_path)
    _validate_deployments_path(path)

    deployments = json.loads(path.read_text())
    provenance = rule_provenance(str(path))
    result = IngestionResult()
    seen_services: set[str] = set()
    incident_start = _parse_timestamp(incident_start_time)
    incident_end = _parse_timestamp(incident_end_time)

    for record in deployments:
        deployment_node = GraphNode(
            label="Deployment",
            properties=_deployment_properties(record),
            provenance=provenance,
        )
        result.nodes.append(deployment_node)

        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_IN",
                source_id=deployment_node.id,
                target_id=incident_id,
                provenance=provenance,
            )
        )

        service_name = str(record["service"])
        if service_name not in seen_services:
            result.nodes.append(
                GraphNode(
                    label="Service",
                    properties={
                        "id": service_id(service_name),
                        "name": service_name,
                    },
                    provenance=provenance,
                )
            )
            seen_services.add(service_name)

        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_ON",
                source_id=deployment_node.id,
                target_id=service_id(service_name),
                provenance=provenance,
            )
        )

        deployment_time = _parse_timestamp(str(record["timestamp"]))
        if deployment_time <= incident_end:
            result.edges.append(
                GraphEdge(
                    edge_type="OCCURRED_AFTER",
                    source_id=incident_id,
                    target_id=deployment_node.id,
                    provenance=provenance,
                )
            )

        if "commit_ids" not in record:
            continue

        for commit_hash in record.get("commit_ids", []):
            result.edges.append(
                GraphEdge(
                    edge_type="INCLUDED_IN",
                    source_id=commit_id(str(commit_hash)),
                    target_id=deployment_node.id,
                    provenance=provenance,
                )
            )

    return result


def _validate_deployments_path(path: Path) -> None:
    """Reject non-deployments paths and evaluation-only inputs."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as runtime deployments.")
    if path.name != "deployments.json":
        raise ValueError(f"Expected a deployments.json path, got {path.name!r}.")


def _deployment_properties(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build canonical Deployment node properties from a fixture record."""
    properties: dict[str, Any] = {
        "id": deployment_id(str(record["deployment_id"])),
        "deployment_id": record["deployment_id"],
        "timestamp": record["timestamp"],
        "service": record["service"],
        "environment": record["environment"],
        "version": record["version"],
        "strategy": record["strategy"],
        "status": record["status"],
    }
    if "initiated_by" in record:
        properties["initiated_by"] = record["initiated_by"]
    if "commit_ids" in record:
        properties["commit_ids"] = list(record.get("commit_ids", []))
    return properties


def _parse_timestamp(value: str) -> datetime:
    """Parse a dataset ISO-8601 timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
