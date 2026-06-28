"""Runtime-safe semantic incident profiles built from benchmark metadata fixtures."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from ingestion.common.ids import incident_id as canonical_incident_id

from retrieval.query_normalization import expand_terms, normalize_text, tokenize_text


@dataclass(slots=True)
class IncidentSemanticProfile:
    """Normalized semantic metadata used to resolve paraphrased incident questions."""

    incident_id: str
    raw_incident_id: str
    title: str
    summary: str
    primary_service: str
    service_names: list[str]
    alias_names: list[str]
    tags: list[str]
    hypotheses: list[str]
    operational_context: list[str]
    semantic_terms: list[str]
    searchable_text: str


def build_incident_semantic_index(data_dir: str | Path) -> dict[str, IncidentSemanticProfile]:
    """Build deterministic incident semantic profiles from local runtime-safe fixtures."""
    root = Path(data_dir)
    profiles: dict[str, IncidentSemanticProfile] = {}

    for metadata_path in sorted(root.glob("*/*/metadata.json")):
        payload = json.loads(metadata_path.read_text())
        services_payload = _load_services_payload(metadata_path.parent / "services.json")

        raw_incident_id = str(payload.get("id", "")).strip()
        if not raw_incident_id:
            continue

        canonical_id = canonical_incident_id(raw_incident_id)
        title = str(payload.get("title", "")).strip()
        summary = str(payload.get("summary", "")).strip()
        primary_service = str(payload.get("service", "")).strip()
        affected_services = [str(item).strip() for item in payload.get("affected_services", []) if str(item).strip()]
        service_names = _dedupe_preserve_order(
            [primary_service, *affected_services, *_service_names(services_payload)]
        )
        alias_names = _dedupe_preserve_order(_service_aliases(services_payload))
        tags = [str(item).strip() for item in payload.get("tags", []) if str(item).strip()]
        hypotheses = [str(item).strip() for item in payload.get("primary_hypotheses", []) if str(item).strip()]
        operational_context = [
            _normalize_operational_context_entry(entry)
            for entry in payload.get("operational_context", [])
            if _normalize_operational_context_entry(entry)
        ]

        text_parts = [
            raw_incident_id,
            title,
            summary,
            primary_service,
            *service_names,
            *alias_names,
            *tags,
            *hypotheses,
            *operational_context,
        ]
        searchable_text = normalize_text(" ".join(part for part in text_parts if part))
        semantic_terms = expand_terms(tokenize_text(searchable_text))

        profiles[canonical_id] = IncidentSemanticProfile(
            incident_id=canonical_id,
            raw_incident_id=raw_incident_id,
            title=title,
            summary=summary,
            primary_service=primary_service,
            service_names=service_names,
            alias_names=alias_names,
            tags=tags,
            hypotheses=hypotheses,
            operational_context=operational_context,
            semantic_terms=semantic_terms,
            searchable_text=searchable_text,
        )

    return profiles


def _load_services_payload(path: Path) -> dict:
    """Load optional services.json payload when present."""
    if not path.is_file():
        return {}
    return json.loads(path.read_text())


def _service_names(payload: dict) -> list[str]:
    """Return stable service names declared in services.json."""
    return [str(item.get("name", "")).strip() for item in payload.get("services", []) if str(item.get("name", "")).strip()]


def _service_aliases(payload: dict) -> list[str]:
    """Return stable service aliases declared in services.json."""
    aliases: list[str] = []
    for service in payload.get("services", []):
        aliases.extend(
            str(alias).strip()
            for alias in service.get("aliases", [])
            if str(alias).strip()
        )
    return aliases


def _normalize_operational_context_entry(entry: object) -> str:
    """Return plain text for one operational-context entry."""
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        text = entry.get("text")
        return str(text).strip() if text is not None else ""
    return ""


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return stable unique strings preserving encounter order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


__all__ = ["IncidentSemanticProfile", "build_incident_semantic_index"]
