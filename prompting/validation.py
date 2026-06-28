"""Validation helpers for grounded RCA drafts and prompt-side evidence hygiene."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from prompting.types import PromptContext, RcaDraft
from retrieval.types import EvidenceBundle


_FORBIDDEN_GROUND_TRUTH_PATTERNS = (
    "expected_rca.json",
    "expected_rca",
    "benchmark ground truth",
    "ground truth",
)
"""Markers that should never leak into prompt-side evidence context."""

_TEXT_FIELDS = ("text", "message", "event", "summary", "title", "root_cause")
"""Common evidence fields that can justify RCA claims or actions."""

_ACTION_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "the",
        "to",
        "for",
        "of",
        "on",
        "in",
        "or",
        "with",
        "by",
        "from",
        "at",
        "if",
        "is",
        "are",
        "be",
        "add",
        "check",
        "review",
        "inspect",
        "verify",
    }
)
"""Low-signal words ignored when checking whether an action is evidence-backed."""


@dataclass(slots=True)
class PromptValidationIssue:
    """Structured validation issue returned to prompting callers."""

    code: str
    message: str
    location: str
    severity: str = "error"


@dataclass(slots=True)
class PromptValidationReport:
    """Structured validation outcome for one RCA draft and its originating evidence."""

    errors: list[PromptValidationIssue] = field(default_factory=list)
    warnings: list[PromptValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True when no validation errors were found."""
        return not self.errors

    @property
    def is_usable(self) -> bool:
        """Return True unless the draft is fundamentally untrustworthy."""
        blocking_codes = {
            "empty_root_cause",
            "missing_required_field",
            "unknown_citation_node_id",
            "ground_truth_leak_detected",
        }
        return not any(issue.code in blocking_codes for issue in self.errors)

    def add_error(self, code: str, message: str, location: str) -> None:
        """Record a fatal validation error."""
        self.errors.append(PromptValidationIssue(code=code, message=message, location=location, severity="error"))

    def add_warning(self, code: str, message: str, location: str) -> None:
        """Record a non-fatal validation warning."""
        self.warnings.append(PromptValidationIssue(code=code, message=message, location=location, severity="warning"))

    def extend(self, other: "PromptValidationReport") -> None:
        """Merge another validation report into this one."""
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def to_dict(self) -> dict[str, Any]:
        """Return a serializable validation report."""
        return {
            "is_valid": self.is_valid,
            "is_usable": self.is_usable,
            "errors": [asdict(issue) for issue in self.errors],
            "warnings": [asdict(issue) for issue in self.warnings],
        }


