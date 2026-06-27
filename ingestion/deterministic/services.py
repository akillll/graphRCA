"""Parse services.json into Service payloads, aliases, and DEPENDS_ON edges."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from ingestion.common.ids import service_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


def parse_services(services_path: str | Path) -> IngestionResult:
    """Parse one optional services.json file into canonical Service nodes and DEPENDS_ON edges."""
    path = Path(services_path)
    if not path.exists():
        return IngestionResult()

    _validate_services_path(path)

    payload = json.loads(path.read_text())
    provenance = rule_provenance(str(path))
    result = IngestionResult()
    known_services: dict[str, str] = {}

    for service in payload.get("services", []):
        service_name = str(service["name"])
        node = GraphNode(
            label="Service",
            properties=_service_properties(service),
            provenance=provenance,
        )
        result.nodes.append(node)
        known_services[service_name] = node.id

    for index, dependency in enumerate(payload.get("dependencies", [])):
        from_name = str(dependency.get("from", ""))
        to_name = str(dependency.get("to", ""))
        from_id = known_services.get(from_name)
        to_id = known_services.get(to_name)

        if from_id is None or to_id is None:
            result.warnings.append(
                _missing_dependency_warning(index=index, from_name=from_name, to_name=to_name)
            )
            continue

        edge_properties: dict[str, Any] = {}
        if dependency.get("relationship") is not None:
            edge_properties["relationship"] = dependency["relationship"]

        result.edges.append(
            GraphEdge(
                edge_type="DEPENDS_ON",
                source_id=from_id,
                target_id=to_id,
                provenance=provenance,
                properties=edge_properties,
            )
        )

    return result


def _validate_services_path(path: Path) -> None:
    """Reject evaluation-only or unexpected file names."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as runtime services.")
    if path.name != "services.json":
        raise ValueError(f"Expected a services.json path, got {path.name!r}.")


def _service_properties(service: Mapping[str, Any]) -> dict[str, Any]:
    """Build canonical Service node properties from a fixture service entry."""
    properties: dict[str, Any] = {
        "id": service_id(str(service["name"])),
        "name": service["name"],
    }
    if service.get("type") is not None:
        properties["type"] = service["type"]
    if service.get("environment") is not None:
        properties["environment"] = service["environment"]
    if service.get("tier") is not None:
        properties["tier"] = service["tier"]
    if service.get("aliases") is not None:
        properties["aliases"] = list(service.get("aliases", []))
    return properties


def _missing_dependency_warning(*, index: int, from_name: str, to_name: str) -> str:
    """Return a structured warning message for an invalid dependency endpoint."""
    return (
        "services.json.dependencies["
        f"{index}"
        f"] references undeclared service endpoints from={from_name!r} to={to_name!r}; skipped DEPENDS_ON edge."
    )
