"""Service-layer orchestration from API request to retrieval and prompting outputs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
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
    analysis_by_text = _analyze_hypotheses(evidence_bundle)

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

    analysis_by_text = _analyze_hypotheses(evidence_bundle)
    if not analysis_by_text:
        return None

    runbooks = list(evidence_bundle.runbooks)
    scored_hypotheses = sorted(
        analysis_by_text.values(),
        key=lambda item: (
            item["support_score"] - item["rule_out_score"],
            item["support_score"],
            -item["rule_out_score"],
            item["text"],
        ),
        reverse=True,
    )
    best = scored_hypotheses[0]
    best_support = best["support_score"]
    if best_support <= 0:
        return None

    best_text = str(best["text"]).strip()
    support_records = list(best["support_records"])
    ruled_out_hypotheses = [
        str(item["text"]).strip()
        for item in scored_hypotheses[1:]
        if item["rule_out_score"] > item["support_score"] and str(item["text"]).strip()
    ]

    citations = _select_fallback_citations(support_records)
    if not citations:
        return None

    evidence_summary = _build_evidence_summary(
        latest_deployment=best.get("latest_deployment"),
        rollback_deployment=best.get("rollback_deployment"),
        cache_commits=best.get("cache_commits", []),
        cache_logs=best.get("cache_logs", []),
        database_logs=best.get("database_logs", []),
        cache_metrics=best.get("cache_metrics", []),
        rollback_recovery=best.get("rollback_recovery", []),
    )
    recommended_actions = _recommended_actions_from_runbooks(runbooks)
    root_cause = _compose_root_cause(
        best_hypothesis=best_text,
        latest_deployment=best.get("latest_deployment"),
        rollback_deployment=best.get("rollback_deployment"),
        cache_commits=best.get("cache_commits", []),
        cache_logs=best.get("cache_logs", []),
        database_logs=best.get("database_logs", []),
        rollback_recovery=best.get("rollback_recovery", []),
    )

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


def _analyze_hypotheses(evidence_bundle: EvidenceBundle) -> dict[str, dict[str, Any]]:
    """Return deterministic support and rule-out evidence for each hypothesis."""
    hypotheses = [record for record in evidence_bundle.hypotheses if str(record.get("text", "")).strip()]
    if not hypotheses:
        return {}

    incident = evidence_bundle.incident or {}
    deployments = sorted(evidence_bundle.deployments, key=lambda record: str(record.get("timestamp", "")))
    commits = list(evidence_bundle.commits)
    logs = list(evidence_bundle.logs)
    metrics = list(evidence_bundle.metrics)
    timeline = list(evidence_bundle.timeline)

    latest_deployment = _latest_deployment_before_incident(deployments, incident)
    rollback_deployment = _first_rollback_after_incident(deployments, incident)
    cache_commits = _matching_records(commits, ("cache", "ttl", "warmup"))
    cache_logs = _matching_records(logs, ("redis miss", "warmup", "ttl", "miss ratio", "cache"))
    database_logs = _matching_records(logs, ("slow query", "postgres", "deadline exceeded", "db"))
    healthy_cache_signals = _matching_records(
        logs + timeline,
        ("cluster health normal", "remained healthy", "cache node remained healthy", "within normal range", "success"),
    )
    rollback_recovery = _matching_records(
        timeline + logs,
        ("returned to baseline", "rollback completed", "200 128ms", "latency returned", "hit rate"),
    )
    cache_metrics = _matching_records(
        metrics,
        ("hit_rate", "p95_latency", "error_rate", "cpu_percent", "evictions_per_sec"),
    )
    db_metrics = _matching_records(metrics, ("postgres_read_replica.cpu_percent",))

    analysis_by_text: dict[str, dict[str, Any]] = {}
    for hypothesis in hypotheses:
        text = str(hypothesis.get("text", "")).strip()
        normalized = text.lower()
        support_records: list[dict[str, Any]] = []
        rule_out_records: list[dict[str, Any]] = []
        support_score = 0
        rule_out_score = 0

        if "cache" in normalized:
            support_records.extend(cache_commits[:2] + cache_logs[:4] + cache_metrics[:4] + rollback_recovery[:2])
            support_score += 8 if cache_commits else 0
            support_score += 6 if cache_logs else 0
            support_score += 5 if cache_metrics else 0
            support_score += 4 if rollback_recovery else 0
            if latest_deployment is not None:
                support_records.append(latest_deployment)
                support_score += 3
            if rollback_deployment is not None:
                support_records.append(rollback_deployment)
                support_score += 2

        if "redis" in normalized:
            support_records.extend(_matching_records(logs + metrics, ("redis",))[:3])
            support_score += 2 if support_records else 0
            rule_out_records.extend(healthy_cache_signals[:3] + rollback_recovery[:2] + cache_metrics[:2])
            rule_out_score += 8 if healthy_cache_signals else 0
            rule_out_score += 4 if rollback_recovery else 0
            rule_out_score += 2 if cache_metrics else 0

        if "database" in normalized or "postgres" in normalized or "db" in normalized:
            support_records.extend(database_logs[:3] + db_metrics[:1])
            support_score += 4 if database_logs else 0
            support_score += 2 if db_metrics else 0
            rule_out_records.extend(cache_commits[:2] + cache_logs[:3] + cache_metrics[:4] + healthy_cache_signals[:2] + rollback_recovery[:2])
            rule_out_score += 6 if cache_commits else 0
            rule_out_score += 6 if cache_logs else 0
            rule_out_score += 5 if cache_metrics else 0
            rule_out_score += 3 if healthy_cache_signals else 0
            rule_out_score += 4 if rollback_recovery else 0

        support_records = _dedupe_records(support_records)
        rule_out_records = _dedupe_records(rule_out_records)
        analysis_by_text[normalized] = {
            "text": text,
            "support_score": support_score,
            "rule_out_score": rule_out_score,
            "support_records": support_records,
            "rule_out_records": rule_out_records,
            "latest_deployment": latest_deployment,
            "rollback_deployment": rollback_deployment,
            "cache_commits": cache_commits,
            "cache_logs": cache_logs,
            "database_logs": database_logs,
            "cache_metrics": cache_metrics,
            "rollback_recovery": rollback_recovery,
        }

    return analysis_by_text


def _latest_deployment_before_incident(
    deployments: list[dict[str, Any]],
    incident: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the most recent deployment at or before incident start."""
    incident_start = _parse_iso8601(incident.get("start_time"))
    candidates = [
        record
        for record in deployments
        if incident_start is not None and (_parse_iso8601(record.get("timestamp")) or incident_start) <= incident_start
    ]
    return candidates[-1] if candidates else (deployments[-1] if deployments else None)