class PromptingValidator:
    """Validate grounded RCA drafts against their originating evidence bundle."""

    def validate(
        self,
        *,
        rca_draft: RcaDraft,
        evidence_bundle: EvidenceBundle,
        prompt_context: PromptContext | None = None,
    ) -> PromptValidationReport:
        """Validate one RCA draft, its citations, and its originating prompt inputs."""
        report = PromptValidationReport()
        report.extend(self.validate_required_fields(rca_draft))
        report.extend(self.validate_citations(rca_draft, evidence_bundle))
        report.extend(self.validate_recommended_actions(rca_draft, evidence_bundle))
        report.extend(self.validate_hypothesis_grounding(rca_draft, evidence_bundle))
        report.extend(self.validate_invented_reasoning_risk(rca_draft, evidence_bundle))
        report.extend(self.validate_ground_truth_leakage(evidence_bundle=evidence_bundle, prompt_context=prompt_context))
        return report

    def validate_required_fields(self, rca_draft: RcaDraft) -> PromptValidationReport:
        """Validate that required RCA fields are populated."""
        report = PromptValidationReport()
        if not rca_draft.root_cause.strip():
            report.add_error(
                "empty_root_cause",
                "RcaDraft.root_cause must be a non-empty string.",
                "rca_draft.root_cause",
            )

        required_lists = (
            ("evidence_summary", rca_draft.evidence_summary),
            ("supported_hypotheses", rca_draft.supported_hypotheses),
            ("ruled_out_hypotheses", rca_draft.ruled_out_hypotheses),
            ("recommended_actions", rca_draft.recommended_actions),
            ("citations", rca_draft.citations),
        )
        for field_name, value in required_lists:
            if value is None:
                report.add_error(
                    "missing_required_field",
                    f"RcaDraft.{field_name} must be populated.",
                    f"rca_draft.{field_name}",
                )

        if not rca_draft.raw_model_output.strip():
            report.add_error(
                "missing_required_field",
                "RcaDraft.raw_model_output must preserve the original model text.",
                "rca_draft.raw_model_output",
            )
        return report

    def validate_citations(self, rca_draft: RcaDraft, evidence_bundle: EvidenceBundle) -> PromptValidationReport:
        """Validate that every cited node ID exists in the originating evidence bundle."""
        report = PromptValidationReport()
        valid_node_ids = _bundle_node_ids(evidence_bundle)

        for index, citation in enumerate(rca_draft.citations):
            if citation.node_id not in valid_node_ids:
                report.add_error(
                    "unknown_citation_node_id",
                    f"Citation references node_id '{citation.node_id}' that is absent from the originating EvidenceBundle.",
                    f"rca_draft.citations[{index}].node_id",
                )

        if not rca_draft.citations and any(
            [
                rca_draft.root_cause.strip(),
                rca_draft.evidence_summary,
                rca_draft.supported_hypotheses,
                rca_draft.ruled_out_hypotheses,
            ]
        ):
            report.add_warning(
                "missing_citations",
                "RCA draft includes substantive conclusions but no citations.",
                "rca_draft.citations",
            )
        return report

    def validate_recommended_actions(self, rca_draft: RcaDraft, evidence_bundle: EvidenceBundle) -> PromptValidationReport:
        """Validate that recommended actions appear grounded in runbooks or cited evidence."""
        report = PromptValidationReport()
        allowed_node_ids = {citation.node_id for citation in rca_draft.citations}
        evidence_texts = _evidence_text_corpus(evidence_bundle, allowed_node_ids=allowed_node_ids)

        for index, action in enumerate(rca_draft.recommended_actions):
            if _action_supported_by_evidence(action, evidence_texts):
                continue
            report.add_warning(
                "unsupported_recommended_action",
                "Recommended action is not clearly traceable to retrieved runbooks or cited evidence.",
                f"rca_draft.recommended_actions[{index}]",
            )
        return report

    def validate_hypothesis_grounding(self, rca_draft: RcaDraft, evidence_bundle: EvidenceBundle) -> PromptValidationReport:
        """Validate that unsupported hypotheses are not promoted as established facts."""
        report = PromptValidationReport()
        hypothesis_records = evidence_bundle.hypotheses
        if not hypothesis_records:
            return report

        supported_texts = {
            _normalize_text(entry.get("text"))
            for entry in hypothesis_records
            if _normalize_text(entry.get("status")) in {"supported", "confirmed", "likely"}
        }
        candidate_texts = {
            _normalize_text(entry.get("text"))
            for entry in hypothesis_records
            if _normalize_text(entry.get("status")) in {"candidate", "open", "possible", ""}
        }
        ruled_out_texts = {
            _normalize_text(entry.get("text"))
            for entry in hypothesis_records
            if _normalize_text(entry.get("status")) in {"ruled_out", "rejected", "unlikely"}
        }

        root_cause_text = _normalize_text(rca_draft.root_cause)
        if root_cause_text in ruled_out_texts:
            report.add_error(
                "ruled_out_hypothesis_promoted",
                "The RCA root cause matches a hypothesis that retrieval marked as ruled out.",
                "rca_draft.root_cause",
            )
        elif root_cause_text in candidate_texts and root_cause_text not in supported_texts:
            report.add_warning(
                "unsupported_hypothesis_promoted",
                "The RCA root cause matches a hypothesis that retrieval did not mark as supported.",
                "rca_draft.root_cause",
            )

        for index, hypothesis in enumerate(rca_draft.supported_hypotheses):
            hypothesis_text = _normalize_text(hypothesis)
            if hypothesis_text in ruled_out_texts:
                report.add_error(
                    "ruled_out_hypothesis_promoted",
                    "A supported hypothesis in the RCA draft conflicts with retrieval rule-out evidence.",
                    f"rca_draft.supported_hypotheses[{index}]",
                )
            elif hypothesis_text in candidate_texts and hypothesis_text not in supported_texts:
                report.add_warning(
                    "unsupported_hypothesis_promoted",
                    "A supported hypothesis in the RCA draft was not marked as supported in retrieval output.",
                    f"rca_draft.supported_hypotheses[{index}]",
                )
        return report

    def validate_invented_reasoning_risk(
        self,
        rca_draft: RcaDraft,
        evidence_bundle: EvidenceBundle,
    ) -> PromptValidationReport:
        """Warn when the RCA appears to reason beyond the available evidence footprint."""
        report = PromptValidationReport()
        evidence_count = sum(
            len(records)
            for records in (
                evidence_bundle.deployments,
                evidence_bundle.commits,
                evidence_bundle.metrics,
                evidence_bundle.logs,
                evidence_bundle.timeline,
                evidence_bundle.services,
                evidence_bundle.configurations,
                evidence_bundle.hypotheses,
                evidence_bundle.runbooks,
            )
        )
        if evidence_count == 0 and any(
            [
                rca_draft.root_cause.strip(),
                rca_draft.evidence_summary,
                rca_draft.supported_hypotheses,
                rca_draft.recommended_actions,
            ]
        ):
            report.add_error(
                "invented_reasoning_without_evidence",
                "RCA draft contains reasoning despite an empty originating EvidenceBundle.",
                "rca_draft",
            )

        if evidence_count > 0 and not rca_draft.citations:
            report.add_warning(
                "invented_reasoning_risk",
                "RCA draft contains evidence-backed sections but does not cite any originating nodes.",
                "rca_draft.citations",
            )
        return report

    def validate_ground_truth_leakage(
        self,
        *,
        evidence_bundle: EvidenceBundle,
        prompt_context: PromptContext | None,
    ) -> PromptValidationReport:
        """Validate that prompt-side evidence does not contain evaluation-only ground truth."""
        report = PromptValidationReport()
        payloads: list[tuple[str, Any]] = [("evidence_bundle", asdict(evidence_bundle))]
        if prompt_context is not None:
            payloads.append(("prompt_context", prompt_context.model_dump(mode="python")))

        for root_name, payload in payloads:
            matches = _find_forbidden_markers(payload)
            for marker, location in matches:
                report.add_error(
                    "ground_truth_leak_detected",
                    f"Prompt-side evidence contains forbidden evaluation marker '{marker}'.",
                    f"{root_name}.{location}",
                )
        return report


