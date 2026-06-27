"""Validation helpers for canonical ingestion payloads and dataset fixtures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from ingestion.types import (
    EDGE_REQUIRED_FIELDS,
    NODE_REQUIRED_FIELDS,
    EdgeType,
    GraphEdge,
    GraphNode,
    IngestionResult,
    NodeLabel,
    provenance_to_dict,
)


TIMESTAMP_FIELDS_BY_LABEL: dict[str, frozenset[str]] = {
    "Incident": frozenset({"start_time", "end_time"}),
    "Deployment": frozenset({"timestamp"}),
    "Commit": frozenset({"timestamp"}),
    "MetricSeries": frozenset({"window_start", "window_end", "first_anomalous_at"}),
    "LogEvent": frozenset({"timestamp"}),
    "TimelineEvent": frozenset({"timestamp"}),
    "LogPattern": frozenset({"first_seen"}),
    "Configuration": frozenset({"timestamp"}),
    "Action": frozenset({"timestamp"}),
}


@dataclass(slots=True)
class ValidationIssue:
    """Structured validation issue returned to callers."""

    code: str
    message: str
    location: str
    severity: str = "error"


@dataclass(slots=True)
class ValidationReport:
    """Structured validation outcome for nodes, edges, or dataset fixtures."""

    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True when no validation errors were found."""
        return not self.errors

    def add_error(self, code: str, message: str, location: str) -> None:
        """Record a validation error."""
        self.errors.append(ValidationIssue(code=code, message=message, location=location, severity="error"))

    def add_warning(self, code: str, message: str, location: str) -> None:
        """Record a non-fatal validation warning."""
        self.warnings.append(ValidationIssue(code=code, message=message, location=location, severity="warning"))

    def extend(self, other: "ValidationReport") -> None:
        """Merge another validation report into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable validation report."""
        return {
            "is_valid": self.is_valid,
            "errors": [asdict(issue) for issue in self.errors],
            "warnings": [asdict(issue) for issue in self.warnings],
        }


def validate_graph_node(node: GraphNode | Mapping[str, Any]) -> ValidationReport:
    """Validate a canonical graph node payload."""
    return _validate_single_node(node)


def validate_graph_edge(edge: GraphEdge | Mapping[str, Any]) -> ValidationReport:
    """Validate a canonical graph edge payload."""
    return _validate_single_edge(edge)


def validate_result(result: IngestionResult | Mapping[str, Any]) -> ValidationReport:
    """Validate an ingestion result before any graph database write."""
    report = ValidationReport()
    nodes = list(_result_nodes(result))
    edges = list(_result_edges(result))

    node_index: dict[str, str] = {}
    alias_index: dict[str, str] = {}

    for position, node in enumerate(nodes):
        node_report = _validate_single_node(node, location=f"nodes[{position}]")
        report.extend(node_report)

        payload = _node_payload(node)
        if not payload:
            continue

        node_id = payload["properties"].get("id")
        label = payload["label"]
        if isinstance(node_id, str) and node_id:
            previous_label = node_index.get(node_id)
            if previous_label is None:
                node_index[node_id] = label
            elif previous_label != label:
                report.add_error(
                    "duplicate_node_id_conflicting_label",
                    f"Node ID '{node_id}' is used by both '{previous_label}' and '{label}'.",
                    f"nodes[{position}].properties.id",
                )

        if label == "Service":
            _collect_service_alias_issues(payload, alias_index, report, position)

    for position, edge in enumerate(edges):
        edge_report = _validate_single_edge(edge, location=f"edges[{position}]")
        report.extend(edge_report)

        payload = _edge_payload(edge)
        if not payload:
            continue

        source_id = payload["source_id"]
        target_id = payload["target_id"]
        if source_id and source_id not in node_index:
            report.add_error(
                "dangling_edge_source",
                f"Edge source '{source_id}' does not exist in the node set.",
                f"edges[{position}].source_id",
            )
        if target_id and target_id not in node_index:
            report.add_error(
                "dangling_edge_target",
                f"Edge target '{target_id}' does not exist in the node set.",
                f"edges[{position}].target_id",
            )

    return report


def validate_deployment_commit_ids(
    deployments: Sequence[Mapping[str, Any]],
    commits: Sequence[Mapping[str, Any]],
    *,
    location: str = "deployments.json",
) -> ValidationReport:
    """Validate that deployment commit references exist in the incident commit set."""
    report = ValidationReport()
    commit_ids = {str(commit.get("commit_id")) for commit in commits if commit.get("commit_id")}

    for deployment_index, deployment in enumerate(deployments):
        for commit_index, commit_id in enumerate(deployment.get("commit_ids", [])):
            if commit_id not in commit_ids:
                report.add_error(
                    "missing_deployment_commit",
                    f"Deployment references unknown commit_id '{commit_id}'.",
                    f"{location}[{deployment_index}].commit_ids[{commit_index}]",
                )

    return report


