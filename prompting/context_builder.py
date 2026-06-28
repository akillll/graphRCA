"""Build compact prompt context objects from retrieval evidence bundles.

This module converts retrieval-layer `EvidenceBundle` objects into prompt-facing
`PromptContext` models without introducing any prompt template logic or model
runtime coupling. The builder keeps citation-ready node identifiers, removes
database-specific details, and trims verbose evidence sources such as logs and
runbooks so the final context stays compact enough for a local LLM.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from prompting.types import PromptContext, RcaCitation
from retrieval.types import CitationCandidate, EvidenceBundle


_NEO4J_DETAIL_KEYS = frozenset(
    {
        "node_labels",
        "labels",
        "element_id",
        "start_node_element_id",
        "end_node_element_id",
        "relationship_id",
        "relationship_type",
        "source_id",
        "target_id",
        "properties",
    }
)
"""Implementation-specific keys that should not be forwarded into prompt context."""

_DEFAULT_KEEP_FIELDS: dict[str, tuple[str, ...]] = {
    "incident": (
        "node_id",
        "title",
        "summary",
        "difficulty",
        "service",
        "severity",
        "start_time",
        "end_time",
        "tags",
    ),
    "deployments": (
        "node_id",
        "deployment_id",
        "timestamp",
        "service",
        "environment",
        "version",
        "strategy",
        "status",
        "actor",
        "commit_ids",
        "service_ids",
    ),
    "commits": (
        "node_id",
        "commit_id",
        "timestamp",
        "message",
        "author",
        "files_changed",
        "deployment_ids",
        "changed_configuration_ids",
    ),
    "metrics": (
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
        "points",
        "metric_ids",
        "service_ids",
    ),
    "logs": (
        "node_id",
        "timestamp",
        "level",
        "service",
        "component",
        "message",
        "trace_id",
        "reference_ids",
        "service_ids",
    ),
    "timeline": (
        "node_id",
        "timestamp",
        "actor",
        "event",
        "detail",
        "reference_ids",
        "previous_event_ids",
    ),
    "services": (
        "node_id",
        "name",
        "team",
        "tier",
        "language",
        "aliases",
        "depends_on_ids",
        "depended_on_by_ids",
    ),
    "configurations": (
        "node_id",
        "kind",
        "text",
        "service",
        "timestamp",
        "source_field",
        "changed_by_commit_ids",
    ),
    "hypotheses": (
        "node_id",
        "text",
        "status",
        "supporting_evidence_ids",
        "ruling_out_evidence_ids",
        "support_edge_types",
        "rule_out_edge_types",
    ),
    "runbooks": (
        "node_id",
        "filename",
        "title",
        "summary",
        "recommended_action_ids",
        "recommended_actions",
    ),
}
"""Field allowlists per evidence section used to keep prompt payloads compact."""

_PREFERRED_LOG_LEVELS = {"ERROR", "WARN"}
"""Log severities that are usually most useful for RCA prompting."""


class PromptContextBuilder:
    """Convert an `EvidenceBundle` into a compact, citation-ready `PromptContext`.

    The builder preserves structured evidence categories and `node_id` values while
    removing graph-driver details and aggressively trimming noisy content. It is
    intentionally independent of prompt rendering and model invocation so the same
    builder can be reused by CLI tools, API handlers, and offline evaluation.
    """

    def __init__(
        self,
        *,
        max_deployments: int = 8,
        max_commits: int = 8,
        max_metrics: int = 8,
        max_logs: int = 12,
        max_timeline_events: int = 16,
        max_services: int = 10,
        max_configurations: int = 10,
        max_hypotheses: int = 12,
        max_runbooks: int = 6,
        max_points_per_metric: int = 12,
        max_files_per_commit: int = 8,
        max_tags: int = 8,
        max_text_chars: int = 320,
        max_log_message_chars: int = 220,
        max_runbook_summary_chars: int = 420,
    ) -> None:
        """Initialize prompt compaction limits for each evidence section."""
        self.max_deployments = max_deployments
        self.max_commits = max_commits
        self.max_metrics = max_metrics
        self.max_logs = max_logs
        self.max_timeline_events = max_timeline_events
        self.max_services = max_services
        self.max_configurations = max_configurations
        self.max_hypotheses = max_hypotheses
        self.max_runbooks = max_runbooks
        self.max_points_per_metric = max_points_per_metric
        self.max_files_per_commit = max_files_per_commit
        self.max_tags = max_tags
        self.max_text_chars = max_text_chars
        self.max_log_message_chars = max_log_message_chars
        self.max_runbook_summary_chars = max_runbook_summary_chars

    def build(self, evidence_bundle: EvidenceBundle, question: str) -> PromptContext:
        """Build a compact `PromptContext` from one retrieval evidence bundle."""
        incident = self._incident_summary(evidence_bundle)
        incident_id = str(incident.get("node_id") or "").strip()
        if not incident_id:
            raise ValueError("EvidenceBundle.incident must include a non-empty node_id.")

        return PromptContext(
            question=question.strip(),
            incident_id=incident_id,
            incident_summary=incident,
            deployments=self._limit(
                self._sanitize_records(evidence_bundle.deployments, section="deployments"),
                self.max_deployments,
            ),
            commits=self._limit(
                self._sanitize_records(evidence_bundle.commits, section="commits"),
                self.max_commits,
            ),
            metrics=self._limit(
                self._sanitize_metric_records(evidence_bundle.metrics),
                self.max_metrics,
            ),
            logs=self._select_logs(evidence_bundle.logs),
            timeline=self._limit(
                self._sanitize_records(evidence_bundle.timeline, section="timeline"),
                self.max_timeline_events,
            ),
            services=self._limit(
                self._sanitize_records(evidence_bundle.services, section="services"),
                self.max_services,
            ),
            configurations=self._limit(
                self._sanitize_records(evidence_bundle.configurations, section="configurations"),
                self.max_configurations,
            ),
            hypotheses=self._limit(
                self._sanitize_records(evidence_bundle.hypotheses, section="hypotheses"),
                self.max_hypotheses,
            ),
            runbooks=self._limit(
                self._sanitize_runbook_records(evidence_bundle.runbooks),
                self.max_runbooks,
            ),
            citations=self._citation_records(evidence_bundle.citations),
        )

    def __call__(self, evidence_bundle: EvidenceBundle, question: str) -> PromptContext:
        """Allow the builder to be used as a small callable helper."""
        return self.build(evidence_bundle, question)

    def _incident_summary(self, evidence_bundle: EvidenceBundle) -> dict[str, Any]:
        """Return a compact incident metadata payload for prompt context."""
        incident = evidence_bundle.incident
        if incident is None:
            raise ValueError("EvidenceBundle.incident is required to build prompt context.")

        summary = self._sanitize_record(incident, section="incident")
        tags = summary.get("tags")
        if isinstance(tags, list):
            summary["tags"] = self._limit(tags, self.max_tags)
        return summary

    def _sanitize_records(self, records: Iterable[dict[str, Any]], *, section: str) -> list[dict[str, Any]]:
        """Return compact, prompt-safe records for one evidence section."""
        sanitized_records = [self._sanitize_record(record, section=section) for record in records]
        if section == "commits":
            for record in sanitized_records:
                files_changed = record.get("files_changed")
                if isinstance(files_changed, list):
                    record["files_changed"] = self._limit(files_changed, self.max_files_per_commit)
        return sanitized_records

    def _sanitize_record(self, record: dict[str, Any], *, section: str) -> dict[str, Any]:
        """Strip non-prompt keys and aggressively compact one evidence record."""
        allowed_fields = _DEFAULT_KEEP_FIELDS[section]
        sanitized: dict[str, Any] = {}

        for key in allowed_fields:
            if key not in record or key in _NEO4J_DETAIL_KEYS:
                continue
            value = self._compact_value(key, record[key])
            if value is None:
                continue
            sanitized[key] = value

        node_id = str(sanitized.get("node_id", "")).strip()
        if not node_id:
            fallback_node_id = str(record.get("node_id", "")).strip()
            if fallback_node_id:
                sanitized["node_id"] = fallback_node_id
        return sanitized

    def _sanitize_metric_records(self, records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Trim metric series payloads while keeping anomaly timing and compact points."""
        sanitized_records = self._sanitize_records(records, section="metrics")
        for record in sanitized_records:
            points = record.get("points")
            if isinstance(points, list):
                record["points"] = self._compact_metric_points(points)
        return sanitized_records

    def _sanitize_runbook_records(self, records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """Drop full markdown content and replace it with a short plain-text summary."""
        compact_runbooks: list[dict[str, Any]] = []
        for record in records:
            sanitized = self._sanitize_record(record, section="runbooks")
            content = record.get("content")
            if isinstance(content, str) and content.strip():
                sanitized["summary"] = self._summarize_runbook_content(content)
            elif "summary" not in sanitized and isinstance(record.get("title"), str):
                sanitized["summary"] = self._truncate_text(str(record["title"]), self.max_runbook_summary_chars)
            compact_runbooks.append(sanitized)
        return compact_runbooks

    def _select_logs(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Select the most prompt-relevant logs while preserving chronological order."""
        sanitized_logs = self._sanitize_records(records, section="logs")
        if len(sanitized_logs) <= self.max_logs:
            return sanitized_logs

        preferred_indices: list[int] = []
        fallback_indices: list[int] = []

        for index, record in enumerate(sanitized_logs):
            level = str(record.get("level", "")).upper()
            if level in _PREFERRED_LOG_LEVELS:
                preferred_indices.append(index)
                continue
            if record.get("reference_ids"):
                preferred_indices.append(index)
                continue
            fallback_indices.append(index)

        selected_indices = preferred_indices[: self.max_logs]
        if len(selected_indices) < self.max_logs:
            remaining = self.max_logs - len(selected_indices)
            selected_indices.extend(fallback_indices[:remaining])

        selected_indices = sorted(set(selected_indices))
        return [sanitized_logs[index] for index in selected_indices]

    def _citation_records(self, candidates: Iterable[CitationCandidate]) -> list[RcaCitation]:
        """Convert retrieval citation candidates into prompt-facing citation hints."""
        citations: list[RcaCitation] = []
        for candidate in candidates:
            explanation = candidate.rationale or f"Evidence node available for citation from {candidate.source_type}."
            citations.append(
                RcaCitation(
                    node_id=candidate.node_id,
                    node_label=candidate.node_label,
                    explanation=explanation,
                )
            )
        return citations

    def _compact_value(self, key: str, value: Any) -> Any:
        """Normalize one field value into a compact prompt-safe representation."""
        if value is None:
            return None
        if isinstance(value, str):
            limit = self.max_log_message_chars if key == "message" else self.max_text_chars
            compact = self._truncate_text(value, limit)
            return compact if compact else None
        if isinstance(value, list):
            compact_list = [self._compact_list_item(item) for item in value]
            compact_list = [item for item in compact_list if item is not None]
            return compact_list or None
        if isinstance(value, dict):
            return self._compact_mapping(value)
        return value

    def _compact_mapping(self, value: dict[str, Any]) -> dict[str, Any] | None:
        """Recursively compact small mapping payloads."""
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            if key in _NEO4J_DETAIL_KEYS:
                continue
            compact_item = self._compact_value(key, item)
            if compact_item is None:
                continue
            compacted[key] = compact_item
        return compacted or None

    def _compact_list_item(self, item: Any) -> Any:
        """Compact one list item without losing simple scalar signal."""
        if item is None:
            return None
        if isinstance(item, str):
            compact = self._truncate_text(item, self.max_text_chars)
            return compact if compact else None
        if isinstance(item, dict):
            return self._compact_mapping(item)
        if isinstance(item, list):
            nested = [self._compact_list_item(value) for value in item]
            nested = [value for value in nested if value is not None]
            return nested or None
        return item

    def _compact_metric_points(self, points: list[Any]) -> list[Any]:
        """Sample metric points from the beginning and end of the window."""
        if len(points) <= self.max_points_per_metric:
            compacted: list[Any] = []
            for point in points:
                compact_point = self._compact_list_item(point)
                if compact_point is not None:
                    compacted.append(compact_point)
            return compacted

        head_count = self.max_points_per_metric // 2
        tail_count = self.max_points_per_metric - head_count
        sampled = [*points[:head_count], *points[-tail_count:]]
        compacted: list[Any] = []
        for point in sampled:
            compact_point = self._compact_list_item(point)
            if compact_point is not None:
                compacted.append(compact_point)
        return compacted

    def _summarize_runbook_content(self, content: str) -> str:
        """Convert markdown runbook content into a short plain-text summary."""
        lines = [line.strip() for line in content.splitlines()]
        summary_lines: list[str] = []

        for line in lines:
            if not line:
                continue
            plain = self._normalize_markdown_line(line)
            if not plain:
                continue
            summary_lines.append(plain)
            if len(" ".join(summary_lines)) >= self.max_runbook_summary_chars:
                break

        summary = " ".join(summary_lines)
        return self._truncate_text(summary, self.max_runbook_summary_chars)

    def _normalize_markdown_line(self, line: str) -> str:
        """Strip common markdown syntax from one runbook line."""
        normalized = re.sub(r"^\s{0,3}#{1,6}\s*", "", line)
        normalized = re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", normalized)
        normalized = re.sub(r"`([^`]*)`", r"\1", normalized)
        normalized = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", normalized)
        return re.sub(r"\s+", " ", normalized).strip()

    def _truncate_text(self, value: str, limit: int) -> str:
        """Trim long text fields to a stable length boundary."""
        normalized = re.sub(r"\s+", " ", value).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[: max(0, limit - 3)].rstrip() + "..."

    def _limit(self, values: list[Any], limit: int) -> list[Any]:
        """Return the first `limit` values while preserving input order."""
        if limit < 0:
            raise ValueError("Prompt context limits must be non-negative.")
        return values[:limit]


__all__ = ["PromptContextBuilder"]
