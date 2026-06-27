"""Canonical ID helpers for ingestion payloads."""

from __future__ import annotations

import re


_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Return a stable slug used in canonical graph identifiers."""
    normalized = value.strip().lower()
    slug = _NON_ALNUM_RE.sub("_", normalized).strip("_")
    return slug or "empty"


def incident_id(metadata_id: str) -> str:
    """Build the canonical Incident ID."""
    return f"incident:{metadata_id}"


def service_id(service_name: str) -> str:
    """Build the canonical Service ID."""
    return f"service:{service_name}"


def deployment_id(deployment_name: str) -> str:
    """Build the canonical Deployment ID."""
    return f"deployment:{deployment_name}"


def commit_id(commit_hash: str) -> str:
    """Build the canonical Commit ID."""
    return f"commit:{commit_hash}"


def metric_id(metric_name: str) -> str:
    """Build the canonical Metric ID."""
    return f"metric:{metric_name}"


def metric_series_id(incident_name: str, metric_name: str) -> str:
    """Build the canonical MetricSeries ID."""
    return f"metric_series:{incident_name}:{metric_name}"


def log_event_id(incident_name: str, timestamp: str, trace_or_sequence: str) -> str:
    """Build the canonical LogEvent ID."""
    return f"log_event:{incident_name}:{timestamp}:{trace_or_sequence}"


def log_event_sequence(index: int) -> str:
    """Return the stable fallback log sequence token."""
    return f"seq_{index}"


def timeline_event_id(incident_name: str, timestamp: str, sequence: int) -> str:
    """Build the canonical TimelineEvent ID."""
    return f"timeline_event:{incident_name}:{timestamp}:{sequence}"


def runbook_id(filename: str) -> str:
    """Build the canonical Runbook ID."""
    return f"runbook:{filename}"


def action_id(source_id: str, action_text: str) -> str:
    """Build the canonical Action ID."""
    return f"action:{source_id}:{slugify(action_text)}"


def hypothesis_id(incident_name: str, hypothesis_text: str) -> str:
    """Build the canonical Hypothesis ID."""
    return f"hypothesis:{incident_name}:{slugify(hypothesis_text)}"


def configuration_id(incident_name: str, text_or_sequence: str) -> str:
    """Build the canonical Configuration ID."""
    return f"config:{incident_name}:{slugify(text_or_sequence)}"


def log_pattern_id(incident_name: str, pattern: str) -> str:
    """Build the canonical LogPattern ID."""
    return f"log_pattern:{incident_name}:{slugify(pattern)}"