def validate_metadata_runbooks(
    metadata: Mapping[str, Any],
    runbooks_dir: str | Path,
    *,
    location: str = "metadata.json",
) -> ValidationReport:
    """Validate that relevant runbooks declared in metadata exist on disk."""
    report = ValidationReport()
    runbooks_root = Path(runbooks_dir)

    for index, filename in enumerate(metadata.get("relevant_runbooks", [])):
        if not (runbooks_root / filename).is_file():
            report.add_error(
                "missing_runbook_file",
                f"Metadata references missing runbook '{filename}'.",
                f"{location}.relevant_runbooks[{index}]",
            )

    return report


def validate_services_topology(
    services_payload: Mapping[str, Any],
    *,
    location: str = "services.json",
) -> ValidationReport:
    """Validate that services.json dependency endpoints resolve to declared services."""
    report = ValidationReport()
    services = services_payload.get("services", [])
    dependencies = services_payload.get("dependencies", [])
    known_names = {str(service.get("name")) for service in services if service.get("name")}

    for index, dependency in enumerate(dependencies):
        source_name = dependency.get("from")
        target_name = dependency.get("to")
        if source_name not in known_names:
            report.add_error(
                "unknown_dependency_source",
                f"Dependency source '{source_name}' is not declared in services.json.",
                f"{location}.dependencies[{index}].from",
            )
        if target_name not in known_names:
            report.add_error(
                "unknown_dependency_target",
                f"Dependency target '{target_name}' is not declared in services.json.",
                f"{location}.dependencies[{index}].to",
            )

    return report


def validate_runtime_input_paths(
    paths: Sequence[str | Path],
    *,
    location: str = "runtime_inputs",
) -> ValidationReport:
    """Validate that runtime ingestion paths do not include evaluation-only files."""
    report = ValidationReport()

    for index, path_value in enumerate(paths):
        path = Path(path_value)
        if path.name == "expected_rca.json":
            report.add_error(
                "evaluation_file_in_runtime_input",
                "expected_rca.json is evaluation-only and must not be treated as runtime input.",
                f"{location}[{index}]",
            )

    return report


def _validate_single_node(node: GraphNode | Mapping[str, Any], location: str = "node") -> ValidationReport:
    """Validate one node payload and return a structured report."""
    report = ValidationReport()
    payload = _node_payload(node)
    if not payload:
        report.add_error("invalid_node_payload", "Node payload must expose label, properties, and provenance.", location)
        return report

    label = payload["label"]
    properties = payload["properties"]
    provenance = payload["provenance"]

    if label not in NODE_REQUIRED_FIELDS:
        report.add_error(
            "unknown_node_label",
            f"Unsupported node label '{label}'. Allowed labels: {', '.join(sorted(NODE_REQUIRED_FIELDS))}.",
            f"{location}.label",
        )
        return report

    _validate_required_fields(
        report,
        required_fields=NODE_REQUIRED_FIELDS[label],
        actual_fields=properties,
        location=f"{location}.properties",
        kind="node",
        subject=label,
    )
    _validate_provenance_payload(report, provenance, location=f"{location}.provenance")
    _validate_timestamp_fields(
        report,
        properties,
        TIMESTAMP_FIELDS_BY_LABEL.get(label, frozenset()),
        location=f"{location}.properties",
    )
    _validate_metric_series_points(report, label, properties, location=f"{location}.properties")

    return report


def _validate_single_edge(edge: GraphEdge | Mapping[str, Any], location: str = "edge") -> ValidationReport:
    """Validate one edge payload and return a structured report."""
    report = ValidationReport()
    payload = _edge_payload(edge)
    if not payload:
        report.add_error(
            "invalid_edge_payload",
            "Edge payload must expose edge_type, source_id, target_id, and provenance.",
            location,
        )
        return report

    edge_type = payload["edge_type"]
    source_id = payload["source_id"]
    target_id = payload["target_id"]
    provenance = payload["provenance"]

    if edge_type not in EDGE_REQUIRED_FIELDS:
        report.add_error(
            "unknown_edge_type",
            f"Unsupported edge type '{edge_type}'. Allowed edge types: {', '.join(sorted(EDGE_REQUIRED_FIELDS))}.",
            f"{location}.edge_type",
        )
        return report

    if not isinstance(source_id, str) or not source_id.strip():
        report.add_error("empty_edge_source_id", "Edge source_id must be a non-empty string.", f"{location}.source_id")
    if not isinstance(target_id, str) or not target_id.strip():
        report.add_error("empty_edge_target_id", "Edge target_id must be a non-empty string.", f"{location}.target_id")

    _validate_required_fields(
        report,
        required_fields=EDGE_REQUIRED_FIELDS[edge_type],
        actual_fields=provenance,
        location=f"{location}.provenance",
        kind="edge",
        subject=edge_type,
    )
    _validate_provenance_payload(report, provenance, location=f"{location}.provenance")

    return report


