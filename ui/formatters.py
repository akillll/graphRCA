"""Display formatting helpers for Chainlit investigation steps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ui.types import UiCitation, UiHypothesis, UiInvestigateResponse, UiWarning


@dataclass(frozen=True, slots=True)
class FormattedInvestigation:
    """Container for the four visible investigation sections."""

    question_resolution: str
    evidence_neighborhood: str
    hypothesis_evaluation: str
    root_cause_analysis: str


class InvestigationFormatter:
    """Render one investigation into a clean operator-plus-engineering view."""

    def format(self, response: UiInvestigateResponse) -> FormattedInvestigation:
        """Format one investigation response into four visible sections."""
        return FormattedInvestigation(
            question_resolution=self.format_question_resolution(response),
            evidence_neighborhood=self.format_evidence_neighborhood(response),
            hypothesis_evaluation=self.format_hypothesis_evaluation(response),
            root_cause_analysis=self.format_root_cause_analysis(response),
        )

    def format_question_resolution(self, response: UiInvestigateResponse) -> str:
        """Render how the backend interpreted and resolved the question."""
        resolution = response.question_resolution or {}
        extracted = resolution.get("extracted_entities")
        entities = extracted if isinstance(extracted, dict) else {}
        candidates = resolution.get("incident_candidates")
        candidate_rows = candidates if isinstance(candidates, list) else []

        lines = [
            "## Question Resolution",
            f"- Selected incident: `{response.incident_id}`",
            f"- Scope classification: `{_display_value(resolution.get('scope_classification'))}`",
            f"- Scope rationale: {_display_value(resolution.get('scope_reason'))}",
            f"- Matched terms: {_render_inline_list(_string_list(resolution.get('matched_terms')))}",
            f"- Services: {_render_inline_list(_string_list(entities.get('services')))}",
            f"- Symptoms: {_render_inline_list(_string_list(entities.get('symptoms')))}",
            f"- Time references: {_render_inline_list(_string_list(entities.get('time_references')))}",
            f"- Operational terms: {_render_inline_list(_string_list(entities.get('operational_terms')))}",
            "- Top incident candidates:",
        ]

        if candidate_rows:
            for index, candidate in enumerate(candidate_rows, start=1):
                if not isinstance(candidate, dict):
                    continue
                incident_id = _display_value(candidate.get("incident_id"))
                score = _display_value(candidate.get("score"))
                reasons = _render_inline_list(_string_list(candidate.get("reasons")))
                lines.append(f"  {index}. `{incident_id}` | score={score} | reasons: {reasons}")
        else:
            lines.append("  1. No alternate candidates were returned.")

        return "\n".join(lines)

    def format_evidence_neighborhood(self, response: UiInvestigateResponse) -> str:
        """Render the developer-facing traversal and evidence summary."""
        summary = response.traversal_summary or {}
        evidence_counts = summary.get("evidence_counts")
        counts = evidence_counts if isinstance(evidence_counts, dict) else {}
        relationships = _string_list(summary.get("graph_relationships"))
        important_nodes = self._important_evidence_nodes(response)
        evidence_summary = list(response.evidence_summary)

        lines = [
            "## Evidence Neighborhood",
            (
                f"- Traversal footprint: {response.incident_id} | "
                f"nodes={_display_value(summary.get('node_count'))} | "
                f"edges={_display_value(summary.get('edge_count'))} | "
                f"candidates={_display_value(summary.get('candidate_count'))}"
            ),
            f"- Evidence counts: {_render_kv_inline(counts)}",
            f"- Key nodes: {_render_inline_list(important_nodes)}",
            f"- Graph relationships: {_render_inline_list(relationships)}",
            "- Evidence summary:",
        ]

        if evidence_summary:
            for item in evidence_summary:
                lines.append(f"  - {item}")
        else:
            lines.append("  - No evidence summary items were returned.")

        lines.append("- Top citations:")
        citation_lines = self._render_citation_lines(response.citations[:5])
        if citation_lines:
            lines.extend(citation_lines)
        else:
            lines.append("  - No citations were returned.")

        return "\n".join(lines)

    def format_hypothesis_evaluation(self, response: UiInvestigateResponse) -> str:
        """Render detailed supported, ruled-out, and considered hypotheses."""
        supported = [item for item in response.hypotheses if item.investigation_outcome == "supported"]
        ruled_out = [item for item in response.hypotheses if item.investigation_outcome == "ruled_out"]
        considered = [item for item in response.hypotheses if item.investigation_outcome == "considered"]

        lines = ["## Hypothesis Evaluation"]
        lines.extend(self._render_hypothesis_section("Supported", supported))
        lines.extend(self._render_hypothesis_section("Ruled Out", ruled_out))
        lines.extend(self._render_hypothesis_section("Considered", considered))
        return "\n".join(lines)

    def format_root_cause_analysis(self, response: UiInvestigateResponse) -> str:
        """Render the human-readable RCA with confidence and actions."""
        lines = [
            "## RCA",
            response.answer,
            "",
            f"Confidence: `{response.confidence}`. {response.confidence_rationale}",
            "",
            "Why this is the leading explanation:",
        ]

        if response.supported_hypotheses:
            for item in response.supported_hypotheses:
                lines.append(f"- {item}")
        else:
            lines.append("- No explicitly supported hypothesis was returned.")

        lines.append("")
        lines.append("Competing hypotheses ruled out:")
        if response.ruled_out_hypotheses:
            for item in response.ruled_out_hypotheses:
                lines.append(f"- {item}")
        else:
            lines.append("- No competing hypotheses were explicitly ruled out.")

        lines.append("")
        lines.append("Recommended actions:")
        if response.recommended_actions:
            for item in response.recommended_actions:
                lines.append(f"- {item}")
        else:
            lines.append("- No recommended actions were returned.")

        lines.append("")
        lines.append("Citations:")
        citation_lines = self._render_citation_lines(response.citations)
        if citation_lines:
            lines.extend(citation_lines)
        else:
            lines.append("- No citations were returned.")

        warning_text = self._render_warnings(response.warnings)
        if warning_text != "None":
            lines.extend(["", f"Warnings: {warning_text}"])

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

    def _render_hypothesis_section(self, title: str, hypotheses: list[UiHypothesis]) -> list[str]:
        """Render one outcome bucket of hypotheses with engineering detail."""
        lines = [f"### {title}"]
        if not hypotheses:
            lines.append("- None")
            return lines

        for hypothesis in hypotheses:
            support_refs = _render_inline_list(hypothesis.supporting_evidence_ids)
            rule_out_refs = _render_inline_list(hypothesis.ruling_out_evidence_ids)
            reason_codes = _render_inline_list(hypothesis.reason_codes)
            lines.append(
                f"- {hypothesis.text} | support_score={_score_value(hypothesis.support_score)} | "
                f"rule_out_score={_score_value(hypothesis.rule_out_score)}"
            )
            lines.append(f"  support evidence: {support_refs}")
            lines.append(f"  rule-out evidence: {rule_out_refs}")
            lines.append(f"  support edges: {_render_inline_list(hypothesis.support_edge_types)}")
            lines.append(f"  rule-out edges: {_render_inline_list(hypothesis.rule_out_edge_types)}")
            lines.append(f"  reason codes: {reason_codes}")
        return lines

    def _render_citation_lines(self, citations: list[UiCitation]) -> list[str]:
        """Render citations as compact markdown bullet lines."""
        return [
            f"- `{citation.node_id}` | {citation.node_label} | {citation.explanation}"
            for citation in citations
        ]

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
    return ", ".join(values) if values else "None"


def _render_kv_inline(values: dict[str, Any]) -> str:
    """Render one small key-value dictionary as inline summary text."""
    if not values:
        return "None"
    parts: list[str] = []
    for key in sorted(values):
        parts.append(f"{key}={_display_value(values[key])}")
    return ", ".join(parts)


def _display_value(value: Any) -> str:
    """Return a readable scalar display value."""
    if value is None:
        return "unknown"
    return str(value)


def _score_value(value: float | None) -> str:
    """Return a stable hypothesis score string."""
    if value is None:
        return "unknown"
    return f"{value:.3f}"


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
