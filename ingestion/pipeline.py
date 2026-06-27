"""Entry points and orchestration for end-to-end ingestion runs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ingestion.deterministic.commits import parse_commits
from ingestion.deterministic.deployments import parse_deployments
from ingestion.deterministic.logs import parse_logs
from ingestion.deterministic.metadata import parse_metadata
from ingestion.deterministic.metrics import parse_metrics
from ingestion.deterministic.runbooks import parse_runbooks
from ingestion.deterministic.services import parse_services
from ingestion.deterministic.timeline import parse_timeline
from ingestion.loader import IngestStats, Neo4jLoader
from ingestion.normalization import normalize_result, normalize_results
from ingestion.types import GraphNode, IngestionResult
from ingestion.validation import (
    ValidationReport,
    validate_deployment_commit_ids,
    validate_metadata_runbooks,
    validate_result,
    validate_runtime_input_paths,
    validate_services_topology,
)


@dataclass(slots=True)
class IncidentIngestSummary:
    """Per-incident ingest summary for deterministic pipeline runs."""

    incident_id: str
    nodes_created_or_seen: int
    edges_created_or_seen: int
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PreparedIncidentPayload:
    """Prepared deterministic incident payload before graph writes."""

    incident_id: str
    normalized_result: IngestionResult
    load_result: IngestionResult
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PipelineSummary:
    """Overall ingest summary for a dataset-wide pipeline run."""

    dataset_path: str
    deterministic_only: bool = True
    llm_enrichment_enabled: bool = False
    runbook_nodes_created_or_seen: int = 0
    runbook_edges_created_or_seen: int = 0
    incidents_processed: int = 0
    incident_summaries: list[IncidentIngestSummary] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_nodes_created_or_seen(self) -> int:
        """Return total node upserts across runbooks and incidents."""
        return self.runbook_nodes_created_or_seen + sum(
            item.nodes_created_or_seen for item in self.incident_summaries
        )

    @property
    def total_edges_created_or_seen(self) -> int:
        """Return total edge upserts across runbooks and incidents."""
        return self.runbook_edges_created_or_seen + sum(
            item.edges_created_or_seen for item in self.incident_summaries
        )


def combine_parser_results(*results: IngestionResult) -> IngestionResult:
    """Merge parser outputs and return one normalized ingestion payload."""
    return normalize_results(*results)


def finalize_ingestion_result(result: IngestionResult) -> IngestionResult:
    """Normalize one accumulated ingestion result before validation or graph writes."""
    return normalize_result(result)


def discover_incident_directories(dataset_path: str | Path = "data") -> list[Path]:
    """Discover incident directories under data/incidents by presence of metadata.json."""
    incidents_root = Path(dataset_path) / "incidents"
    if not incidents_root.exists():
        return []
    return sorted(path.parent for path in incidents_root.rglob("metadata.json") if path.name == "metadata.json")


def collect_runtime_input_paths(dataset_path: str | Path = "data") -> list[Path]:
    """Return all runtime ingestion inputs and exclude evaluation-only files."""
    dataset_root = Path(dataset_path)
    incident_dirs = discover_incident_directories(dataset_root)
    return _runtime_input_paths(dataset_root, incident_dirs)


def prepare_runbooks_payload(dataset_path: str | Path = "data") -> IngestionResult:
    """Parse, normalize, and validate reusable runbook payloads once."""
    dataset_root = Path(dataset_path)
    runbooks_result = finalize_ingestion_result(parse_runbooks(dataset_root / "runbooks"))
    runbook_validation = validate_result(runbooks_result)
    _raise_on_validation_errors(runbook_validation, "runbook validation failed")
    return runbooks_result


def prepare_incident_payload(
    *,
    incident_dir: str | Path,
    runbooks_dir: str | Path,
    shared_runtime_result: IngestionResult | None = None,
    shared_runtime_node_ids: set[str] | None = None,
) -> PreparedIncidentPayload:
    """Parse, normalize, and validate one deterministic incident payload without DB writes."""
    incident_path = Path(incident_dir)
    metadata_file = incident_path / "metadata.json"
    deployments_file = incident_path / "deployments.json"
    commits_file = incident_path / "commits.json"
    metrics_file = incident_path / "metrics.json"
    logs_file = incident_path / "logs.json"
    timeline_file = incident_path / "timeline.json"
    services_file = incident_path / "services.json"

    raw_metadata = json.loads(metadata_file.read_text())
    incident_node_id = f"incident:{raw_metadata['id']}"

    dataset_validation = ValidationReport()
    dataset_validation.extend(validate_metadata_runbooks(raw_metadata, runbooks_dir, location=str(metadata_file)))

    raw_deployments = json.loads(deployments_file.read_text())
    raw_commits = json.loads(commits_file.read_text())
    dataset_validation.extend(
        validate_deployment_commit_ids(raw_deployments, raw_commits, location=str(deployments_file))
    )

    if services_file.exists():
        raw_services = json.loads(services_file.read_text())
        dataset_validation.extend(validate_services_topology(raw_services, location=str(services_file)))

    _raise_on_validation_errors(dataset_validation, f"dataset validation failed for {incident_path.name}")

    parser_results = [
        parse_metadata(metadata_file),
        parse_deployments(
            deployments_file,
            incident_id=incident_node_id,
            incident_start_time=raw_metadata["start_time"],
            incident_end_time=raw_metadata["end_time"],
        ),
        parse_commits(commits_file, incident_id=incident_node_id),
        parse_metrics(
            metrics_file,
            incident_id=incident_node_id,
            start_time=raw_metadata["start_time"],
            end_time=raw_metadata["end_time"],
        ),
        parse_logs(logs_file, incident_id=incident_node_id),
        parse_timeline(timeline_file, incident_id=incident_node_id),
    ]
    if services_file.exists():
        parser_results.append(parse_services(services_file))

    normalized_result = combine_parser_results(
        *(parser_results + ([shared_runtime_result] if shared_runtime_result is not None else []))
    )
    validation_report = validate_result(normalized_result)
    _raise_on_validation_errors(validation_report, f"payload validation failed for {incident_path.name}")

    load_result = _filter_loadable_incident_result(
        normalized_result,
        shared_runtime_node_ids=shared_runtime_node_ids or set(),
    )
    return PreparedIncidentPayload(
        incident_id=incident_node_id,
        normalized_result=normalized_result,
        load_result=load_result,
        warnings=[
            *normalized_result.warnings,
            *[issue.message for issue in validation_report.warnings],
        ],
    )


def ingest_dataset(
    *,
    dataset_path: str | Path = "data",
    env_path: str | Path = ".env",
    deterministic_only: bool = True,
    enable_llm_enrichment: bool = False,
    loader: Neo4jLoader | None = None,
) -> PipelineSummary:
    """Run deterministic ingestion across the dataset and persist the normalized graph payloads."""
    if enable_llm_enrichment:
        raise ValueError("LLM enrichment is not implemented yet. Leave enable_llm_enrichment=False.")

    dataset_root = Path(dataset_path)
    incident_dirs = discover_incident_directories(dataset_root)
    runtime_path_report = validate_runtime_input_paths(_runtime_input_paths(dataset_root, incident_dirs))
    _raise_on_validation_errors(runtime_path_report, "runtime input validation failed")

    owns_loader = loader is None
    graph_loader = loader or Neo4jLoader.from_env(env_path)
    summary = PipelineSummary(
        dataset_path=str(dataset_root),
        deterministic_only=deterministic_only,
        llm_enrichment_enabled=enable_llm_enrichment,
    )

    try:
        runbooks_result = prepare_runbooks_payload(dataset_root)
        runbook_stats = graph_loader.load(runbooks_result)
        summary.runbook_nodes_created_or_seen = runbook_stats.nodes_created_or_seen
        summary.runbook_edges_created_or_seen = runbook_stats.edges_created_or_seen
        summary.warnings.extend(runbooks_result.warnings)

        shared_runbook_ids = {node.id for node in runbooks_result.nodes}

        for incident_dir in incident_dirs:
            incident_summary = ingest_incident_directory(
                incident_dir=incident_dir,
                runbooks_dir=dataset_root / "runbooks",
                loader=graph_loader,
                shared_runtime_result=runbooks_result,
                shared_runtime_node_ids=shared_runbook_ids,
            )
            summary.incident_summaries.append(incident_summary)
            summary.incidents_processed += 1
            summary.warnings.extend(incident_summary.warnings)

        return summary
    finally:
        if owns_loader:
            graph_loader.close()


def ingest_incident_directory(
    *,
    incident_dir: str | Path,
    runbooks_dir: str | Path,
    loader: Neo4jLoader,
    shared_runtime_result: IngestionResult | None = None,
    shared_runtime_node_ids: set[str] | None = None,
) -> IncidentIngestSummary:
    """Parse, normalize, validate, and load one incident directory deterministically."""
    prepared = prepare_incident_payload(
        incident_dir=incident_dir,
        runbooks_dir=runbooks_dir,
        shared_runtime_result=shared_runtime_result,
        shared_runtime_node_ids=shared_runtime_node_ids,
    )
    load_stats = loader.load(prepared.load_result)

    return IncidentIngestSummary(
        incident_id=prepared.incident_id,
        nodes_created_or_seen=load_stats.nodes_created_or_seen,
        edges_created_or_seen=load_stats.edges_created_or_seen,
        warnings=list(prepared.warnings),
    )


def print_pipeline_summary(summary: PipelineSummary) -> None:
    """Print a compact human-readable ingest summary."""
    print(
        "Runbooks:"
        f" nodes={summary.runbook_nodes_created_or_seen}"
        f" edges={summary.runbook_edges_created_or_seen}"
    )
    for item in summary.incident_summaries:
        print(
            f"{item.incident_id}:"
            f" nodes={item.nodes_created_or_seen}"
            f" edges={item.edges_created_or_seen}"
        )
    print(
        "Total:"
        f" incidents={summary.incidents_processed}"
        f" nodes={summary.total_nodes_created_or_seen}"
        f" edges={summary.total_edges_created_or_seen}"
    )


def _runtime_input_paths(dataset_root: Path, incident_dirs: list[Path]) -> list[Path]:
    """Return runtime input paths used by the deterministic pipeline."""
    paths: list[Path] = [dataset_root / "runbooks"]
    for incident_dir in incident_dirs:
        for name in (
            "metadata.json",
            "deployments.json",
            "commits.json",
            "metrics.json",
            "logs.json",
            "timeline.json",
            "services.json",
        ):
            candidate = incident_dir / name
            if candidate.exists():
                paths.append(candidate)
    return paths


def _filter_loadable_incident_result(
    result: IngestionResult,
    *,
    shared_runtime_node_ids: set[str],
) -> IngestionResult:
    """Drop shared-only nodes while keeping edges that target already-loaded shared nodes."""
    filtered = IngestionResult(warnings=list(result.warnings))
    filtered.nodes = [node for node in result.nodes if node.id not in shared_runtime_node_ids]
    filtered_node_ids = {node.id for node in filtered.nodes}

    for edge in result.edges:
        source_ok = edge.source_id in filtered_node_ids or edge.source_id in shared_runtime_node_ids
        target_ok = edge.target_id in filtered_node_ids or edge.target_id in shared_runtime_node_ids
        if not (source_ok and target_ok):
            continue
        if edge.source_id in shared_runtime_node_ids and edge.target_id in shared_runtime_node_ids:
            continue
        filtered.edges.append(edge)

    return filtered


def _raise_on_validation_errors(report: ValidationReport, message: str) -> None:
    """Raise one combined error when validation fails."""
    if report.is_valid:
        return
    details = "; ".join(f"{issue.location}: {issue.message}" for issue in report.errors)
    raise ValueError(f"{message}: {details}")
