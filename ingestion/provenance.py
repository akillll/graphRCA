"""Utilities for attaching deterministic or LLM provenance to graph payloads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CreatedBy = Literal["rule", "llm"]


@dataclass(frozen=True, slots=True)
class Provenance:
    """Provenance metadata attached to every node and edge payload."""

    source: str
    created_by: CreatedBy
    deterministic: bool
    model: str | None = None
    confidence: float | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        """Validate the provenance payload shape."""
        if not self.source:
            raise ValueError("Provenance source is required.")

        if self.created_by == "rule":
            if not self.deterministic:
                raise ValueError("Rule-created provenance must be deterministic.")
            if self.model is not None or self.confidence is not None or self.rationale is not None:
                raise ValueError("Rule provenance cannot carry LLM-only fields.")
            return

        if self.created_by == "llm":
            if self.model is None:
                raise ValueError("LLM provenance requires a model identifier.")
            if self.confidence is None:
                raise ValueError("LLM provenance requires a confidence value.")
            if not 0.0 <= self.confidence <= 1.0:
                raise ValueError("LLM provenance confidence must be between 0.0 and 1.0.")
            if self.rationale is None:
                raise ValueError("LLM provenance requires a rationale.")
            return

        raise ValueError(f"Unsupported provenance created_by value: {self.created_by}")


def rule_provenance(source: str) -> Provenance:
    """Create deterministic rule-based provenance metadata."""
    return Provenance(source=source, created_by="rule", deterministic=True)


def llm_provenance(
    source: str,
    *,
    model: str,
    confidence: float,
    rationale: str,
    deterministic: bool = False,
) -> Provenance:
    """Create provenance metadata for LLM-assisted extraction."""
    return Provenance(
        source=source,
        created_by="llm",
        deterministic=deterministic,
        model=model,
        confidence=confidence,
        rationale=rationale,
    )