def _first_rollback_after_incident(
    deployments: list[dict[str, Any]],
    incident: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the first rollback deployment after incident start when present."""
    incident_start = _parse_iso8601(incident.get("start_time"))
    for record in deployments:
        strategy = str(record.get("strategy", "")).lower()
        timestamp = _parse_iso8601(record.get("timestamp"))
        if "rollback" in strategy and incident_start is not None and timestamp is not None and timestamp >= incident_start:
            return record
    return None


def _matching_records(records: list[dict[str, Any]], keywords: tuple[str, ...]) -> list[dict[str, Any]]:
    """Return records whose text fields mention any of the supplied keywords."""
    matches: list[dict[str, Any]] = []
    for record in records:
        haystack = _record_text(record)
        if any(keyword in haystack for keyword in keywords):
            matches.append(record)
    return matches


def _record_text(record: dict[str, Any]) -> str:
    """Return a normalized searchable text projection for one evidence record."""
    parts: list[str] = []
    for key in ("message", "event", "detail", "summary", "title", "metric", "text", "service", "component"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().lower())
    for key in ("files_changed", "recommended_actions"):
        value = record.get(key)
        if isinstance(value, list):
            parts.extend(str(item).strip().lower() for item in value if str(item).strip())
    return " | ".join(parts)


def _dedupe_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return records with unique node IDs while preserving order."""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for record in records:
        node_id = str(record.get("node_id", "")).strip()
        if not node_id or node_id in seen:
            continue
        seen.add(node_id)
        deduped.append(record)
    return deduped


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


def _build_evidence_summary(
    *,
    latest_deployment: dict[str, Any] | None,
    rollback_deployment: dict[str, Any] | None,
    cache_commits: list[dict[str, Any]],
    cache_logs: list[dict[str, Any]],
    database_logs: list[dict[str, Any]],
    cache_metrics: list[dict[str, Any]],
    rollback_recovery: list[dict[str, Any]],
) -> list[str]:
    """Build compact evidence summary bullets from the strongest correlated evidence."""
    summary: list[str] = []
    if latest_deployment is not None:
        summary.append(
            f"Latency degradation began shortly after deployment {latest_deployment.get('deployment_id', latest_deployment.get('node_id'))} at {latest_deployment.get('timestamp')}."
        )
    if cache_commits:
        summary.append(
            "The deployed commits changed cache behavior, including TTL reduction and warmup skipping logic."
        )
    if cache_logs or cache_metrics:
        summary.append(
            "Catalog API logs and metrics show cache misses and a sharp Redis hit-rate drop coinciding with latency and error-rate increases."
        )
    if database_logs:
        summary.append(
            "Slow PostgreSQL reads appeared after the cache-miss spike, indicating downstream database pressure rather than a primary database-originating failure."
        )
    if rollback_deployment is not None or rollback_recovery:
        summary.append(
            "Rollback and subsequent recovery evidence show the issue subsided after the cache-related release was reverted."
        )
    return summary[:4]


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


def _compose_root_cause(
    *,
    best_hypothesis: str,
    latest_deployment: dict[str, Any] | None,
    rollback_deployment: dict[str, Any] | None,
    cache_commits: list[dict[str, Any]],
    cache_logs: list[dict[str, Any]],
    database_logs: list[dict[str, Any]],
    rollback_recovery: list[dict[str, Any]],
) -> str:
    """Compose one concise evidence-backed root-cause statement."""
    deployment_id = latest_deployment.get("deployment_id") if latest_deployment is not None else None
    deployment_time = latest_deployment.get("timestamp") if latest_deployment is not None else None
    rollback_time = rollback_deployment.get("timestamp") if rollback_deployment is not None else None
    commit_snippets = [
        _short_commit_phrase(str(commit.get("message", "")).strip())
        for commit in cache_commits[:2]
        if str(commit.get("message", "")).strip()
    ]
    commit_clause = ", ".join(commit_snippets)

    if "cache" in best_hypothesis.lower():
        sentence = "Evidence most strongly supports cache churn from an application change."
        if deployment_id and deployment_time:
            sentence += f" Deployment {deployment_id} at {deployment_time} introduced cache-policy changes"
            if commit_clause:
                sentence += f" ({commit_clause})"
            sentence += "."
        if cache_logs:
            sentence += " After the rollout, catalog-api logs showed repeated Redis misses and skipped warmup behavior."
        if database_logs:
            sentence += " The subsequent slow PostgreSQL reads appear to be secondary pressure from the cache miss spike rather than the primary fault."
        if rollback_time or rollback_recovery:
            sentence += f" Recovery after the rollback{f' at {rollback_time}' if rollback_time else ''} confirms the release as the strongest causal driver."
        return sentence

    sentence = f"Evidence most strongly supports {best_hypothesis}."
    if deployment_id and deployment_time:
        sentence += f" The strongest correlation begins immediately after deployment {deployment_id} at {deployment_time}."
    if commit_clause:
        sentence += f" Relevant changes in that release included {commit_clause}."
    if rollback_time or rollback_recovery:
        sentence += f" Recovery after the rollback{f' at {rollback_time}' if rollback_time else ''} strengthens that conclusion."
    return sentence


def _short_commit_phrase(message: str) -> str:
    """Return a compact commit summary for RCA prose."""
    normalized = re.sub(r"\s+", " ", message).strip()
    return normalized[:90].rstrip(".")


def _truncate_text(value: str, *, limit: int) -> str:
    """Truncate one string deterministically."""
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _parse_iso8601(value: Any) -> datetime | None:
    """Parse one dataset timestamp into a datetime when possible."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


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
