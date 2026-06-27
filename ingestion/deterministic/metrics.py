"""Parse metrics.json into Metric and MetricSeries payloads."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any

from ingestion.common.ids import metric_id, metric_series_id, service_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


def parse_metrics(
    metrics_path: str | Path,
    *,
    incident_id: str,
    start_time: str,
    end_time: str,
) -> IngestionResult:
    """Parse one incident metrics.json file into canonical nodes and deterministic edges."""
    path = Path(metrics_path)
    _validate_metrics_path(path)

    payload = json.loads(path.read_text())
    provenance = rule_provenance(str(path))
    result = IngestionResult()
    incident_key = _incident_key(incident_id)
    seen_metrics: set[str] = set()
    seen_services: set[str] = set()
    incident_start = _parse_timestamp(start_time)
    incident_end = _parse_timestamp(end_time)
    window = payload["window"]

    for series in payload.get("series", []):
        metric_name = str(series["metric"])
        metric_node_id = metric_id(metric_name)
        if metric_node_id not in seen_metrics:
            result.nodes.append(
                GraphNode(
                    label="Metric",
                    properties={
                        "id": metric_node_id,
                        "name": metric_name,
                        "service": series.get("service"),
                    },
                    provenance=provenance,
                )
            )
            seen_metrics.add(metric_node_id)

        service_name = str(series["service"])
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

        points = [list(point) for point in series.get("points", [])]
        summaries = _metric_summaries(points, incident_start=incident_start, incident_end=incident_end)
        metric_series_node = GraphNode(
            label="MetricSeries",
            properties={
                "id": metric_series_id(incident_key, metric_name),
                "metric": metric_node_id,
                "incident_id": incident_id,
                "window_start": window["start"],
                "window_end": window["end"],
                "resolution": window["resolution"],
                "points": points,
                "unit": series["unit"],
                "service": service_name,
                **summaries,
            },
            provenance=provenance,
        )
        result.nodes.append(metric_series_node)

        result.edges.append(
            GraphEdge(
                edge_type="REFERENCES",
                source_id=metric_series_node.id,
                target_id=metric_node_id,
                provenance=provenance,
            )
        )
        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_IN",
                source_id=metric_series_node.id,
                target_id=incident_id,
                provenance=provenance,
            )
        )
        result.edges.append(
            GraphEdge(
                edge_type="OBSERVED_ON",
                source_id=metric_series_node.id,
                target_id=service_node_id,
                provenance=provenance,
            )
        )

    return result


def _validate_metrics_path(path: Path) -> None:
    """Reject non-metrics paths and evaluation-only inputs."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as runtime metrics.")
    if path.name != "metrics.json":
        raise ValueError(f"Expected a metrics.json path, got {path.name!r}.")


def _metric_summaries(
    points: list[list[Any]],
    *,
    incident_start: datetime,
    incident_end: datetime,
) -> dict[str, Any]:
    """Compute deterministic MetricSeries summary properties from raw points."""
    parsed_points = [(_parse_timestamp(str(timestamp)), value) for timestamp, value in points]
    values = [value for _, value in parsed_points]

    pre_incident_values = [value for timestamp, value in parsed_points if timestamp < incident_start]
    incident_points = [(timestamp, value) for timestamp, value in parsed_points if incident_start <= timestamp <= incident_end]

    baseline_value = median(pre_incident_values) if pre_incident_values else parsed_points[0][1]
    incident_values = [value for _, value in incident_points] or [parsed_points[0][1]]
    incident_median = median(incident_values)

    if incident_median > baseline_value:
        direction = "up"
        observed_value = max(incident_values)
    elif incident_median < baseline_value:
        direction = "down"
        observed_value = min(incident_values)
    else:
        direction = "flat"
        observed_value = baseline_value

    return {
        "baseline_value": baseline_value,
        "min_value": min(values),
        "max_value": max(values),
        "observed_value": observed_value,
        "direction": direction,
        "first_anomalous_at": _first_anomalous_at(incident_points, baseline_value),
    }


def _first_anomalous_at(
    incident_points: list[tuple[datetime, Any]],
    baseline_value: Any,
) -> str | None:
    """Return the first incident-window timestamp whose value differs from baseline by 20 percent."""
    if baseline_value == 0:
        for timestamp, value in incident_points:
            if value != 0:
                return _format_timestamp(timestamp)
        return None

    threshold = abs(float(baseline_value)) * 0.2
    for timestamp, value in incident_points:
        if abs(float(value) - float(baseline_value)) >= threshold:
            return _format_timestamp(timestamp)
    return None


def _incident_key(incident_id: str) -> str:
    """Return the raw incident identifier portion used by canonical ID helpers."""
    if incident_id.startswith("incident:"):
        return incident_id.split("incident:", 1)[1]
    return incident_id


def _parse_timestamp(value: str) -> datetime:
    """Parse a dataset ISO-8601 timestamp."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_timestamp(value: datetime) -> str:
    """Format a timezone-aware timestamp back into dataset style."""
    return value.isoformat().replace("+00:00", "Z")
