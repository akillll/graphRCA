"""Incident candidate resolution from extracted entities and graph lookups."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ingestion.common.ids import incident_id as canonical_incident_id
from retrieval.client import Neo4jReadClient
from retrieval.incident_index import IncidentSemanticProfile, build_incident_semantic_index
from retrieval.query_normalization import overlap_terms, singularize_token, tokenize_text
from retrieval.queries import (
    ALL_INCIDENTS_QUERY,
    INCIDENT_BY_ID_QUERY,
    INCIDENTS_BY_PRIMARY_SERVICE_QUERY,
    SERVICE_BY_ALIAS_QUERY,
    SERVICE_BY_NAME_QUERY,
)
from retrieval.types import ExtractedEntities, IncidentCandidate


@dataclass(slots=True)
class _CandidateState:
    """Internal mutable scoring state before converting to IncidentCandidate."""

    incident_id: str
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)

    def add(self, score_delta: float, reason: str) -> None:
        """Accumulate score and keep unique ranking reasons."""
        self.score += score_delta
        if reason not in self.reasons:
            self.reasons.append(reason)


class IncidentResolver:
    """Resolve extracted entities into ranked incident candidates using graph and semantic fixture hints."""

    def __init__(
        self,
        client: Neo4jReadClient,
        *,
        incident_index: dict[str, IncidentSemanticProfile] | None = None,
    ) -> None:
        """Initialize the resolver with a read-only Neo4j client and optional semantic index."""
        self._client = client
        self._incident_index = incident_index or {}

    @classmethod
    def from_env(cls, env_path: str = ".env", *, data_dir: str | Path | None = None) -> "IncidentResolver":
        """Build a resolver from `.env`-backed Neo4j settings and optional local incident profiles."""
        incident_index = build_incident_semantic_index(data_dir) if data_dir is not None else None
        return cls(Neo4jReadClient.from_env(env_path), incident_index=incident_index)

    def resolve(self, entities: ExtractedEntities) -> list[IncidentCandidate]:
        """Return ranked candidate incidents without traversing the full evidence graph."""
        candidates: dict[str, _CandidateState] = {}
        incident_payloads = self._all_incident_payloads()

        self._add_incident_id_matches(candidates, entities)
        self._add_service_name_matches(candidates, entities)
        self._add_service_alias_matches(candidates, entities)
        self._add_semantic_profile_matches(candidates, entities, incident_payloads)
        self._add_broad_incident_matches(candidates, entities, incident_payloads)
        self._apply_time_hint_adjustments(candidates, entities.time_references)
        self._apply_signal_quality_adjustments(candidates, entities)

        ranked = sorted(
            candidates.values(),
            key=lambda candidate: (-candidate.score, candidate.incident_id),
        )
        return [
            IncidentCandidate(
                incident_id=candidate.incident_id,
                score=round(candidate.score, 3),
                reasons=candidate.reasons,
            )
            for candidate in ranked
            if candidate.score >= 0.25
        ]

    def __call__(self, entities: ExtractedEntities) -> list[IncidentCandidate]:
        """Allow the resolver to be used as a small callable helper."""
        return self.resolve(entities)

    def _all_incident_payloads(self) -> dict[str, dict[str, Any]]:
        """Load one compact payload per incident for broad resolution scoring."""
        payloads: dict[str, dict[str, Any]] = {}
        rows = self._client.run_query(ALL_INCIDENTS_QUERY)
        for row in rows:
            payload = row.get("result", {})
            incident = payload.get("incident") or {}
            node_id = str(incident.get("node_id", "")).strip()
            if not node_id:
                continue
            payloads[node_id] = incident
        return payloads

    def _add_incident_id_matches(
        self,
        candidates: dict[str, _CandidateState],
        entities: ExtractedEntities,
    ) -> None:
        """Add exact incident-ID matches first with the highest base score."""
        for incident_id in entities.incident_ids:
            rows = self._client.run_query(
                INCIDENT_BY_ID_QUERY,
                {"incident_id": _to_canonical_incident_id(incident_id)},
            )
            for row in rows:
                payload = row.get("result", {})
                incident = payload.get("incident") or {}
                state = self._candidate_state(candidates, incident)
                state.add(1.2, f"exact incident ID match: {incident_id}")

    def _add_service_name_matches(
        self,
        candidates: dict[str, _CandidateState],
        entities: ExtractedEntities,
    ) -> None:
        """Add candidates by exact service-name matches against primary incident service."""
        for service_name in entities.services:
            service_rows = self._client.run_query(SERVICE_BY_NAME_QUERY, {"service_name": service_name})
            if not service_rows:
                continue

            rows = self._client.run_query(INCIDENTS_BY_PRIMARY_SERVICE_QUERY, {"service_name": service_name})
            for row in rows:
                payload = row.get("result", {})
                incident = payload.get("incident") or {}
                state = self._candidate_state(candidates, incident)
                state.add(0.8, f"primary service match: {service_name}")

    def _add_service_alias_matches(
        self,
        candidates: dict[str, _CandidateState],
        entities: ExtractedEntities,
    ) -> None:
        """Add candidates by resolving service aliases to canonical service names."""
        for service_alias in entities.services:
            alias_rows = self._client.run_query(SERVICE_BY_ALIAS_QUERY, {"service_alias": service_alias})
            for row in alias_rows:
                payload = row.get("result", {})
                service = payload.get("service") or {}
                properties = service.get("properties") or {}
                canonical_name = properties.get("name")
                if not canonical_name:
                    continue

                incident_rows = self._client.run_query(
                    INCIDENTS_BY_PRIMARY_SERVICE_QUERY,
                    {"service_name": canonical_name},
                )
                for incident_row in incident_rows:
                    incident_payload = incident_row.get("result", {})
                    incident = incident_payload.get("incident") or {}
                    state = self._candidate_state(candidates, incident)
                    state.add(0.55, f"service alias match: {service_alias} -> {canonical_name}")

    def _add_semantic_profile_matches(
        self,
        candidates: dict[str, _CandidateState],
        entities: ExtractedEntities,
        incident_payloads: dict[str, dict[str, Any]],
    ) -> None:
        """Add semantic boosts using deterministic incident profiles from runtime-safe fixtures."""
        if not self._incident_index:
            return

        for incident_id, profile in self._incident_index.items():
            incident_payload = incident_payloads.get(incident_id)
            if incident_payload is None:
                incident_payload = {
                    "node_id": incident_id,
                    "properties": {
                        "id": incident_id,
                        "title": profile.title,
                        "summary": profile.summary,
                        "service": profile.primary_service,
                        "tags": profile.tags,
                    },
                }
            state = self._candidate_state(candidates, incident_payload)

            semantic_overlap = overlap_terms(entities.semantic_terms, profile.semantic_terms)
            if semantic_overlap:
                score = min(0.45, 0.06 * len(semantic_overlap))
                state.add(score, f"semantic overlap: {', '.join(semantic_overlap[:4])}")

            symptom_overlap = overlap_terms(entities.symptom_mentions, profile.semantic_terms)
            if symptom_overlap:
                score = min(0.35, 0.12 * len(symptom_overlap))
                state.add(score, f"symptom overlap: {', '.join(symptom_overlap[:3])}")

            operational_overlap = overlap_terms(entities.operational_terms, profile.semantic_terms)
            if operational_overlap:
                score = min(0.35, 0.14 * len(operational_overlap))
                state.add(score, f"operational overlap: {', '.join(operational_overlap[:3])}")

            service_family_overlap = overlap_terms(
                entities.semantic_terms,
                tokenize_text(" ".join([*profile.service_names, *profile.alias_names]), min_length=2),
            )
            if service_family_overlap and not entities.services:
                score = min(0.25, 0.08 * len(service_family_overlap))
                state.add(score, f"service-family overlap: {', '.join(service_family_overlap[:3])}")

    def _add_broad_incident_matches(
        self,
        candidates: dict[str, _CandidateState],
        entities: ExtractedEntities,
        incident_payloads: dict[str, dict[str, Any]],
    ) -> None:
        """Seed candidates from broad incident metadata when exact service matching is absent."""
        question_tokens = entities.semantic_terms or _question_tokens(entities.raw_question)
        if not question_tokens and not entities.time_references and not entities.symptoms:
            return

        for incident in incident_payloads.values():
            state = self._candidate_state(candidates, incident)
            searchable = _incident_searchable_text(state.properties)
            matched_tokens = [
                token
                for token in question_tokens
                if len(token) >= 4 and (token in searchable or singularize_token(token) in searchable)
            ]
            for token in matched_tokens[:5]:
                state.add(0.08, f"incident text match: {token}")

            if entities.symptoms:
                matched_symptoms = [symptom for symptom in entities.symptoms if symptom.lower() in searchable]
                for symptom in matched_symptoms:
                    state.add(0.12, f"incident symptom text match: {symptom}")

    def _apply_time_hint_adjustments(
        self,
        candidates: dict[str, _CandidateState],
        time_references: list[str],
    ) -> None:
        """Boost or penalize candidates based on conservative explicit time matches."""
        if not time_references:
            return

        for candidate in candidates.values():
            matches = [hint for hint in time_references if _incident_matches_time_hint(candidate.properties, hint)]
            if matches:
                for hint in matches:
                    candidate.add(0.25, f"time hint match: {hint}")
            else:
                candidate.score = max(0.0, candidate.score - 0.1)
                if "time hints did not match incident window" not in candidate.reasons:
                    candidate.reasons.append("time hints did not match incident window")

    def _apply_signal_quality_adjustments(
        self,
        candidates: dict[str, _CandidateState],
        entities: ExtractedEntities,
    ) -> None:
        """Nudge candidates based on overall signal quality and contradictory gaps."""
        for candidate in candidates.values():
            reasons_text = " ".join(candidate.reasons).lower()
            has_exact_signal = "exact incident id match" in reasons_text or "primary service match" in reasons_text
            has_semantic_signal = any(
                phrase in reasons_text
                for phrase in ("semantic overlap", "symptom overlap", "operational overlap", "service-family overlap")
            )

            if has_exact_signal and has_semantic_signal:
                candidate.add(0.1, "exact and semantic signals agree")
            elif not has_exact_signal and has_semantic_signal and entities.services:
                candidate.score = max(0.0, candidate.score - 0.05)
                if "no exact service alignment" not in candidate.reasons:
                    candidate.reasons.append("no exact service alignment")

    @staticmethod
    def _candidate_state(
        candidates: dict[str, _CandidateState],
        incident_payload: dict[str, Any],
    ) -> _CandidateState:
        """Get or create mutable candidate state from a query result payload."""
        incident_id = str(incident_payload.get("node_id", ""))
        if not incident_id:
            raise ValueError("Incident query result is missing node_id.")

        state = candidates.get(incident_id)
        if state is None:
            state = _CandidateState(
                incident_id=incident_id,
                properties=dict(incident_payload.get("properties") or {}),
            )
            candidates[incident_id] = state
        elif not state.properties:
            state.properties = dict(incident_payload.get("properties") or {})
        return state


def _incident_matches_time_hint(properties: dict[str, Any], hint: str) -> bool:
    """Return True when a conservative explicit time hint matches incident metadata."""
    normalized_hint = hint.strip()
    if not normalized_hint:
        return False

    incident_id = str(properties.get("id", ""))
    start_time = str(properties.get("start_time", ""))
    end_time = str(properties.get("end_time", ""))
    haystacks = [incident_id, start_time, end_time]

    if any(normalized_hint in value for value in haystacks):
        return True

    parsed_hint = _parse_time_hint(normalized_hint)
    if parsed_hint is None:
        return False

    start_dt = _parse_iso_datetime(start_time)
    end_dt = _parse_iso_datetime(end_time)

    if parsed_hint["kind"] == "month_day":
        month = parsed_hint["month"]
        day = parsed_hint["day"]
        return any(dt is not None and dt.month == month and dt.day == day for dt in (start_dt, end_dt))

    if parsed_hint["kind"] == "date":
        year = parsed_hint["year"]
        month = parsed_hint["month"]
        day = parsed_hint["day"]
        return any(
            dt is not None and dt.year == year and dt.month == month and dt.day == day
            for dt in (start_dt, end_dt)
        )

    if parsed_hint["kind"] == "time":
        hour = parsed_hint["hour"]
        minute = parsed_hint["minute"]
        return any(dt is not None and dt.hour == hour and dt.minute == minute for dt in (start_dt, end_dt))

    return False


def _to_canonical_incident_id(value: str) -> str:
    """Normalize a raw fixture incident ID into the canonical graph ID."""
    return value if value.startswith("incident:") else canonical_incident_id(value)


def _parse_iso_datetime(value: str) -> datetime | None:
    """Parse one ISO-like incident timestamp conservatively."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_time_hint(hint: str) -> dict[str, int | str] | None:
    """Parse supported explicit date or time hints into comparable parts."""
    normalized = hint.strip()

    if len(normalized) == 10 and normalized[4] == "-" and normalized[7] == "-":
        try:
            year, month, day = (int(part) for part in normalized.split("-"))
        except ValueError:
            return None
        return {"kind": "date", "year": year, "month": month, "day": day}

    if len(normalized) == 10 and normalized[4] == "_" and normalized[7] == "_":
        try:
            year, month, day = (int(part) for part in normalized.split("_"))
        except ValueError:
            return None
        return {"kind": "date", "year": year, "month": month, "day": day}

    if ":" in normalized:
        try:
            clock, suffix = _split_clock_and_suffix(normalized)
            hour_text, minute_text, *_ = clock.split(":")
            hour = int(hour_text)
            minute = int(minute_text)
            if suffix == "pm" and hour != 12:
                hour += 12
            if suffix == "am" and hour == 12:
                hour = 0
            return {"kind": "time", "hour": hour, "minute": minute}
        except ValueError:
            return None

    month_day = _parse_month_day_hint(normalized)
    if month_day is not None:
        return month_day

    return None


