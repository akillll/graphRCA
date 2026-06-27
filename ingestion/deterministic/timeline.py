"""Parse timeline.json into TimelineEvent payloads and ordering edges."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping, Sequence

from ingestion.common.ids import timeline_event_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


def parse_timeline(timeline_path: str | Path, *, incident_id: str) -> IngestionResult:
    """Parse one incident timeline.json file into canonical nodes and deterministic edges."""
    path = Path(timeline_path)
    _validate_timeline_path(path)

    events = json.loads(path.read_text())
    provenance = rule_provenance(str(path))
    result = IngestionResult()
    incident_key = _incident_key(incident_id)
    timeline_node_ids: list[str] = []

    for index, event in enumerate(events):
        timeline_node = GraphNode(
            label="TimelineEvent",
            properties=_timeline_event_properties(event, incident_key, incident_id, index),
            provenance=provenance,
        )
        result.nodes.append(timeline_node)
        timeline_node_ids.append(timeline_node.id)

        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_IN",
                source_id=timeline_node.id,
                target_id=incident_id,
                provenance=provenance,
            )
        )

        if index > 0:
            result.edges.append(
                GraphEdge(
                    edge_type="OCCURRED_AFTER",
                    source_id=timeline_node.id,
                    target_id=timeline_node_ids[index - 1],
                    provenance=provenance,
                )
            )

        references = event.get("references")
        if isinstance(references, Sequence) and not isinstance(references, (str, bytes)):
            for reference in references:
                if not isinstance(reference, str) or not reference.strip():
                    continue
                result.edges.append(
                    GraphEdge(
                        edge_type="REFERENCES",
                        source_id=timeline_node.id,
                        target_id=reference,
                        provenance=provenance,
                    )
                )

    return result


def _validate_timeline_path(path: Path) -> None:
    """Reject non-timeline paths and evaluation-only inputs."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as runtime timeline.")
    if path.name != "timeline.json":
        raise ValueError(f"Expected a timeline.json path, got {path.name!r}.")


def _timeline_event_properties(
    event: Mapping[str, Any],
    incident_key: str,
    incident_id: str,
    index: int,
) -> dict[str, Any]:
    """Build canonical TimelineEvent node properties from a fixture event."""
    properties: dict[str, Any] = {
        "id": timeline_event_id(incident_key, str(event["timestamp"]), index),
        "incident_id": incident_id,
        "timestamp": event["timestamp"],
        "actor": event["actor"],
        "event": event["event"],
    }
    if "event_type" in event:
        properties["event_type"] = event["event_type"]
    if "linked_node_id" in event:
        properties["linked_node_id"] = event["linked_node_id"]
    if "references" in event:
        properties["references"] = list(event.get("references", []))
    return properties


def _incident_key(incident_id: str) -> str:
    """Return the raw incident identifier portion used by canonical ID helpers."""
    if incident_id.startswith("incident:"):
        return incident_id.split("incident:", 1)[1]
    return incident_id
