"""Validation helpers for retrieved incident neighborhoods and evidence bundles."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from ingestion.types import EDGE_REQUIRED_FIELDS
from retrieval.client import Neo4jReadClient
from retrieval.queries import INCIDENT_BY_ID_QUERY
from retrieval.types import EvidenceBundle, TraversalResult


KNOWN_EDGE_TYPES = frozenset(EDGE_REQUIRED_FIELDS.keys())
"""Known graph relationship types allowed in retrieval output."""


@dataclass(slots=True)
class ValidationIssue:
    """Structured validation issue returned to retrieval callers."""

    code: str
    message: str
    location: str
    severity: str = "error"


@dataclass(slots=True)
class RetrievalValidationReport:
    """Structured validation outcome for traversal results and evidence bundles."""

    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Return True when no retrieval validation errors were found."""
        return not self.errors

    @property
    def is_usable(self) -> bool:
        """Return True unless the retrieval result is fundamentally unusable."""
        unusable_codes = {
            "missing_incident_id",
            "missing_incident_node",
            "unknown_incident_id",
            "empty_bundle_incident_node_id",
        }
        return not any(issue.code in unusable_codes for issue in self.errors)

    def add_error(self, code: str, message: str, location: str) -> None:
        """Record a retrieval validation error."""
        self.errors.append(ValidationIssue(code=code, message=message, location=location, severity="error"))

    def add_warning(self, code: str, message: str, location: str) -> None:
        """Record a non-fatal retrieval validation warning."""
        self.warnings.append(ValidationIssue(code=code, message=message, location=location, severity="warning"))

    def extend(self, other: "RetrievalValidationReport") -> None:
        """Merge another retrieval validation report into this one."""
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