def _split_clock_and_suffix(value: str) -> tuple[str, str | None]:
    """Split a clock string from an optional am/pm suffix."""
    parts = value.strip().split()
    if len(parts) == 1:
        return parts[0], None
    return parts[0], parts[1].lower()


def _parse_month_day_hint(value: str) -> dict[str, int | str] | None:
    """Parse `April 21` or `April 21, 2026` into comparable date parts."""
    cleaned = value.replace(",", "")
    parts = cleaned.split()
    if len(parts) not in {2, 3}:
        return None

    month_lookup = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }
    month = month_lookup.get(parts[0].lower())
    if month is None:
        return None

    try:
        day = int(parts[1])
    except ValueError:
        return None

    if len(parts) == 3:
        try:
            year = int(parts[2])
        except ValueError:
            return None
        return {"kind": "date", "year": year, "month": month, "day": day}

    return {"kind": "month_day", "month": month, "day": day}


def _question_tokens(question: str) -> list[str]:
    """Return stable searchable tokens from the raw user question."""
    return tokenize_text(question)


def _incident_searchable_text(properties: dict[str, Any]) -> str:
    """Return a normalized searchable projection for one incident."""
    parts: list[str] = []
    for key in ("id", "title", "summary", "service", "severity", "difficulty"):
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            parts.append(value.strip().lower())
    tags = properties.get("tags")
    if isinstance(tags, list):
        parts.extend(str(item).strip().lower() for item in tags if str(item).strip())
    return " | ".join(parts)