def _validate_required_fields(
    report: ValidationReport,
    *,
    required_fields: frozenset[str],
    actual_fields: Mapping[str, Any],
    location: str,
    kind: str,
    subject: str,
) -> None:
    """Validate presence of required fields on a payload mapping."""
    missing = sorted(field_name for field_name in required_fields if field_name not in actual_fields)
    if missing:
        report.add_error(
            f"missing_{kind}_fields",
            f"{subject} is missing required fields: {', '.join(missing)}.",
            location,
        )


def _validate_timestamp_fields(
    report: ValidationReport,
    properties: Mapping[str, Any],
    timestamp_fields: frozenset[str],
    *,
    location: str,
) -> None:
    """Validate parseability of known timestamp-like fields."""
    for field_name in timestamp_fields:
        value = properties.get(field_name)
        if value is None:
            continue
        if not _is_parseable_timestamp(value):
            report.add_error(
                "invalid_timestamp",
                f"Field '{field_name}' must contain an ISO-8601 timestamp, got {value!r}.",
                f"{location}.{field_name}",
            )


def _validate_metric_series_points(
    report: ValidationReport,
    label: str,
    properties: Mapping[str, Any],
    *,
    location: str,
) -> None:
    """Validate point timestamp shape for MetricSeries payloads."""
    if label != "MetricSeries":
        return

    points = properties.get("points")
    if not isinstance(points, Sequence) or isinstance(points, (str, bytes)):
        report.add_error("invalid_metric_points", "MetricSeries.points must be a sequence of [timestamp, value] pairs.", f"{location}.points")
        return

    for index, point in enumerate(points):
        if not isinstance(point, Sequence) or isinstance(point, (str, bytes)) or len(point) < 1:
            report.add_error(
                "invalid_metric_point",
                "MetricSeries point must be a sequence whose first element is a timestamp.",
                f"{location}.points[{index}]",
            )
            continue
        if not _is_parseable_timestamp(point[0]):
            report.add_error(
                "invalid_metric_point_timestamp",
                f"MetricSeries point timestamp must be ISO-8601, got {point[0]!r}.",
                f"{location}.points[{index}][0]",
            )


def _validate_provenance_payload(report: ValidationReport, provenance: Mapping[str, Any], *, location: str) -> None:
    """Validate shared provenance requirements on nodes and edges."""
    created_by = provenance.get("created_by")
    deterministic = provenance.get("deterministic")
    source = provenance.get("source")

    if not isinstance(source, str) or not source.strip():
        report.add_error("invalid_provenance_source", "Provenance source must be a non-empty string.", f"{location}.source")

    if created_by not in {"rule", "llm"}:
        report.add_error(
            "invalid_created_by",
            "Provenance created_by must be 'rule' or 'llm'.",
            f"{location}.created_by",
        )
        return

    if not isinstance(deterministic, bool):
        report.add_error(
            "invalid_deterministic_flag",
            "Provenance deterministic must be a boolean.",
            f"{location}.deterministic",
        )

    if created_by == "rule":
        if deterministic is not True:
            report.add_error(
                "rule_provenance_not_deterministic",
                "Rule-created provenance must set deterministic to True.",
                f"{location}.deterministic",
            )
        for field_name in ("model", "confidence", "rationale"):
            if provenance.get(field_name) is not None:
                report.add_error(
                    "unexpected_rule_provenance_field",
                    f"Rule provenance must not include '{field_name}'.",
                    f"{location}.{field_name}",
                )
        return

    model = provenance.get("model")
    confidence = provenance.get("confidence")
    rationale = provenance.get("rationale")
    if not isinstance(model, str) or not model.strip():
        report.add_error("missing_llm_model", "LLM provenance requires a non-empty model.", f"{location}.model")
    if not isinstance(confidence, (float, int)) or not 0.0 <= float(confidence) <= 1.0:
        report.add_error(
            "invalid_llm_confidence",
            "LLM provenance confidence must be a number between 0.0 and 1.0.",
            f"{location}.confidence",
        )
    if not isinstance(rationale, str) or not rationale.strip():
        report.add_error(
            "missing_llm_rationale",
            "LLM provenance requires a non-empty rationale.",
            f"{location}.rationale",
        )


