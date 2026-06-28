"""Deterministic extraction of incident, service, symptom, and time hints from questions."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from retrieval.query_normalization import expand_terms, normalize_text, tokenize_text
from retrieval.types import ExtractedEntities


_INCIDENT_ID_RE = re.compile(r"\b(?:easy|medium|hard)_[a-z0-9_]+_\d{4}_\d{2}_\d{2}\b", re.IGNORECASE)
_ISO_DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_UNDERSCORE_DATE_RE = re.compile(r"\b\d{4}_\d{2}_\d{2}\b")
_MONTH_DAY_RE = re.compile(
    r"\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|"
    r"aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\s+\d{1,2}"
    r"(?:,\s*\d{4})?\b",
    re.IGNORECASE,
)
_TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm|AM|PM)?\b")

_SYMPTOM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("timeout chain", re.compile(r"\btimeout chain\b", re.IGNORECASE)),
    ("latency spike", re.compile(r"\blatency spike\b", re.IGNORECASE)),
    ("memory leak", re.compile(r"\bmemory leak\b", re.IGNORECASE)),
    ("replica lag", re.compile(r"\breplica lag\b", re.IGNORECASE)),
    ("cache stampede", re.compile(r"\bcache stampede\b", re.IGNORECASE)),
    ("replay storm", re.compile(r"\breplay storm\b", re.IGNORECASE)),
    ("reconnect storm", re.compile(r"\breconnect storm\b", re.IGNORECASE)),
    ("retry amplification", re.compile(r"\bretry amplification\b", re.IGNORECASE)),
    ("pool exhaustion", re.compile(r"\bpool exhaustion\b", re.IGNORECASE)),
    ("tls misconfig", re.compile(r"\btls misconfig(?:uration)?\b", re.IGNORECASE)),
    ("backlog", re.compile(r"\bbacklog\b", re.IGNORECASE)),
    ("saturation", re.compile(r"\bsaturation\b", re.IGNORECASE)),
    ("timeout", re.compile(r"\btimeouts?\b", re.IGNORECASE)),
    ("latency", re.compile(r"\blatency\b", re.IGNORECASE)),
    ("spike", re.compile(r"\bspike\b", re.IGNORECASE)),
    ("error", re.compile(r"\berrors?\b", re.IGNORECASE)),
    ("failure", re.compile(r"\bfail(?:ed|ure|ures)?\b", re.IGNORECASE)),
    ("disconnect", re.compile(r"\bdisconnect(?:ed|s|ion)?\b", re.IGNORECASE)),
    ("reconnect", re.compile(r"\breconnect(?:ed|s|ion)?\b", re.IGNORECASE)),
    ("regression", re.compile(r"\bregression\b", re.IGNORECASE)),
)

_OPERATIONAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("recent deploy", re.compile(r"\b(?:after|following)\s+(?:the\s+)?(?:deploy|deployment|rollout)\b", re.IGNORECASE)),
    ("rollback", re.compile(r"\brollback\b", re.IGNORECASE)),
    ("tenant migration", re.compile(r"\btenant migration\b", re.IGNORECASE)),
    ("partial outage", re.compile(r"\bpartial (?:outage|degradation|failure)\b", re.IGNORECASE)),
    ("new purchase", re.compile(r"\b(?:newly purchased|recently updated|new purchase)\b", re.IGNORECASE)),
    ("batch job", re.compile(r"\b(?:batch job|backfill|reconciliation)\b", re.IGNORECASE)),
    ("traffic increase", re.compile(r"\b(?:traffic surge|increased traffic|campaign)\b", re.IGNORECASE)),
    ("worker restart", re.compile(r"\b(?:restart|oomkilled|oom killed)\b", re.IGNORECASE)),
)


@dataclass(slots=True)
class EntityExtractor:
    """Deterministic entity extractor for retrieval-time incident questions."""

    known_services: list[str] = field(default_factory=list)
    known_incident_ids: list[str] = field(default_factory=list)

    def extract(
        self,
        question: str,
        known_services: list[str] | None = None,
        known_incident_ids: list[str] | None = None,
    ) -> ExtractedEntities:
        """Extract explicit incident IDs, exact services, symptoms, and time references."""
        service_candidates = known_services if known_services is not None else self.known_services
        incident_candidates = known_incident_ids if known_incident_ids is not None else self.known_incident_ids

        normalized_question = normalize_text(question)
        incident_ids = self._extract_incident_ids(question, incident_candidates)
        services = self._extract_services(question, service_candidates)
        symptoms = self._extract_symptoms(question)
        time_references = self._extract_time_references(question)
        operational_terms = self._extract_operational_terms(question)
        semantic_terms = self._extract_semantic_terms(
            question=question,
            services=services,
            symptoms=symptoms,
            operational_terms=operational_terms,
        )

        return ExtractedEntities(
            raw_question=question,
            normalized_question=normalized_question,
            incident_ids=incident_ids,
            services=services,
            symptoms=symptoms,
            time_references=time_references,
            service_mentions=list(services),
            symptom_mentions=list(symptoms),
            operational_terms=operational_terms,
            semantic_terms=semantic_terms,
        )

    def __call__(
        self,
        question: str,
        known_services: list[str] | None = None,
        known_incident_ids: list[str] | None = None,
    ) -> ExtractedEntities:
        """Allow the extractor to be used as a small callable helper."""
        return self.extract(
            question=question,
            known_services=known_services,
            known_incident_ids=known_incident_ids,
        )

    @staticmethod
    def _extract_incident_ids(question: str, known_incident_ids: list[str]) -> list[str]:
        """Return explicit incident IDs mentioned in the question."""
        matches: list[str] = []
        known_lookup = {incident_id.lower(): incident_id for incident_id in known_incident_ids}

        for match in _INCIDENT_ID_RE.findall(question):
            normalized = match.lower()
            matches.append(known_lookup.get(normalized, match))

        return _dedupe_preserve_order(matches)

    @staticmethod
    def _extract_services(question: str, known_services: list[str]) -> list[str]:
        """Return exact known service names mentioned in the question."""
        matches: list[str] = []
        for service_name in sorted(known_services, key=len, reverse=True):
            if not service_name:
                continue
            pattern = re.compile(rf"(?<![a-z0-9_-]){re.escape(service_name)}(?![a-z0-9_-])", re.IGNORECASE)
            if pattern.search(question):
                matches.append(service_name)
        return _dedupe_preserve_order(matches)

    @staticmethod
    def _extract_symptoms(question: str) -> list[str]:
        """Return symptom keywords or phrases directly present in the question."""
        matches: list[str] = []
        for label, pattern in _SYMPTOM_PATTERNS:
            if pattern.search(question):
                matches.append(label)
        return _dedupe_preserve_order(_drop_subsumed_symptoms(matches))

    @staticmethod
    def _extract_time_references(question: str) -> list[str]:
        """Return conservative explicit date or clock references from the question."""
        matches: list[str] = []
        for pattern in (_ISO_DATE_RE, _MONTH_DAY_RE, _TIME_RE):
            matches.extend(match.group(0) for match in pattern.finditer(question))

        for match in _UNDERSCORE_DATE_RE.finditer(question):
            value = match.group(0)
            if value not in matches:
                matches.append(value)

        return _dedupe_preserve_order(matches)

    @staticmethod
    def _extract_operational_terms(question: str) -> list[str]:
        """Return deterministic operational-context hints present in the question."""
        matches: list[str] = []
        for label, pattern in _OPERATIONAL_PATTERNS:
            if pattern.search(question):
                matches.append(label)
        return _dedupe_preserve_order(matches)

    @staticmethod
    def _extract_semantic_terms(
        *,
        question: str,
        services: list[str],
        symptoms: list[str],
        operational_terms: list[str],
    ) -> list[str]:
        """Return normalized query terms plus deterministic domain expansions."""
        base_terms = tokenize_text(question)
        for service in services:
            base_terms.extend(tokenize_text(service, min_length=2))
        for symptom in symptoms:
            base_terms.extend(tokenize_text(symptom))
        for term in operational_terms:
            base_terms.extend(tokenize_text(term))
        return _dedupe_preserve_order(expand_terms(base_terms))


def _drop_subsumed_symptoms(symptoms: list[str]) -> list[str]:
    """Remove broader symptom labels when a more specific phrase is already present."""
    symptom_set = set(symptoms)
    filtered = list(symptoms)

    if "latency spike" in symptom_set:
        filtered = [symptom for symptom in filtered if symptom not in {"latency", "spike"}]
    if "timeout chain" in symptom_set:
        filtered = [symptom for symptom in filtered if symptom != "timeout"]
    if "reconnect storm" in symptom_set:
        filtered = [symptom for symptom in filtered if symptom != "reconnect"]
    if "replay storm" in symptom_set:
        filtered = [symptom for symptom in filtered if symptom != "reconnect"]

    return filtered


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return stable unique values preserving the original encounter order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped
