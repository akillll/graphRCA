"""Deterministic serialization helpers for prompt context rendering.

This module converts a structured `PromptContext` into a compact, human-readable
text artifact that can be reused for prompt insertion, debugging, logging, and
snapshot-style tests. It contains no prompt instructions, no template logic, and
no llama.cpp transport logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from prompting.types import PromptContext, RcaCitation


_SECTION_SEPARATOR = "\n\n"
"""Stable separator used between serialized sections."""

_RECORD_INDENT = "  "
"""Indentation prefix for per-record fields."""


@dataclass(slots=True)
class PromptSerializer:
    """Serialize `PromptContext` into deterministic, compact plain text.

    The serializer keeps section ordering fixed, preserves every citation-ready
    node ID, avoids Python dictionary ordering artifacts, and summarizes heavier
    fields so the output stays suitable for local llama.cpp context windows.
    """

    max_logs: int = 12
    max_timeline_events: int = 16
    max_runbooks: int = 6
    max_runbook_summary_chars: int = 280
    max_metric_points_preview: int = 2
    max_list_items_per_field: int = 8

    def serialize(self, context: PromptContext) -> str:
        """Serialize one prompt context into deterministic plain text."""
        sections = [
            self.serialize_incident(context),
            self.serialize_services(context),
            self.serialize_deployments(context),
            self.serialize_commits(context),
            self.serialize_configurations(context),
            self.serialize_metrics(context),
            self.serialize_logs(context),
            self.serialize_timeline(context),
            self.serialize_hypotheses(context),
            self.serialize_runbooks(context),
            self.serialize_citations(context),
        ]
        return _SECTION_SEPARATOR.join(section for section in sections if section.strip())

    def serialize_incident(self, context: PromptContext) -> str:
        """Serialize the incident summary section."""
        incident = dict(context.incident_summary)
        incident.setdefault("node_id", context.incident_id)
        ordered_fields = (
            "node_id",
            "title",
            "summary",
            "difficulty",
            "service",
            "severity",
            "start_time",
            "end_time",
            "tags",
        )
        lines = ["Incident", f"- question: {context.question}"]
        lines.extend(self._serialize_record(incident, ordered_fields=ordered_fields))
        return "\n".join(lines)

    def serialize_services(self, context: PromptContext) -> str:
        """Serialize the services section."""
        ordered = self._sort_records(context.services, keys=("name", "node_id"))
        return self._serialize_section(
            "Services",
            ordered,
            ordered_fields=("node_id", "name", "aliases", "team", "tier", "language", "depends_on_ids", "depended_on_by_ids"),
        )

    def serialize_deployments(self, context: PromptContext) -> str:
        """Serialize the deployments section."""
        ordered = self._sort_records(context.deployments, keys=("timestamp", "node_id"))
        return self._serialize_section(
            "Deployments",
            ordered,
            ordered_fields=(
                "node_id",
                "deployment_id",
                "timestamp",
                "service",
                "environment",
                "version",
                "strategy",
                "status",
                "actor",
                "service_ids",
                "commit_ids",
            ),
        )

    def serialize_commits(self, context: PromptContext) -> str:
        """Serialize the commits section."""
        ordered = self._sort_records(context.commits, keys=("timestamp", "commit_id", "node_id"))
        return self._serialize_section(
            "Commits",
            ordered,
            ordered_fields=(
                "node_id",
                "commit_id",
                "timestamp",
                "author",
                "message",
                "files_changed",
                "deployment_ids",
                "changed_configuration_ids",
            ),
        )

    def serialize_configurations(self, context: PromptContext) -> str:
        """Serialize the configurations section."""
        ordered = self._sort_records(context.configurations, keys=("timestamp", "kind", "node_id", "text"))
        return self._serialize_section(
            "Configurations",
            ordered,
            ordered_fields=("node_id", "kind", "service", "timestamp", "text", "source_field", "changed_by_commit_ids"),
        )

    def serialize_metrics(self, context: PromptContext) -> str:
        """Serialize the metrics section with compact point summaries."""
        ordered = self._sort_records(context.metrics, keys=("first_anomalous_at", "window_start", "metric", "node_id"))
        if not ordered:
            return "Metrics\n- none"

        lines = ["Metrics"]
        for record in ordered:
            lines.extend(
                self._serialize_metric_record(
                    record,
                    ordered_fields=(
                        "node_id",
                        "metric",
                        "service",
                        "unit",
                        "window_start",
                        "window_end",
                        "resolution",
                        "baseline",
                        "current",
                        "peak",
                        "min",
                        "max",
                        "mean",
                        "first_anomalous_at",
                        "service_ids",
                        "metric_ids",
                    ),
                )
            )
        return "\n".join(lines)

    def serialize_logs(self, context: PromptContext) -> str:
        """Serialize the logs section preserving chronological order."""
        logs = list(context.logs[: self.max_logs])
        if not logs:
            return "Logs\n- none"

        lines = ["Logs"]
        for record in logs:
            lines.extend(
                self._serialize_record(
                    record,
                    ordered_fields=("node_id", "timestamp", "level", "service", "component", "message", "trace_id", "reference_ids"),
                )
            )
        if len(context.logs) > self.max_logs:
            lines.append(f"- truncated_count: {len(context.logs) - self.max_logs}")
        return "\n".join(lines)

    def serialize_timeline(self, context: PromptContext) -> str:
        """Serialize the timeline section preserving chronological order."""
        timeline = list(context.timeline[: self.max_timeline_events])
        if not timeline:
            return "Timeline\n- none"

        lines = ["Timeline"]
        for record in timeline:
            lines.extend(
                self._serialize_record(
                    record,
                    ordered_fields=("node_id", "timestamp", "actor", "event", "detail", "previous_event_ids", "reference_ids"),
                )
            )
        if len(context.timeline) > self.max_timeline_events:
            lines.append(f"- truncated_count: {len(context.timeline) - self.max_timeline_events}")
        return "\n".join(lines)

    def serialize_hypotheses(self, context: PromptContext) -> str:
        """Serialize the hypotheses section."""
        ordered = self._sort_records(context.hypotheses, keys=("status", "text", "node_id"))
        return self._serialize_section(
            "Hypotheses",
            ordered,
            ordered_fields=(
                "node_id",
                "status",
                "text",
                "support_edge_types",
                "rule_out_edge_types",
                "supporting_evidence_ids",
                "ruling_out_evidence_ids",
            ),
        )

    def serialize_runbooks(self, context: PromptContext) -> str:
        """Serialize the runbooks section using compact summaries only."""
        ordered = self._sort_records(context.runbooks, keys=("filename", "title", "node_id"))
        runbooks = ordered[: self.max_runbooks]
        if not runbooks:
            return "Runbooks\n- none"

        lines = ["Runbooks"]
        for record in runbooks:
            compact_record = dict(record)
            summary = compact_record.get("summary")
            if isinstance(summary, str):
                compact_record["summary"] = self._truncate(summary, self.max_runbook_summary_chars)
            lines.extend(
                self._serialize_record(
                    compact_record,
                    ordered_fields=("node_id", "filename", "title", "summary", "recommended_action_ids"),
                )
            )
        if len(ordered) > self.max_runbooks:
            lines.append(f"- truncated_count: {len(ordered) - self.max_runbooks}")
        return "\n".join(lines)

    def serialize_citations(self, context: PromptContext) -> str:
        """Serialize the citations section."""
        citations = sorted(context.citations, key=lambda citation: (citation.node_id, citation.node_label, citation.explanation))
        if not citations:
            return "Citations\n- none"

        lines = ["Citations"]
        for citation in citations:
            lines.extend(self._serialize_citation(citation))
        return "\n".join(lines)

    def _serialize_section(
        self,
        title: str,
        records: Iterable[dict[str, Any]],
        *,
        ordered_fields: tuple[str, ...],
    ) -> str:
        """Serialize one homogeneous record section."""
        record_list = list(records)
        if not record_list:
            return f"{title}\n- none"

        lines = [title]
        for record in record_list:
            lines.extend(self._serialize_record(record, ordered_fields=ordered_fields))
        return "\n".join(lines)

    def _serialize_metric_record(self, record: dict[str, Any], *, ordered_fields: tuple[str, ...]) -> list[str]:
        """Serialize one metric record while summarizing metric points."""
        compact_record = dict(record)
        points = compact_record.pop("points", None)
        lines = self._serialize_record(compact_record, ordered_fields=ordered_fields)
        if isinstance(points, list) and points:
            lines.extend(self._serialize_metric_points(points))
        return lines

    def _serialize_metric_points(self, points: list[Any]) -> list[str]:
        """Serialize only a compact preview of metric points."""
        preview_count = min(len(points), self.max_metric_points_preview)
        head = points[:preview_count]
        tail = points[-preview_count:] if len(points) > preview_count else []
        lines = [
            f"{_RECORD_INDENT}- points_count: {len(points)}",
            f"{_RECORD_INDENT}- points_head: {self._format_value(head)}",
        ]
        if tail and tail != head:
            lines.append(f"{_RECORD_INDENT}- points_tail: {self._format_value(tail)}")
        return lines

    def _serialize_record(self, record: dict[str, Any], *, ordered_fields: tuple[str, ...]) -> list[str]:
        """Serialize one record with deterministic field ordering."""
        node_id = str(record.get("node_id", "")).strip()
        lines = [f"- {node_id or '<missing-node-id>'}"]

        rendered_fields: set[str] = set()
        for field_name in ordered_fields:
            if field_name not in record or field_name == "node_id":
                continue
            rendered = self._render_field(field_name, record[field_name])
            if rendered is None:
                continue
            lines.append(f"{_RECORD_INDENT}- {field_name}: {rendered}")
            rendered_fields.add(field_name)

        for field_name in sorted(record.keys()):
            if field_name in rendered_fields or field_name == "node_id":
                continue
            rendered = self._render_field(field_name, record[field_name])
            if rendered is None:
                continue
            lines.append(f"{_RECORD_INDENT}- {field_name}: {rendered}")
        return lines

    def _serialize_citation(self, citation: RcaCitation) -> list[str]:
        """Serialize one citation record."""
        return [
            f"- {citation.node_id}",
            f"{_RECORD_INDENT}- node_label: {citation.node_label}",
            f"{_RECORD_INDENT}- explanation: {citation.explanation}",
        ]

    def _render_field(self, field_name: str, value: Any) -> str | None:
        """Render one field value deterministically."""
        if value is None:
            return None
        if isinstance(value, str):
            normalized = value.strip()
            return normalized or None
        if isinstance(value, list):
            if not value:
                return None
            limited = value[: self.max_list_items_per_field]
            formatted = [self._format_value(item) for item in self._sorted_if_unordered(field_name, limited)]
            rendered = ", ".join(formatted)
            if len(value) > self.max_list_items_per_field:
                rendered += f", ... (+{len(value) - self.max_list_items_per_field} more)"
            return rendered
        if isinstance(value, dict):
            return self._format_mapping(value)
        return str(value)

    def _format_mapping(self, value: dict[str, Any]) -> str:
        """Render one mapping with deterministic key ordering."""
        parts: list[str] = []
        for key in sorted(value.keys()):
            item = value[key]
            parts.append(f"{key}={self._format_value(item)}")
        return "; ".join(parts)

    def _format_value(self, value: Any) -> str:
        """Return a deterministic compact string representation for any value."""
        if value is None:
            return "null"
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return "[" + ", ".join(self._format_value(item) for item in value) + "]"
        if isinstance(value, dict):
            return "{" + ", ".join(f"{key}: {self._format_value(value[key])}" for key in sorted(value.keys())) + "}"
        return str(value)

    def _sort_records(self, records: Iterable[dict[str, Any]], *, keys: tuple[str, ...]) -> list[dict[str, Any]]:
        """Return records sorted deterministically by the supplied keys."""
        return sorted(records, key=lambda record: tuple(self._sort_token(record.get(key)) for key in keys))

    def _sorted_if_unordered(self, field_name: str, values: list[Any]) -> list[Any]:
        """Sort list values only when field ordering is not semantically meaningful."""
        chronological_fields = {"points", "previous_event_ids"}
        if field_name in chronological_fields:
            return values
        if all(not isinstance(item, (dict, list)) for item in values):
            return sorted(values, key=self._sort_token)
        return sorted(values, key=lambda item: self._sort_token(self._format_value(item)))

    def _sort_token(self, value: Any) -> str:
        """Return a stable comparison token for deterministic sorting."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return self._format_value(value)

    def _truncate(self, value: str, limit: int) -> str:
        """Truncate long text fields deterministically."""
        normalized = value.strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 3)].rstrip() + "..."


__all__ = ["PromptSerializer"]
