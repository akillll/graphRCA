"""Service-layer orchestration from API request to retrieval and prompting outputs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from api.config import ApiSettings, get_settings
from api.errors import (
    BadRequestError,
    GraphUnavailableError,
    IncidentNotFoundError,
    ModelUnavailableError,
    PromptingFailedError,
    UnexpectedApiError,
)
from api.types import InvestigateRequest, InvestigateResponse
from prompting.generator import PromptContextBuildError, PromptGenerationError, PromptGenerator
from prompting.llama_client import (
    LlamaCppClient,
    LlamaCppConnectionError,
    LlamaCppResponseError,
    LlamaCppTimeoutError,
)
from prompting.parser import RcaParsingError
from prompting.types import RcaCitation, RcaDraft
from retrieval.assembly import EvidenceAssembler
from retrieval.client import Neo4jReadClient
from retrieval.entity_extractor import EntityExtractor
from retrieval.hypothesis_scoring import build_evidence_summary, compose_root_cause, score_hypotheses
from retrieval.incident_index import build_incident_semantic_index
from retrieval.resolution import IncidentResolver
from retrieval.traversal import IncidentTraversal
from retrieval.types import EvidenceBundle, IncidentCandidate, TraversalResult


@dataclass(slots=True)
class InvestigationService:
    """API-facing orchestration layer for one GraphRCA investigation request."""

    settings: ApiSettings | None = None
    data_dir: Path | None = None
    graph_client: Neo4jReadClient | None = None
    extractor: EntityExtractor | None = None
    resolver: IncidentResolver | None = None
    traversal: IncidentTraversal | None = None
    assembler: EvidenceAssembler = field(default_factory=EvidenceAssembler)
    prompt_generator: PromptGenerator | None = None

    def __post_init__(self) -> None:
        """Initialize dependency wrappers without performing network calls."""
        if self.settings is None:
            self.settings = get_settings()

        if self.data_dir is None:
            self.data_dir = _default_data_dir()
        else:
            self.data_dir = Path(self.data_dir)

        known_services, known_incident_ids = _load_known_entities(self.data_dir)
        incident_index = build_incident_semantic_index(self.data_dir)

        if self.graph_client is None:
            self.graph_client = Neo4jReadClient(
                uri=self.settings.neo4j_uri,
                username=self.settings.neo4j_user,
                password=self.settings.neo4j_password,
                database=self.settings.neo4j_database,
            )

        if self.extractor is None:
            self.extractor = EntityExtractor(
                known_services=known_services,
                known_incident_ids=known_incident_ids,
            )

        if self.resolver is None:
            self.resolver = IncidentResolver(self.graph_client, incident_index=incident_index)

        if self.traversal is None:
            self.traversal = IncidentTraversal(self.graph_client)

        if self.prompt_generator is None:
            self.prompt_generator = PromptGenerator(
                llama_client=LlamaCppClient(
                    endpoint_url=self.settings.llama_base_url,
                    timeout=self.settings.llama_timeout_seconds,
                )
            )

    def investigate(self, request: InvestigateRequest) -> InvestigateResponse:
        """Resolve one question, retrieve graph evidence, and generate a grounded RCA."""
        question = request.question.strip()
        if not question:
            raise BadRequestError("Question must be a non-empty string.")

        try:
            entities = self.extractor.extract(question)
            candidates: list[IncidentCandidate] = []

            if request.incident_id and request.incident_id.strip():
                selected_incident_id = request.incident_id.strip()
            else:
                candidates = self._resolve_candidates(entities.raw_question, entities)
                selected_incident_id = candidates[0].incident_id

            traversal_result = self._traverse_incident(selected_incident_id)
            evidence_bundle = self.assembler.assemble(traversal_result)
            rca_draft = self._generate_draft(question, evidence_bundle)
            rca_draft = _repair_rca_draft(rca_draft, evidence_bundle)
            return self._build_response(
                request=request,
                selected_incident_id=traversal_result.incident_id,
                candidates=candidates,
                entities=entities,
                traversal_result=traversal_result,
                evidence_bundle=evidence_bundle,
                rca_draft=rca_draft,
            )
        except (BadRequestError, IncidentNotFoundError, GraphUnavailableError, ModelUnavailableError, PromptingFailedError):
            raise
        except Exception as exc:  # pragma: no cover - defensive normalization
            raise UnexpectedApiError("Unexpected API failure during investigation.") from exc

    def close(self) -> None:
        """Close the shared graph client if it was initialized."""
        if self.graph_client is not None:
            self.graph_client.close()

    def _resolve_candidates(self, question: str, entities) -> list[IncidentCandidate]:
        """Resolve extracted entities into ranked incident candidates."""
        try:
            candidates = self.resolver.resolve(entities)
        except Exception as exc:
            raise _map_graph_error(exc, message="Failed to resolve incident candidates.") from exc

        if not candidates:
            raise IncidentNotFoundError(
                "No incident candidates found for the supplied question.",
                details={
                    "question": question,
                    "extracted_entities": {
                        "incident_ids": list(entities.incident_ids),
                        "services": list(entities.services),
                        "symptoms": list(entities.symptoms),
                        "time_references": list(entities.time_references),
                        "operational_terms": list(entities.operational_terms),
                        "semantic_terms": list(entities.semantic_terms),
                    },
                },
            )
        return candidates

    def _traverse_incident(self, incident_id: str) -> TraversalResult:
        """Traverse one incident-centered evidence neighborhood."""
        try:
            traversal_result = self.traversal.traverse(incident_id)
        except Exception as exc:
            raise _map_graph_error(exc, message=f"Failed to traverse incident '{incident_id}'.") from exc

        if not traversal_result.nodes:
            raise IncidentNotFoundError(
                f"Incident not found: {traversal_result.incident_id}",
                details={"incident_id": traversal_result.incident_id},
            )

        if not any(node.get("node_id") == traversal_result.incident_id for node in traversal_result.nodes):
            raise IncidentNotFoundError(
                f"Incident not found: {traversal_result.incident_id}",
                details={"incident_id": traversal_result.incident_id},
            )

        return traversal_result

    def _generate_draft(self, question: str, evidence_bundle: EvidenceBundle) -> RcaDraft:
        """Generate and strictly parse one RCA draft from the assembled evidence bundle."""
        try:
            prompt_input = self.prompt_generator.build_prompt_input(question, evidence_bundle)
        except PromptContextBuildError as exc:
            raise PromptingFailedError(
                "Failed to build prompt context for the investigation.",
                details={"stage": "prompt_context", "reason": str(exc)},
            ) from exc
        except PromptGenerationError as exc:
            raise PromptingFailedError(
                "Failed to prepare the RCA prompt.",
                details={"stage": "prompt_preparation", "reason": str(exc)},
            ) from exc
        except Exception as exc:
            raise PromptingFailedError(
                "Unexpected failure while preparing the RCA prompt.",
                details={"stage": "prompt_preparation", "reason": str(exc)},
            ) from exc

        try:
            raw_model_output = self.prompt_generator.llama_client.generate(prompt_input)
        except (LlamaCppConnectionError, LlamaCppTimeoutError) as exc:
            raise ModelUnavailableError(
                "The local llama.cpp server is unavailable.",
                details={"stage": "model_call", "reason": str(exc)},
            ) from exc
        except LlamaCppResponseError as exc:
            raise ModelUnavailableError(
                "The local llama.cpp server returned an invalid response.",
                details={"stage": "model_call", "reason": str(exc)},
            ) from exc
        except Exception as exc:
            raise ModelUnavailableError(
                "Unexpected failure while calling the local llama.cpp server.",
                details={"stage": "model_call", "reason": str(exc)},
            ) from exc

        try:
            return self.prompt_generator.parser.parse(raw_model_output)
        except RcaParsingError as exc:
            raise PromptingFailedError(
                "Failed to parse the model RCA output.",
                details={"stage": "prompt_parsing", "reason": str(exc)},
            ) from exc
        except Exception as exc:
            raise PromptingFailedError(
                "Unexpected failure while parsing the model RCA output.",
                details={"stage": "prompt_parsing", "reason": str(exc)},
            ) from exc

    def _build_response(
        self,
        *,
        request: InvestigateRequest,
        selected_incident_id: str,
        candidates: list[IncidentCandidate],
        entities,
        traversal_result: TraversalResult,
        evidence_bundle: EvidenceBundle,
        rca_draft: RcaDraft,
    ) -> InvestigateResponse:
        """Convert retrieval and prompting outputs into the public API response."""
        topology_warning = f"No service topology edges found for incident {selected_incident_id}."
        warnings = [
            warning
            for warning in traversal_result.warnings
            if warning != topology_warning or request.include_debug or self.settings.retrieval_debug_enabled
        ]
        if not rca_draft.citations:
            warnings.append("The RCA draft did not include any citations.")

        return InvestigateResponse(
            question=request.question,
            incident_id=selected_incident_id,
            answer=rca_draft.root_cause,
            evidence_nodes=_evidence_node_summaries(traversal_result),
            hypotheses=_response_hypotheses(evidence_bundle, rca_draft),
            citations=[citation.model_dump() for citation in rca_draft.citations],
            traversal_summary=_traversal_summary(
                entities=entities,
                candidates=candidates,
                selected_incident_id=selected_incident_id,
                traversal_result=traversal_result,
                evidence_bundle=evidence_bundle,
                rca_draft=rca_draft,
                include_debug=request.include_debug or self.settings.retrieval_debug_enabled,
            ),
            warnings=_dedupe_preserve_order(warnings),
        )


def _map_graph_error(exc: Exception, *, message: str) -> GraphUnavailableError:
    """Normalize graph dependency failures into one stable API exception."""
    return GraphUnavailableError(message, details={"reason": str(exc)})


def _evidence_node_summaries(traversal_result: TraversalResult) -> list[dict[str, Any]]:
    """Return stable node summaries suitable for response-level evidence references."""
    return [
        {
            "node_id": node.get("node_id"),
            "node_labels": list(node.get("node_labels", [])),
        }
        for node in traversal_result.nodes
        if node.get("node_id")
    ]


def _response_hypotheses(evidence_bundle: EvidenceBundle, rca_draft: RcaDraft) -> list[dict[str, Any]]:
    """Merge retrieved hypothesis records with RCA-draft support and rule-out outcomes."""
    supported = {item.strip().lower() for item in rca_draft.supported_hypotheses if item.strip()}
    ruled_out = {item.strip().lower() for item in rca_draft.ruled_out_hypotheses if item.strip()}
    scoring_report = score_hypotheses(evidence_bundle)
    analysis_by_text = {
        item.normalized_text: {
            "support_score": item.support_score,
            "rule_out_score": item.rule_out_score,
            "support_records": item.support_records,
            "rule_out_records": item.rule_out_records,
        }
        for item in scoring_report.hypotheses
    }

    hypotheses: list[dict[str, Any]] = []
    for record in evidence_bundle.hypotheses:
        hypothesis_text = str(record.get("text", "")).strip().lower()
        analysis = analysis_by_text.get(hypothesis_text, {})
        support_records = analysis.get("support_records", [])
        rule_out_records = analysis.get("rule_out_records", [])
        payload = {
            "node_id": record.get("node_id"),
            "node_labels": list(record.get("node_labels", [])),
            "text": record.get("text"),
            "status": record.get("status"),
            "supporting_evidence_ids": _merge_id_lists(
                record.get("supporting_evidence_ids", []),
                [item.get("node_id") for item in support_records],
            ),
            "ruling_out_evidence_ids": _merge_id_lists(
                record.get("ruling_out_evidence_ids", []),
                [item.get("node_id") for item in rule_out_records],
            ),
            "support_edge_types": _merge_string_lists(
                record.get("support_edge_types", []),
                ["DETERMINISTIC_SUPPORT"] if support_records else [],
            ),
            "rule_out_edge_types": _merge_string_lists(
                record.get("rule_out_edge_types", []),
                ["DETERMINISTIC_RULE_OUT"] if rule_out_records else [],
            ),
        }
        if hypothesis_text in supported:
            payload["investigation_outcome"] = "supported"
        elif hypothesis_text in ruled_out:
            payload["investigation_outcome"] = "ruled_out"
        elif (
            analysis.get("rule_out_score", 0) > analysis.get("support_score", 0)
            and payload["ruling_out_evidence_ids"]
        ):
            payload["investigation_outcome"] = "ruled_out"
        elif (
            analysis.get("support_score", 0) > analysis.get("rule_out_score", 0)
            and payload["supporting_evidence_ids"]
        ):
            payload["investigation_outcome"] = "supported"
        else:
            payload["investigation_outcome"] = "considered"
        hypotheses.append(payload)
    return hypotheses


def _repair_rca_draft(rca_draft: RcaDraft, evidence_bundle: EvidenceBundle) -> RcaDraft:
    """Replace non-grounded model output with a deterministic evidence-backed fallback."""
    if _draft_is_grounded(rca_draft):
        return rca_draft
    fallback = _synthesize_evidence_backed_draft(evidence_bundle)
    return fallback or rca_draft


def _draft_is_grounded(rca_draft: RcaDraft) -> bool:
    """Return True when the draft contains a usable root cause and citations."""
    root_cause = rca_draft.root_cause.strip().lower()
    if not root_cause:
        return False
    if "unable to parse a grounded root cause" in root_cause:
        return False
    if not rca_draft.citations:
        return False
    return True


def _synthesize_evidence_backed_draft(evidence_bundle: EvidenceBundle) -> RcaDraft | None:
    """Build a deterministic RCA draft from evidence when the model output is unusable."""
    incident = evidence_bundle.incident or {}
    incident_id = str(incident.get("node_id", "")).strip()
    if not incident_id:
        return None

    scoring_report = score_hypotheses(evidence_bundle)
    if scoring_report.winning_hypothesis is None:
        return None

    runbooks = list(evidence_bundle.runbooks)
    best = scoring_report.winning_hypothesis
    best_text = best.text.strip()
    support_records = list(best.support_records)
    ruled_out_hypotheses = [
        item.text.strip()
        for item in scoring_report.hypotheses[1:]
        if item.rule_out_score > item.support_score and item.text.strip()
    ]

    citations = _select_fallback_citations(support_records)
    if not citations:
        return None

    evidence_summary = build_evidence_summary(scoring_report)
    recommended_actions = _recommended_actions_from_runbooks(runbooks)
    root_cause = compose_root_cause(scoring_report)
    if not root_cause:
        return None

    return RcaDraft(
        root_cause=root_cause,
        evidence_summary=evidence_summary,
        supported_hypotheses=[best_text],
        ruled_out_hypotheses=ruled_out_hypotheses,
        recommended_actions=recommended_actions,
        citations=citations,
        raw_model_output=rca_draft_placeholder(root_cause),
    )


def rca_draft_placeholder(root_cause: str) -> str:
    """Return a stable synthetic raw output marker for deterministic fallback drafts."""
    return f"<deterministic_fallback>{root_cause}</deterministic_fallback>"


def _citations_from_records(records: list[dict[str, Any]]) -> list[RcaCitation]:
    """Convert evidence records into RCA citations."""
    citations: list[RcaCitation] = []
    for record in records:
        node_id = str(record.get("node_id", "")).strip()
        if not node_id:
            continue
        label = _citation_label(record)
        explanation = _citation_explanation(record)
        citations.append(
            RcaCitation(
                node_id=node_id,
                node_label=label,
                explanation=explanation,
            )
        )
    return citations


def _citation_label(record: dict[str, Any]) -> str:
    """Infer a compact citation label from one evidence record."""
    node_id = str(record.get("node_id", ""))
    if node_id.startswith("deployment:"):
        return "Deployment"
    if node_id.startswith("commit:"):
        return "Commit"
    if node_id.startswith("log_event:"):
        return "LogEvent"
    if node_id.startswith("metric_series:"):
        return "MetricSeries"
    if node_id.startswith("timeline_event:"):
        return "TimelineEvent"
    if node_id.startswith("runbook:"):
        return "Runbook"
    return "Evidence"


def _citation_explanation(record: dict[str, Any]) -> str:
    """Generate a short explanation for why a record is cited."""
    for key in ("message", "event", "title", "metric", "text"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return _truncate_text(value.strip(), limit=120)
    timestamp = record.get("timestamp")
    if isinstance(timestamp, str) and timestamp.strip():
        return f"Evidence observed at {timestamp.strip()}."
    return "Evidence contributing to the RCA."


def _recommended_actions_from_runbooks(runbooks: list[dict[str, Any]]) -> list[str]:
    """Return stable recommended actions derived from matched runbooks."""
    actions: list[str] = []
    for runbook in runbooks:
        for action in runbook.get("recommended_actions", []):
            action_text = str(action).strip()
            if action_text:
                actions.append(action_text)
    return _dedupe_preserve_order(actions)[:5]


def _merge_id_lists(*values: list[Any]) -> list[str]:
    """Return stable unique string IDs while preserving first-seen order."""
    seen: set[str] = set()
    merged: list[str] = []
    for value in values:
        for item in value:
            normalized = str(item).strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            merged.append(normalized)
    return merged


def _merge_string_lists(*values: list[Any]) -> list[str]:
    """Return stable unique strings while preserving first-seen order."""
    return _merge_id_lists(*values)


def _select_fallback_citations(records: list[dict[str, Any]]) -> list[RcaCitation]:
    """Select a balanced citation set across key evidence categories."""
    selected: list[dict[str, Any]] = []
    prefixes = (
        "deployment:",
        "commit:",
        "log_event:",
        "metric_series:",
        "timeline_event:",
    )
    for prefix in prefixes:
        for record in records:
            node_id = str(record.get("node_id", "")).strip()
            if node_id.startswith(prefix) and record not in selected:
                selected.append(record)
                break
    for record in records:
        if record not in selected:
            selected.append(record)
        if len(selected) >= 10:
            break
    return _citations_from_records(selected[:10])


def _graph_relationship_summaries(traversal_result: TraversalResult) -> list[str]:
    """Return compact relationship summaries derived from traversal edges."""
    counts: dict[str, int] = {}
    for edge in traversal_result.edges:
        relationship_type = str(edge.get("relationship_type", "")).strip()
        if not relationship_type:
            continue
        counts[relationship_type] = counts.get(relationship_type, 0) + 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [f"{relationship_type} ({count})" for relationship_type, count in ordered[:8]]



def _truncate_text(value: str, *, limit: int) -> str:
    """Truncate one string deterministically."""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _traversal_summary(
    *,
    entities,
    candidates: list[IncidentCandidate],
    selected_incident_id: str,
    traversal_result: TraversalResult,
    evidence_bundle: EvidenceBundle,
    rca_draft: RcaDraft,
    include_debug: bool,
) -> dict[str, Any]:
    """Build a stable traversal summary with optional debug detail."""
    summary: dict[str, Any] = {
        "selected_incident_id": selected_incident_id,
        "candidate_count": len(candidates),
        "node_count": len(traversal_result.nodes),
        "edge_count": len(traversal_result.edges),
        "evidence_counts": {
            "deployments": len(evidence_bundle.deployments),
            "commits": len(evidence_bundle.commits),
            "metrics": len(evidence_bundle.metrics),
            "logs": len(evidence_bundle.logs),
            "timeline": len(evidence_bundle.timeline),
            "services": len(evidence_bundle.services),
            "configurations": len(evidence_bundle.configurations),
            "hypotheses": len(evidence_bundle.hypotheses),
            "runbooks": len(evidence_bundle.runbooks),
            "citations": len(evidence_bundle.citations),
        },
        "recommended_actions": list(rca_draft.recommended_actions),
        "graph_relationships": _graph_relationship_summaries(traversal_result),
    }

    if include_debug:
        summary["extracted_entities"] = {
            "incident_ids": list(entities.incident_ids),
            "services": list(entities.services),
            "symptoms": list(entities.symptoms),
            "time_references": list(entities.time_references),
            "operational_terms": list(entities.operational_terms),
            "semantic_terms": list(entities.semantic_terms),
        }
        summary["incident_candidates"] = [
            {
                "incident_id": candidate.incident_id,
                "score": candidate.score,
                "reasons": list(candidate.reasons),
            }
            for candidate in candidates
        ]
        summary["traversal_warnings"] = list(traversal_result.warnings)

    return summary


def _default_data_dir() -> Path:
    """Return the default incident fixture directory for local entity lookup."""
    return Path(__file__).resolve().parent.parent / "data" / "incidents"


def _load_known_entities(data_dir: Path) -> tuple[list[str], list[str]]:
    """Load stable service names and incident IDs from local fixture files."""
    service_names: set[str] = set()
    incident_ids: list[str] = []

    for metadata_path in sorted(data_dir.glob("*/*/metadata.json")):
        payload = json.loads(metadata_path.read_text())
        incident_id = payload.get("id")
        if isinstance(incident_id, str) and incident_id.strip():
            incident_ids.append(incident_id.strip())

        primary_service = payload.get("service")
        if isinstance(primary_service, str) and primary_service.strip():
            service_names.add(primary_service.strip())

        for service_name in payload.get("affected_services", []):
            if isinstance(service_name, str) and service_name.strip():
                service_names.add(service_name.strip())

    for services_path in sorted(data_dir.glob("*/*/services.json")):
        payload = json.loads(services_path.read_text())
        for service in payload.get("services", []):
            name = service.get("name")
            if isinstance(name, str) and name.strip():
                service_names.add(name.strip())
            for alias in service.get("aliases", []):
                if isinstance(alias, str) and alias.strip():
                    service_names.add(alias.strip())

    return sorted(service_names), _dedupe_preserve_order(incident_ids)


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return stable unique values while preserving original order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


__all__ = ["InvestigationService"]
