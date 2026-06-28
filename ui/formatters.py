"""Display formatting helpers for Chainlit investigation steps.

The formatter layer converts a validated UI investigation response into compact,
readable markdown sections suitable for desktop and mobile chat surfaces. It is
presentation-only: no HTTP, no Chainlit handlers, and no backend orchestration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ui.types import UiCitation, UiHypothesis, UiInvestigateResponse, UiWarning


@dataclass(frozen=True, slots=True)
class FormattedInvestigation:
    """Container for the four markdown sections rendered from one investigation.

    Attributes:
        incident_resolution: Section 1 markdown.
        evidence_summary: Section 2 markdown.
        hypothesis_evaluation: Section 3 markdown.
        root_cause_analysis: Section 4 markdown.
    """

    incident_resolution: str
    evidence_summary: str
    hypothesis_evaluation: str
    root_cause_analysis: str

    @property
    def sections(self) -> list[str]:
        """Return the ordered markdown sections."""
        return [
            self.incident_resolution,
            self.evidence_summary,
            self.hypothesis_evaluation,
            self.root_cause_analysis,
        ]

    @property
    def markdown(self) -> str:
        """Return the complete formatted investigation as one markdown string."""
        return "\n\n".join(self.sections)


class InvestigationFormatter:
    """Render one `UiInvestigateResponse` into compact markdown sections.

    The formatter preserves backend citations and warnings verbatim while turning
    traversal summaries, evidence nodes, and hypothesis outcomes into readable
    UI text. It does not mutate the response and does not infer missing backend
    data beyond conservative display fallbacks such as `Not provided`.
    """

    def format(self, response: UiInvestigateResponse) -> FormattedInvestigation:
        """Format one investigation response into the four required sections."""
        return FormattedInvestigation(
            incident_resolution=self.format_incident_resolution(response),
            evidence_summary=self.format_evidence_summary(response),
            hypothesis_evaluation=self.format_hypothesis_evaluation(response),
            root_cause_analysis=self.format_root_cause_analysis(response),
        )

    def format_incident_resolution(self, response: UiInvestigateResponse) -> str:
        """Render Section 1: incident resolution and extracted entity hints."""
        summary = response.traversal_summary or {}
        extracted = summary.get("extracted_entities")
        entities = extracted if isinstance(extracted, dict) else {}

        services = _string_list(entities.get("services"))
        symptoms = _string_list(entities.get("symptoms"))
        time_references = _string_list(entities.get("time_references"))

        lines = [
            "## Incident Resolution",
            f"- Resolved incident: `{response.incident_id}`",
            f"- Extracted services: {_render_inline_list(services)}",
            f"- Symptoms: {_render_inline_list(symptoms)}",
            f"- Time references: {_render_inline_list(time_references)}",
        ]
        return "\n".join(lines)

    def format_evidence_summary(self, response: UiInvestigateResponse) -> str:
        """Render Section 2: traversal summary, key nodes, and graph references."""
        summary = response.traversal_summary or {}
        evidence_counts = summary.get("evidence_counts")
        counts = evidence_counts if isinstance(evidence_counts, dict) else {}
        important_nodes = self._important_evidence_nodes(response)
        readable_relationships = self._readable_relationships(response.hypotheses)

        lines = [
            "## Evidence Summary",
            (
                f"- Traversal: incident `{response.incident_id}`, "
                f"{_display_value(summary.get('node_count'))} nodes, "
                f"{_display_value(summary.get('edge_count'))} edges, "
                f"{_display_value(summary.get('candidate_count'))} candidates considered"
            ),
            f"- Evidence counts: {_render_kv_inline(counts)}",
            f"- Important nodes: {_render_inline_list(important_nodes)}",
            f"- Graph relationships: {_render_inline_list(readable_relationships)}",
        ]
        return "\n".join(lines)

    def format_hypothesis_evaluation(self, response: UiInvestigateResponse) -> str:
        """Render Section 3: supported and ruled-out hypotheses with evidence refs."""
        supported = [item for item in response.hypotheses if item.investigation_outcome == "supported"]
        ruled_out = [item for item in response.hypotheses if item.investigation_outcome == "ruled_out"]
        considered = [item for item in response.hypotheses if item.investigation_outcome == "considered"]

        lines = [
            "## Hypothesis Evaluation",
            f"- Supported: {self._render_hypothesis_group(supported)}",
            f"- Ruled out: {self._render_hypothesis_group(ruled_out)}",
            f"- Considered: {self._render_hypothesis_group(considered)}",
        ]
        return "\n".join(lines)

    def format_root_cause_analysis(self, response: UiInvestigateResponse) -> str:
        """Render Section 4: final RCA answer, citations, actions, and warnings."""
        recommended_actions = self._recommended_actions(response)
        lines = [
            "## Root Cause Analysis",
            f"- RCA: {response.answer}",
            f"- Citations: {self._render_citations(response.citations)}",
            f"- Recommended actions: {_render_inline_list(recommended_actions)}",
            f"- Warnings: {self._render_warnings(response.warnings)}",
        ]
        return "\n".join(lines)

    def _important_evidence_nodes(self, response: UiInvestigateResponse, limit: int = 8) -> list[str]:
        """Return compact evidence-node labels for the most useful visible nodes."""
        prioritized = sorted(
            response.evidence_nodes,
            key=lambda node: (_label_priority(node), str(node.get("node_id", ""))),
        )
        rendered: list[str] = []
        for node in prioritized[:limit]:
            node_id = str(node.get("node_id", "")).strip()
            labels = node.get("node_labels", [])
            label = labels[0] if isinstance(labels, list) and labels else "Node"
            if node_id:
                rendered.append(f"{label} `{node_id}`")
        return rendered

    def _readable_relationships(self, hypotheses: list[UiHypothesis]) -> list[str]:
        """Return readable relationship summaries derived from hypothesis evidence links."""
        relationship_set: set[str] = set()
        for hypothesis in hypotheses:
            for edge_type in hypothesis.support_edge_types:
                relationship_set.add(f"{edge_type} -> {hypothesis.text}")
            for edge_type in hypothesis.rule_out_edge_types:
                relationship_set.add(f"{edge_type} -> {hypothesis.text}")
        return sorted(relationship_set)

    def _render_hypothesis_group(self, hypotheses: list[UiHypothesis]) -> str:
        """Render one hypothesis outcome bucket with evidence references."""
        if not hypotheses:
            return "None"

        parts: list[str] = []
        for hypothesis in hypotheses:
            references = hypothesis.supporting_evidence_ids or hypothesis.ruling_out_evidence_ids
            ref_text = ", ".join(f"`{ref}`" for ref in references) if references else "no direct evidence refs"
            parts.append(f"{hypothesis.text} ({ref_text})")
        return "; ".join(parts)

    def _render_citations(self, citations: list[UiCitation]) -> str:
        """Render every citation without dropping any backend-provided reference."""
        if not citations:
            return "None"
        return "; ".join(
            f"`{citation.node_id}` ({citation.node_label}: {citation.explanation})"
            for citation in citations
        )

    def _recommended_actions(self, response: UiInvestigateResponse) -> list[str]:
        """Return recommended actions when the backend payload includes them.

        The current backend response contract does not expose actions as a top-
        level field, so this formatter reads them conservatively from
        `traversal_summary.recommended_actions` if present.
        """
        summary = response.traversal_summary or {}
        raw_actions = summary.get("recommended_actions")
        return _string_list(raw_actions)

    def _render_warnings(self, warnings: list[UiWarning]) -> str:
        """Render warning messages compactly."""
        if not warnings:
            return "None"
        return "; ".join(warning.message for warning in warnings)


def _string_list(value: Any) -> list[str]:
    """Normalize one loose value into a clean list of strings."""
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _render_inline_list(values: list[str]) -> str:
    """Render one compact inline list with a stable fallback."""
    return ", ".join(values) if values else "Not provided"


def _render_kv_inline(values: dict[str, Any]) -> str:
    """Render one small key-value dictionary as inline summary text."""
    if not values:
        return "Not provided"
    parts: list[str] = []
    for key in sorted(values):
        parts.append(f"{key}={_display_value(values[key])}")
    return ", ".join(parts)


def _display_value(value: Any) -> str:
    """Return a readable scalar display value."""
    if value is None:
        return "unknown"
    return str(value)


def _label_priority(node: dict[str, Any]) -> tuple[int, str]:
    """Return a stable priority for evidence node ordering."""
    labels = node.get("node_labels", [])
    label = labels[0] if isinstance(labels, list) and labels else "Node"
    priority = {
        "Incident": 0,
        "Service": 1,
        "Deployment": 2,
        "Commit": 3,
        "MetricSeries": 4,
        "LogEvent": 5,
        "TimelineEvent": 6,
        "Hypothesis": 7,
        "Runbook": 8,
    }.get(label, 99)
    return (priority, label)


__all__ = ["FormattedInvestigation", "InvestigationFormatter"]