def _collect_service_alias_issues(
    node_payload: Mapping[str, Any],
    alias_index: dict[str, str],
    report: ValidationReport,
    position: int,
) -> None:
    """Validate duplicate alias conflicts across Service nodes."""
    service_id = node_payload["properties"].get("id")
    service_name = node_payload["properties"].get("name")
    aliases = node_payload["properties"].get("aliases", [])

    if service_name:
        _register_alias(str(service_name), str(service_id), alias_index, report, f"nodes[{position}].properties.name")

    if aliases is None:
        return
    if not isinstance(aliases, Sequence) or isinstance(aliases, (str, bytes)):
        report.add_error(
            "invalid_service_aliases",
            "Service aliases must be a sequence of strings when present.",
            f"nodes[{position}].properties.aliases",
        )
        return

    for alias_index_position, alias in enumerate(aliases):
        if not isinstance(alias, str) or not alias.strip():
            report.add_error(
                "invalid_service_alias",
                "Service alias must be a non-empty string.",
                f"nodes[{position}].properties.aliases[{alias_index_position}]",
            )
            continue
        _register_alias(
            alias,
            str(service_id),
            alias_index,
            report,
            f"nodes[{position}].properties.aliases[{alias_index_position}]",
        )


def _register_alias(
    alias: str,
    owner_id: str,
    alias_index: dict[str, str],
    report: ValidationReport,
    location: str,
) -> None:
    """Track a service name or alias and report conflicts."""
    key = alias.strip().lower()
    if not key:
        return
    previous_owner = alias_index.get(key)
    if previous_owner is None:
        alias_index[key] = owner_id
        return
    if previous_owner != owner_id:
        report.add_error(
            "service_alias_conflict",
            f"Alias '{alias}' is claimed by both '{previous_owner}' and '{owner_id}'.",
            location,
        )


def _node_payload(node: GraphNode | Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize a node object or dict-like payload into a validation mapping."""
    if isinstance(node, GraphNode):
        return {
            "label": node.label,
            "properties": node.properties,
            "provenance": provenance_to_dict(node.provenance),
        }
    if isinstance(node, Mapping):
        label = node.get("label")
        properties = node.get("properties")
        provenance = node.get("provenance")
        if isinstance(provenance, Mapping):
            normalized_provenance = dict(provenance)
        else:
            normalized_provenance = _normalize_provenance_obj(provenance)
        if isinstance(properties, Mapping):
            return {
                "label": label,
                "properties": dict(properties),
                "provenance": normalized_provenance,
            }
    return None


def _edge_payload(edge: GraphEdge | Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize an edge object or dict-like payload into a validation mapping."""
    if isinstance(edge, GraphEdge):
        return {
            "edge_type": edge.edge_type,
            "source_id": edge.source_id,
            "target_id": edge.target_id,
            "provenance": provenance_to_dict(edge.provenance),
        }
    if isinstance(edge, Mapping):
        provenance = edge.get("provenance")
        if isinstance(provenance, Mapping):
            normalized_provenance = dict(provenance)
        else:
            normalized_provenance = _normalize_provenance_obj(provenance)
        return {
            "edge_type": edge.get("edge_type"),
            "source_id": edge.get("source_id"),
            "target_id": edge.get("target_id"),
            "provenance": normalized_provenance,
        }
    return None


def _normalize_provenance_obj(provenance: Any) -> dict[str, Any]:
    """Best-effort normalization for provenance-like objects."""
    if provenance is None:
        return {}
    if hasattr(provenance, "source") and hasattr(provenance, "created_by") and hasattr(provenance, "deterministic"):
        return {
            "source": getattr(provenance, "source"),
            "created_by": getattr(provenance, "created_by"),
            "deterministic": getattr(provenance, "deterministic"),
            "model": getattr(provenance, "model", None),
            "confidence": getattr(provenance, "confidence", None),
            "rationale": getattr(provenance, "rationale", None),
        }
    return {}


def _result_nodes(result: IngestionResult | Mapping[str, Any]) -> Sequence[GraphNode | Mapping[str, Any]]:
    """Return result nodes from a typed result or dict-like payload."""
    if isinstance(result, IngestionResult):
        return result.nodes
    if isinstance(result, Mapping):
        nodes = result.get("nodes", [])
        return nodes if isinstance(nodes, Sequence) else []
    return []


def _result_edges(result: IngestionResult | Mapping[str, Any]) -> Sequence[GraphEdge | Mapping[str, Any]]:
    """Return result edges from a typed result or dict-like payload."""
    if isinstance(result, IngestionResult):
        return result.edges
    if isinstance(result, Mapping):
        edges = result.get("edges", [])
        return edges if isinstance(edges, Sequence) else []
    return []


def _is_parseable_timestamp(value: Any) -> bool:
    """Return True when the value is a parseable ISO-8601 timestamp."""
    if not isinstance(value, str) or not value.strip():
        return False
    candidate = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(candidate)
    except ValueError:
        return False
    return True
