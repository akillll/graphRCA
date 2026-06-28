"""Deterministic text normalization helpers for semantic incident resolution."""

from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"[a-z0-9]+")

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "at",
        "be",
        "caused",
        "cause",
        "did",
        "do",
        "does",
        "for",
        "from",
        "how",
        "in",
        "into",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "their",
        "them",
        "there",
        "these",
        "this",
        "to",
        "was",
        "were",
        "what",
        "when",
        "where",
        "which",
        "why",
    }
)

_SYNONYM_GROUPS: tuple[tuple[str, ...], ...] = (
    ("latency", "slow", "slowness", "degraded", "degradation"),
    ("timeout", "timeouts", "timed", "deadline"),
    ("error", "errors", "failure", "failed", "failing"),
    ("backlog", "queued", "queueing", "delay", "delays"),
    ("replica", "stale", "freshness", "consistency"),
    ("memory", "heap", "oom", "oomkilled", "rss", "leak"),
    ("autoscaling", "autoscaler", "scale", "scaling"),
    ("retry", "retries", "retrying", "amplification"),
    ("cache", "caching", "miss", "warmup", "stampede"),
    ("reconnect", "disconnect", "connection", "storm"),
    ("tenant", "shard", "migration", "skew"),
    ("subscription", "entitlement", "premium", "access"),
    ("media", "image", "photo", "avatar", "upload"),
)

_SYNONYM_MAP = {
    term: tuple(sorted({member for member in group if member != term}))
    for group in _SYNONYM_GROUPS
    for term in group
}


def normalize_text(value: str) -> str:
    """Return a lowercase normalized text string with compact spacing."""
    return " ".join(_TOKEN_RE.findall(value.lower()))


def singularize_token(token: str) -> str:
    """Return a lightweight singularized token for lexical matching."""
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("s") and not token.endswith("ss") and len(token) > 4:
        return token[:-1]
    return token


def tokenize_text(value: str, *, min_length: int = 3, drop_stopwords: bool = True) -> list[str]:
    """Return stable normalized tokens from free text."""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw_token in _TOKEN_RE.findall(value.lower()):
        token = singularize_token(raw_token)
        if len(token) < min_length:
            continue
        if drop_stopwords and token in _STOPWORDS:
            continue
        if token in seen:
            continue
        seen.add(token)
        tokens.append(token)
    return tokens


def expand_terms(terms: list[str]) -> list[str]:
    """Return stable terms plus deterministic synonym expansions."""
    expanded: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = singularize_token(term.lower())
        if normalized not in seen:
            seen.add(normalized)
            expanded.append(normalized)
        for synonym in _SYNONYM_MAP.get(normalized, ()):
            canonical = singularize_token(synonym.lower())
            if canonical in seen:
                continue
            seen.add(canonical)
            expanded.append(canonical)
    return expanded


def overlap_terms(left: list[str] | set[str], right: list[str] | set[str]) -> list[str]:
    """Return stable sorted overlap between two term collections."""
    left_set = {singularize_token(str(value).lower()) for value in left if str(value).strip()}
    right_set = {singularize_token(str(value).lower()) for value in right if str(value).strip()}
    return sorted(left_set.intersection(right_set))


__all__ = [
    "expand_terms",
    "normalize_text",
    "overlap_terms",
    "singularize_token",
    "tokenize_text",
]
