"""Entry points and orchestration for end-to-end ingestion runs."""

from __future__ import annotations

from ingestion.normalization import normalize_result, normalize_results
from ingestion.types import IngestionResult


def combine_parser_results(*results: IngestionResult) -> IngestionResult:
    """Merge parser outputs and return one normalized ingestion payload."""
    return normalize_results(*results)


def finalize_ingestion_result(result: IngestionResult) -> IngestionResult:
    """Normalize one accumulated ingestion result before validation or graph writes."""
    return normalize_result(result)