def validate_prompting_output(
    *,
    rca_draft: RcaDraft,
    evidence_bundle: EvidenceBundle,
    prompt_context: PromptContext | None = None,
) -> PromptValidationReport:
    """Validate one RCA draft against its originating evidence using default rules."""
    validator = PromptingValidator()
    return validator.validate(
        rca_draft=rca_draft,
        evidence_bundle=evidence_bundle,
        prompt_context=prompt_context,
    )


def _bundle_node_ids(evidence_bundle: EvidenceBundle) -> set[str]:
    """Return every node ID present in the originating evidence bundle."""
    node_ids: set[str] = set()
    if evidence_bundle.incident and evidence_bundle.incident.get("node_id"):
        node_ids.add(str(evidence_bundle.incident["node_id"]))

    grouped_sections = (
        evidence_bundle.deployments,
        evidence_bundle.commits,
        evidence_bundle.metrics,
        evidence_bundle.logs,
        evidence_bundle.timeline,
        evidence_bundle.services,
        evidence_bundle.configurations,
        evidence_bundle.hypotheses,
        evidence_bundle.runbooks,
    )
    for records in grouped_sections:
        for record in records:
            node_id = str(record.get("node_id", "")).strip()
            if node_id:
                node_ids.add(node_id)
    return node_ids


def _evidence_text_corpus(evidence_bundle: EvidenceBundle, *, allowed_node_ids: set[str]) -> list[str]:
    """Return normalized evidence text snippets that can justify actions or reasoning."""
    corpus: list[str] = []
    sections = (
        evidence_bundle.runbooks,
        evidence_bundle.configurations,
        evidence_bundle.commits,
        evidence_bundle.logs,
        evidence_bundle.timeline,
        evidence_bundle.metrics,
        evidence_bundle.hypotheses,
    )
    for records in sections:
        for record in records:
            node_id = str(record.get("node_id", "")).strip()
            if allowed_node_ids and node_id and node_id not in allowed_node_ids and records is not evidence_bundle.runbooks:
                continue
            for field_name in _TEXT_FIELDS:
                value = record.get(field_name)
                if isinstance(value, str) and value.strip():
                    corpus.append(_normalize_text(value))
    return corpus


def _action_supported_by_evidence(action: str, evidence_texts: list[str]) -> bool:
    """Return True when an action appears grounded in retrieved evidence text."""
    action_terms = {
        token
        for token in re.findall(r"[a-z0-9]+", action.lower())
        if len(token) > 2 and token not in _ACTION_STOPWORDS
    }
    if not action_terms:
        return False

    for evidence_text in evidence_texts:
        overlap = action_terms.intersection(set(re.findall(r"[a-z0-9]+", evidence_text.lower())))
        if len(overlap) >= min(2, len(action_terms)):
            return True
    return False


def _find_forbidden_markers(payload: Any, *, path: str = "") -> list[tuple[str, str]]:
    """Recursively find ground-truth leakage markers in serialized payloads."""
    matches: list[tuple[str, str]] = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_path = f"{path}.{key}" if path else str(key)
            matches.extend(_find_forbidden_markers(value, path=key_path))
        return matches

    if isinstance(payload, list):
        for index, value in enumerate(payload):
            list_path = f"{path}[{index}]" if path else f"[{index}]"
            matches.extend(_find_forbidden_markers(value, path=list_path))
        return matches

    if isinstance(payload, str):
        normalized = payload.lower()
        for marker in _FORBIDDEN_GROUND_TRUTH_PATTERNS:
            if marker in normalized:
                matches.append((marker, path or "<root>"))
    return matches


def _normalize_text(value: Any) -> str:
    """Return a lowercase normalized text representation for comparison."""
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", value).strip().lower()


__all__ = [
    "PromptValidationIssue",
    "PromptValidationReport",
    "PromptingValidator",
    "validate_prompting_output",
]
