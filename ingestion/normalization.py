"""Cross-parser normalization for canonical ingestion payloads."""

from __future__ import annotations

from typing import Any

from ingestion.types import GraphEdge, GraphNode, IngestionResult


def normalize_result(result: IngestionResult) -> IngestionResult:
    """Normalize nodes and edges produced by multiple parsers into one coherent result."""
    normalized = IngestionResult(warnings=list(result.warnings))
    node_index: dict[str, GraphNode] = {}

    for node in result.nodes:
        existing = node_index.get(node.id)
        if existing is None:
            node_index[node.id] = GraphNode(
                label=node.label,
                properties=dict(node.properties),
                provenance=node.provenance,
            )
            continue

        if existing.label != node.label:
            raise ValueError(
                f"Conflicting node labels for canonical ID '{node.id}': '{existing.label}' vs '{node.label}'."
            )

        existing.properties = _merge_node_properties(existing, node)

    normalized.nodes = list(node_index.values())
    valid_node_ids = {node.id for node in normalized.nodes}

    edge_index: dict[tuple[str, str, str], GraphEdge] = {}
    for edge in result.edges:
        if edge.source_id not in valid_node_ids or edge.target_id not in valid_node_ids:
            normalized.warnings.append(
                f"Skipped dangling edge {edge.edge_type} from '{edge.source_id}' to '{edge.target_id}'."
            )
            continue

        edge_key = (edge.source_id, edge.edge_type, edge.target_id)
        existing_edge = edge_index.get(edge_key)
        if existing_edge is None:
            edge_index[edge_key] = GraphEdge(
                edge_type=edge.edge_type,
                source_id=edge.source_id,
                target_id=edge.target_id,
                provenance=edge.provenance,
                properties=dict(edge.properties),
            )
            continue

        existing_edge.properties = _merge_edge_properties(existing_edge, edge)

    normalized.edges = list(edge_index.values())
    return normalized


def normalize_results(*results: IngestionResult) -> IngestionResult:
    """Merge multiple parser results and normalize them as one payload."""
    merged = IngestionResult()
    for result in results:
        merged.extend(result)
    return normalize_result(merged)


def _merge_node_properties(existing: GraphNode, incoming: GraphNode) -> dict[str, Any]:
    """Merge compatible duplicate node properties without losing deterministic detail."""
    merged = dict(existing.properties)
    for key, incoming_value in incoming.properties.items():
        if key not in merged:
            merged[key] = incoming_value
            continue

        existing_value = merged[key]
        if existing_value == incoming_value:
            continue

        if key == "aliases":
            merged[key] = _merge_aliases(existing_value, incoming_value)
            continue

        if isinstance(existing_value, list) and isinstance(incoming_value, list):
            merged[key] = _merge_list_values(existing_value, incoming_value)
            continue

        if existing.label == "Service" and key == "name":
            if str(existing_value).strip() == str(incoming_value).strip():
                merged[key] = str(existing_value).strip()
                continue

        raise ValueError(
            f"Conflicting property '{key}' for node '{existing.id}': {existing_value!r} vs {incoming_value!r}."
        )

    if existing.label == "Service":
        merged = _normalize_service_properties(merged)

    return merged


def _normalize_service_properties(properties: dict[str, Any]) -> dict[str, Any]:
    """Normalize merged Service node properties deterministically."""
    merged = dict(properties)
    aliases = _merge_aliases(merged.get("aliases", []), [])
    name = merged.get("name")
    if isinstance(name, str):
        aliases = [alias for alias in aliases if alias != name]
    if aliases:
        merged["aliases"] = aliases
    elif "aliases" in merged:
        merged.pop("aliases")
    return merged


def _merge_edge_properties(existing: GraphEdge, incoming: GraphEdge) -> dict[str, Any]:
    """Merge duplicate edge properties while preserving provenance trace in properties."""
    merged = dict(existing.properties)
    for key, incoming_value in incoming.properties.items():
        if key not in merged:
            merged[key] = incoming_value
            continue

        existing_value = merged[key]
        if existing_value == incoming_value:
            continue

        if isinstance(existing_value, list) and isinstance(incoming_value, list):
            merged[key] = _merge_list_values(existing_value, incoming_value)
            continue

        raise ValueError(
            "Conflicting properties for duplicate edge "
            f"{existing.edge_type} {existing.source_id} -> {existing.target_id}: "
            f"{key}={existing_value!r} vs {incoming_value!r}."
        )

    merged_sources = _merge_list_values(
        _provenance_sources(existing.properties, existing.provenance.source),
        [incoming.provenance.source],
    )
    if len(merged_sources) > 1:
        merged["merged_provenance_sources"] = merged_sources

    return merged


def _provenance_sources(properties: dict[str, Any], fallback_source: str) -> list[str]:
    """Return existing merged provenance sources or a single fallback source."""
    current = properties.get("merged_provenance_sources")
    if isinstance(current, list) and current:
        return [str(value) for value in current]
    return [fallback_source]


def _merge_aliases(left: Any, right: Any) -> list[str]:
    """Merge service aliases deterministically, preserving first-seen order."""
    merged: list[str] = []
    seen: set[str] = set()
    for candidate in _coerce_string_list(left) + _coerce_string_list(right):
        alias = candidate.strip()
        if not alias or alias in seen:
            continue
        seen.add(alias)
        merged.append(alias)
    return merged


def _merge_list_values(left: list[Any], right: list[Any]) -> list[Any]:
    """Merge list properties deterministically while preserving first-seen order."""
    merged: list[Any] = []
    seen: set[Any] = set()
    for value in left + right:
        marker = _freeze_value(value)
        if marker in seen:
            continue
        seen.add(marker)
        merged.append(value)
    return merged


def _coerce_string_list(value: Any) -> list[str]:
    """Coerce an aliases-like value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _freeze_value(value: Any) -> Any:
    """Create a hashable marker for deterministic list deduplication."""
    if isinstance(value, dict):
        return tuple(sorted((key, _freeze_value(item)) for key, item in value.items()))
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    return value
