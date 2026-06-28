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
from prompting.types import RcaDraft
from retrieval.assembly import EvidenceAssembler
from retrieval.client import Neo4jReadClient
from retrieval.entity_extractor import EntityExtractor
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
            self.resolver = IncidentResolver(self.graph_client)

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
            return self.prompt_generator.parser.parse_strict(raw_model_output)
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
        warnings = list(traversal_result.warnings)
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

    hypotheses: list[dict[str, Any]] = []
    for record in evidence_bundle.hypotheses:
        payload = dict(record)
        hypothesis_text = str(payload.get("text", "")).strip().lower()
        if hypothesis_text in supported:
            payload["investigation_outcome"] = "supported"
        elif hypothesis_text in ruled_out:
            payload["investigation_outcome"] = "ruled_out"
        else:
            payload["investigation_outcome"] = "considered"
        hypotheses.append(payload)
    return hypotheses


def _traversal_summary(
    *,
    entities,
    candidates: list[IncidentCandidate],
    selected_incident_id: str,
    traversal_result: TraversalResult,
    evidence_bundle: EvidenceBundle,
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
    }

    if include_debug:
        summary["extracted_entities"] = {
            "incident_ids": list(entities.incident_ids),
            "services": list(entities.services),
            "symptoms": list(entities.symptoms),
            "time_references": list(entities.time_references),
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