class RetrievalValidator:
    """Validate traversal and evidence-bundle outputs without blocking normal retrieval."""

    def __init__(
        self,
        client: Neo4jReadClient | None = None,
        *,
        known_incident_ids: Iterable[str] | None = None,
    ) -> None:
        """Initialize the validator with optional incident-ID sources."""
        self._client = client
        self._known_incident_ids = frozenset(known_incident_ids or [])

    def validate(
        self,
        *,
        traversal_result: TraversalResult,
        evidence_bundle: EvidenceBundle | None = None,
    ) -> RetrievalValidationReport:
        """Validate one traversal result and its assembled evidence bundle."""
        report = RetrievalValidationReport()
        report.extend(self.validate_traversal_result(traversal_result))
        if evidence_bundle is not None:
            report.extend(self.validate_evidence_bundle(evidence_bundle))
            report.extend(self._validate_runbook_bundle_alignment(traversal_result, evidence_bundle))
        return report

    def validate_traversal_result(self, traversal_result: TraversalResult) -> RetrievalValidationReport:
        """Validate traversal result incident IDs, edges, runbooks, and hard-incident topology."""
        report = RetrievalValidationReport()

        if not traversal_result.incident_id:
            report.add_error(
                "missing_incident_id",
                "TraversalResult.incident_id must be a non-empty string.",
                "traversal_result.incident_id",
            )
            return report

        if not self._incident_exists(traversal_result.incident_id):
            report.add_error(
                "unknown_incident_id",
                f"Retrieved incident ID '{traversal_result.incident_id}' does not exist.",
                "traversal_result.incident_id",
            )

        node_by_id = {
            str(node.get("node_id")): node
            for node in traversal_result.nodes
            if node.get("node_id")
        }

        incident_node = node_by_id.get(traversal_result.incident_id)
        if incident_node is None:
            report.add_error(
                "missing_incident_node",
                f"Traversal nodes do not include the selected incident '{traversal_result.incident_id}'.",
                "traversal_result.nodes",
            )

        for index, edge in enumerate(traversal_result.edges):
            edge_type = str(edge.get("relationship_type", ""))
            if edge_type not in KNOWN_EDGE_TYPES:
                report.add_error(
                    "unknown_edge_type",
                    f"Traversal edge type '{edge_type}' is not part of the known graph relationship contract.",
                    f"traversal_result.edges[{index}].relationship_type",
                )

        report.extend(self._validate_runbook_matches(traversal_result, node_by_id))
        report.extend(self._validate_hard_incident_topology(traversal_result, node_by_id))
        return report

    def validate_evidence_bundle(self, evidence_bundle: EvidenceBundle) -> RetrievalValidationReport:
        """Validate that bundled evidence preserves non-empty citation-ready node IDs."""
        report = RetrievalValidationReport()

        if evidence_bundle.incident is not None:
            incident_node_id = str(evidence_bundle.incident.get("node_id", "")).strip()
            if not incident_node_id:
                report.add_error(
                    "empty_bundle_incident_node_id",
                    "EvidenceBundle.incident must include a non-empty node_id.",
                    "evidence_bundle.incident.node_id",
                )

        grouped_sections: tuple[tuple[str, list[dict[str, Any]]], ...] = (
            ("deployments", evidence_bundle.deployments),
            ("commits", evidence_bundle.commits),
            ("metrics", evidence_bundle.metrics),
            ("logs", evidence_bundle.logs),
            ("timeline", evidence_bundle.timeline),
            ("services", evidence_bundle.services),
            ("configurations", evidence_bundle.configurations),
            ("hypotheses", evidence_bundle.hypotheses),
            ("runbooks", evidence_bundle.runbooks),
        )
        for section_name, records in grouped_sections:
            for index, record in enumerate(records):
                node_id = str(record.get("node_id", "")).strip()
                if not node_id:
                    report.add_error(
                        "empty_bundle_node_id",
                        f"Evidence bundle section '{section_name}' contains a record without a node_id.",
                        f"evidence_bundle.{section_name}[{index}].node_id",
                    )

        for index, citation in enumerate(evidence_bundle.citations):
            if not citation.node_id.strip():
                report.add_error(
                    "empty_citation_node_id",
                    "EvidenceBundle.citations must reference non-empty node IDs.",
                    f"evidence_bundle.citations[{index}].node_id",
                )

        return report

    def _validate_runbook_matches(
        self,
        traversal_result: TraversalResult,
        node_by_id: dict[str, dict[str, Any]],
    ) -> RetrievalValidationReport:
        """Validate that runbook match entries point to runbook nodes present in traversal output."""
        report = RetrievalValidationReport()

        for index, runbook_entry in enumerate(traversal_result.runbooks):
            runbook = runbook_entry.get("runbook")
            if not isinstance(runbook, dict):
                report.add_warning(
                    "missing_runbook_entry",
                    "Traversal runbook entry does not include a concrete runbook node.",
                    f"traversal_result.runbooks[{index}].runbook",
                )
                continue

            runbook_id = str(runbook.get("node_id", "")).strip()
            if not runbook_id:
                report.add_error(
                    "empty_runbook_node_id",
                    "Traversal runbook entry must include a non-empty runbook node_id.",
                    f"traversal_result.runbooks[{index}].runbook.node_id",
                )
                continue

            if runbook_id not in node_by_id:
                report.add_warning(
                    "runbook_match_missing_node",
                    f"Runbook match references '{runbook_id}' but that runbook node is absent from traversal nodes.",
                    f"traversal_result.runbooks[{index}].runbook.node_id",
                )

        return report

    def _validate_hard_incident_topology(
        self,
        traversal_result: TraversalResult,
        node_by_id: dict[str, dict[str, Any]],
    ) -> RetrievalValidationReport:
        """Validate that hard-incident topology service nodes are not orphaned."""
        report = RetrievalValidationReport()
        if not _is_hard_incident(traversal_result.incident_id):
            return report

        adjacency: dict[str, int] = {}
        for edge in traversal_result.edges:
            edge_type = str(edge.get("relationship_type", ""))
            source_id = str(edge.get("source_id", ""))
            target_id = str(edge.get("target_id", ""))
            if edge_type not in {"OBSERVED_ON", "DEPENDS_ON"}:
                continue
            if source_id:
                adjacency[source_id] = adjacency.get(source_id, 0) + 1
            if target_id:
                adjacency[target_id] = adjacency.get(target_id, 0) + 1

        for node_id, node in node_by_id.items():
            labels = list(node.get("node_labels", []))
            if "Service" not in labels:
                continue
            if adjacency.get(node_id, 0) == 0:
                report.add_warning(
                    "orphan_service_topology_node",
                    f"Hard-incident topology returned orphan service node '{node_id}' without OBSERVED_ON or DEPENDS_ON edges.",
                    f"traversal_result.nodes[{node_id}]",
                )

        return report

    @staticmethod
    def _validate_runbook_bundle_alignment(
        traversal_result: TraversalResult,
        evidence_bundle: EvidenceBundle,
    ) -> RetrievalValidationReport:
        """Validate that bundled runbook IDs align with traversal runbook entries when both are present."""
        report = RetrievalValidationReport()
        traversal_runbook_ids = {
            str(entry.get("runbook", {}).get("node_id", "")).strip()
            for entry in traversal_result.runbooks
            if isinstance(entry.get("runbook"), dict)
        }
        traversal_runbook_ids.discard("")

        bundle_runbook_ids = {
            str(record.get("node_id", "")).strip()
            for record in evidence_bundle.runbooks
            if record.get("node_id")
        }

        missing_in_bundle = sorted(traversal_runbook_ids - bundle_runbook_ids)
        for runbook_id in missing_in_bundle:
            report.add_warning(
                "runbook_missing_from_bundle",
                f"Traversal runbook '{runbook_id}' was not preserved in the evidence bundle.",
                f"evidence_bundle.runbooks[{runbook_id}]",
            )

        return report

    def _incident_exists(self, incident_id: str) -> bool:
        """Return True when the incident exists in a known set or Neo4j."""
        if incident_id in self._known_incident_ids:
            return True
        if self._client is None:
            return False
        rows = self._client.run_query(INCIDENT_BY_ID_QUERY, {"incident_id": incident_id})
        return bool(rows)


def validate_retrieval_output(
    traversal_result: TraversalResult,
    evidence_bundle: EvidenceBundle | None = None,
    *,
    client: Neo4jReadClient | None = None,
    known_incident_ids: Iterable[str] | None = None,
) -> RetrievalValidationReport:
    """Validate one retrieval output without requiring an explicit validator instance."""
    validator = RetrievalValidator(client, known_incident_ids=known_incident_ids)
    return validator.validate(traversal_result=traversal_result, evidence_bundle=evidence_bundle)


def _is_hard_incident(incident_id: str) -> bool:
    """Return True when the incident ID belongs to the hard benchmark tier."""
    normalized = incident_id.removeprefix("incident:")
    return normalized.startswith("hard_")
