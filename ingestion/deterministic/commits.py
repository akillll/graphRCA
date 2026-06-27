"""Parse commits.json into Commit payloads and deterministic edges."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ingestion.common.ids import commit_id, configuration_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


def parse_commits(commits_path: str | Path, *, incident_id: str) -> IngestionResult:
    """Parse one incident commits.json file into canonical nodes and deterministic edges."""
    path = Path(commits_path)
    _validate_commits_path(path)

    commits = json.loads(path.read_text())
    provenance = rule_provenance(str(path))
    result = IngestionResult()
    incident_key = _incident_key(incident_id)
    seen_configurations: set[str] = set()

    for record in commits:
        commit_node = GraphNode(
            label="Commit",
            properties=_commit_properties(record),
            provenance=provenance,
        )
        result.nodes.append(commit_node)
        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_IN",
                source_id=commit_node.id,
                target_id=incident_id,
                provenance=provenance,
            )
        )

        for file_path in record.get("files_changed", []):
            if not _is_explicit_safe_changed_path(file_path):
                continue

            config_node_id = configuration_id(incident_key, file_path)
            if config_node_id not in seen_configurations:
                result.nodes.append(
                    GraphNode(
                        label="Configuration",
                        properties={
                            "id": config_node_id,
                            "incident_id": incident_id,
                            "text": file_path,
                            "kind": "changed_file",
                            "source_field": "files_changed",
                        },
                        provenance=provenance,
                    )
                )
                seen_configurations.add(config_node_id)

            result.edges.append(
                GraphEdge(
                    edge_type="CHANGED",
                    source_id=commit_node.id,
                    target_id=config_node_id,
                    provenance=provenance,
                )
            )

    return result


def _validate_commits_path(path: Path) -> None:
    """Reject non-commit paths and evaluation-only inputs."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as runtime commits.")
    if path.name != "commits.json":
        raise ValueError(f"Expected a commits.json path, got {path.name!r}.")


def _commit_properties(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build canonical Commit node properties from a fixture record."""
    properties: dict[str, Any] = {
        "id": commit_id(str(record["commit_id"])),
        "commit_id": record["commit_id"],
        "timestamp": record["timestamp"],
        "message": record["message"],
        "files_changed": list(record.get("files_changed", [])),
    }
    if "author" in record:
        properties["author"] = record["author"]
    return properties


def _is_explicit_safe_changed_path(file_path: Any) -> bool:
    """Return True when a changed file path is explicit enough for deterministic CHANGED edges."""
    if not isinstance(file_path, str):
        return False
    normalized = file_path.strip()
    if not normalized:
        return False
    return "/" in normalized and not normalized.endswith("/")


def _incident_key(incident_id: str) -> str:
    """Return the raw incident identifier portion used by canonical ID helpers."""
    if incident_id.startswith("incident:"):
        return incident_id.split("incident:", 1)[1]
    return incident_id
