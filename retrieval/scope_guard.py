"""Question-scope guardrails for the GraphRCA investigation surface."""

from __future__ import annotations

from dataclasses import dataclass, field

from retrieval.query_normalization import tokenize_text
from retrieval.types import ExtractedEntities


_DOMAIN_TERMS = frozenset(
    {
        "incident",
        "investigate",
        "investigation",
        "root",
        "cause",
        "rca",
        "service",
        "deployment",
        "deploy",
        "rollback",
        "latency",
        "timeout",
        "error",
        "failure",
        "degradation",
        "degraded",
        "delay",
        "delays",
        "metric",
        "metrics",
        "log",
        "logs",
        "runbook",
        "evidence",
        "hypothesis",
        "queue",
        "cache",
        "worker",
        "database",
        "redis",
        "tls",
        "replica",
        "mesh",
        "webhook",
        "notification",
        "notifications",
        "memory",
        "reconnect",
        "replay",
        "autoscaling",
        "network",
        "policy",
        "spike",
        "storm",
        "tenant",
        "tenants",
    }
)

_INTENT_TERMS = frozenset({"why", "what", "how", "caused", "cause", "explain", "investigate", "rca"})


@dataclass(frozen=True, slots=True)
class ScopeAssessment:
    """Deterministic classification of a user question for GraphRCA."""

    classification: str
    reason: str
    matched_terms: list[str] = field(default_factory=list)


@dataclass(slots=True)
class QuestionScopeGuard:
    """Classify whether a question belongs on the GraphRCA investigation path."""

    known_services: list[str] = field(default_factory=list)
    known_incident_ids: list[str] = field(default_factory=list)

    def assess(
        self,
        question: str,
        entities: ExtractedEntities,
        *,
        incident_id: str | None = None,
    ) -> ScopeAssessment:
        """Return a conservative scope assessment for one incoming question."""
        if incident_id and incident_id.strip():
            return ScopeAssessment(
                classification="in_scope",
                reason="Explicit incident ID override supplied with the request.",
                matched_terms=[incident_id.strip()],
            )

        if entities.incident_ids or entities.services or entities.symptoms or entities.operational_terms:
            return ScopeAssessment(
                classification="in_scope",
                reason="The question references known incident-investigation entities or operational signals.",
                matched_terms=_matched_terms_from_entities(entities),
            )

        question_tokens = set(tokenize_text(question, min_length=2))
        service_tokens = _service_tokens(self.known_services)
        semantic_tokens = {token for token in entities.semantic_terms if token}
        matched_terms = sorted(
            question_tokens.intersection(_DOMAIN_TERMS.union(service_tokens)).union(
                semantic_tokens.intersection(_DOMAIN_TERMS.union(service_tokens))
            )
        )
        has_investigation_intent = bool(question_tokens.intersection(_INTENT_TERMS))
        has_time_anchor = bool(entities.time_references)
        has_semantic_signal = bool(semantic_tokens.intersection(_DOMAIN_TERMS.union(service_tokens)))

        if matched_terms and has_investigation_intent:
            return ScopeAssessment(
                classification="in_scope",
                reason="The question uses investigation intent and GraphRCA domain language.",
                matched_terms=matched_terms[:8],
            )

        if has_time_anchor and (matched_terms or has_semantic_signal or len(question_tokens) >= 4):
            return ScopeAssessment(
                classification="ambiguous_in_scope",
                reason="The question is time-anchored and operationally phrased, so it should be resolved against benchmark incidents.",
                matched_terms=(matched_terms or list(semantic_tokens) or list(question_tokens))[:8],
            )

        if len(matched_terms) >= 2 or has_semantic_signal:
            return ScopeAssessment(
                classification="ambiguous_in_scope",
                reason="The question appears operational, but it is not anchored strongly enough to one benchmark incident.",
                matched_terms=(matched_terms or list(semantic_tokens))[:8],
            )

        return ScopeAssessment(
            classification="out_of_scope",
            reason="The question does not look like an incident investigation against the benchmark dataset.",
            matched_terms=matched_terms[:8],
        )


def _service_tokens(services: list[str]) -> set[str]:
    """Return stable lexical tokens derived from known service names."""
    tokens: set[str] = set()
    for service in services:
        tokens.update(tokenize_text(service, min_length=2))
    return tokens


def _matched_terms_from_entities(entities: ExtractedEntities) -> list[str]:
    """Return a compact set of matched entity hints for display."""
    values = [
        *entities.incident_ids,
        *entities.services,
        *entities.symptoms,
        *entities.time_references,
        *entities.operational_terms,
        *entities.semantic_terms,
    ]
    seen: set[str] = set()
    matched: list[str] = []
    for value in values:
        normalized = str(value).strip()
        lowered = normalized.lower()
        if not normalized or lowered in seen:
            continue
        seen.add(lowered)
        matched.append(normalized)
    return matched[:8]


__all__ = ["QuestionScopeGuard", "ScopeAssessment"]
