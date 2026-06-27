"""CLI smoke checks for deterministic ingestion."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ingestion.loader import GraphCounts, Neo4jLoader
from ingestion.pipeline import (
    collect_runtime_input_paths,
    discover_incident_directories,
    ingest_dataset,
    prepare_incident_payload,
    prepare_runbooks_payload,
)
from ingestion.validation import validate_runtime_input_paths


DEFAULT_EASY_INCIDENT = "easy/cache_warmup_regression"


def main(argv: list[str] | None = None) -> int:
    """Run deterministic ingestion smoke commands."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "parse-one":
            _cmd_parse_one(args)
        elif args.command == "parse-all":
            _cmd_parse_all(args)
        elif args.command == "load-all":
            _cmd_load_all(args)
        elif args.command == "check-idempotency":
            _cmd_check_idempotency(args)
        else:
            parser.error(f"Unknown command: {args.command}")
    except Exception as exc:
        print(f"FAIL: {exc}")
        return 1

    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the deterministic ingestion smoke-test CLI."""
    parser = argparse.ArgumentParser(description="Deterministic ingestion smoke checks")
    subparsers = parser.add_subparsers(dest="command", required=True)

    parse_one = subparsers.add_parser("parse-one", help="Parse one easy incident without Neo4j")
    parse_one.add_argument("--dataset-path", default="data")
    parse_one.add_argument("--incident", default=DEFAULT_EASY_INCIDENT)

    parse_all = subparsers.add_parser("parse-all", help="Parse all incidents without Neo4j")
    parse_all.add_argument("--dataset-path", default="data")

    load_all = subparsers.add_parser("load-all", help="Load all deterministic payloads into Neo4j")
    load_all.add_argument("--dataset-path", default="data")
    load_all.add_argument("--env-path", default=".env")

    idem = subparsers.add_parser("check-idempotency", help="Run load-all twice and compare graph counts")
    idem.add_argument("--dataset-path", default="data")
    idem.add_argument("--env-path", default=".env")

    return parser


def _cmd_parse_one(args: argparse.Namespace) -> None:
    """Parse one easy incident without Neo4j and print pass/fail summary."""
    dataset_root = Path(args.dataset_path)
    incident_dir = dataset_root / "incidents" / args.incident
    runbooks_result = prepare_runbooks_payload(dataset_root)
    prepared = prepare_incident_payload(
        incident_dir=incident_dir,
        runbooks_dir=dataset_root / "runbooks",
        shared_runtime_result=runbooks_result,
        shared_runtime_node_ids={node.id for node in runbooks_result.nodes},
    )

    _print_runtime_input_check(dataset_root)
    print(f"PASS: parsed one incident {prepared.incident_id}")
    print(
        "RESULT:"
        f" nodes={len(prepared.load_result.nodes)}"
        f" edges={len(prepared.load_result.edges)}"
        f" warnings={len(prepared.warnings)}"
    )


def _cmd_parse_all(args: argparse.Namespace) -> None:
    """Parse all incidents without Neo4j and print pass/fail summary."""
    dataset_root = Path(args.dataset_path)
    incident_dirs = discover_incident_directories(dataset_root)
    runbooks_result = prepare_runbooks_payload(dataset_root)
    shared_runbook_ids = {node.id for node in runbooks_result.nodes}
    total_nodes = len(runbooks_result.nodes)
    total_edges = len(runbooks_result.edges)
    total_warnings = len(runbooks_result.warnings)

    _print_runtime_input_check(dataset_root)

    for incident_dir in incident_dirs:
        prepared = prepare_incident_payload(
            incident_dir=incident_dir,
            runbooks_dir=dataset_root / "runbooks",
            shared_runtime_result=runbooks_result,
            shared_runtime_node_ids=shared_runbook_ids,
        )
        total_nodes += len(prepared.load_result.nodes)
        total_edges += len(prepared.load_result.edges)
        total_warnings += len(prepared.warnings)
        print(
            f"PASS: {prepared.incident_id}"
            f" nodes={len(prepared.load_result.nodes)}"
            f" edges={len(prepared.load_result.edges)}"
            f" warnings={len(prepared.warnings)}"
        )

    print(
        "PASS: parsed all deterministic incidents"
        f" incidents={len(incident_dirs)}"
        f" total_nodes={total_nodes}"
        f" total_edges={total_edges}"
        f" total_warnings={total_warnings}"
    )


def _cmd_load_all(args: argparse.Namespace) -> None:
    """Load all deterministic payloads into Neo4j and print summary."""
    summary = ingest_dataset(dataset_path=args.dataset_path, env_path=args.env_path)
    _print_runtime_input_check(Path(args.dataset_path))
    print(
        "PASS: loaded deterministic dataset into Neo4j"
        f" incidents={summary.incidents_processed}"
        f" total_nodes={summary.total_nodes_created_or_seen}"
        f" total_edges={summary.total_edges_created_or_seen}"
        f" warnings={len(summary.warnings)}"
    )


def _cmd_check_idempotency(args: argparse.Namespace) -> None:
    """Load the dataset twice and assert node and edge counts do not increase."""
    dataset_root = Path(args.dataset_path)
    _print_runtime_input_check(dataset_root)

    with Neo4jLoader.from_env(args.env_path) as loader:
        first_summary = ingest_dataset(dataset_path=dataset_root, env_path=args.env_path, loader=loader)
        first_counts = loader.graph_counts()
        second_summary = ingest_dataset(dataset_path=dataset_root, env_path=args.env_path, loader=loader)
        second_counts = loader.graph_counts()

    _assert_counts_stable(first_counts, second_counts)
    print(
        "PASS: rerun idempotency check"
        f" first_nodes={first_counts.node_count}"
        f" first_edges={first_counts.edge_count}"
        f" second_nodes={second_counts.node_count}"
        f" second_edges={second_counts.edge_count}"
        f" first_seen_nodes={first_summary.total_nodes_created_or_seen}"
        f" second_seen_nodes={second_summary.total_nodes_created_or_seen}"
    )


def _print_runtime_input_check(dataset_root: Path) -> None:
    """Print pass/fail for expected_rca exclusion from runtime ingestion."""
    report = validate_runtime_input_paths(collect_runtime_input_paths(dataset_root))
    if not report.is_valid:
        details = "; ".join(issue.message for issue in report.errors)
        raise ValueError(f"expected_rca exclusion check failed: {details}")
    print("PASS: expected_rca.json excluded from runtime ingestion inputs")


def _assert_counts_stable(first: GraphCounts, second: GraphCounts) -> None:
    """Assert that rerunning deterministic ingestion does not increase graph counts."""
    if second.node_count != first.node_count or second.edge_count != first.edge_count:
        raise ValueError(
            "Rerun increased graph counts: "
            f"first=({first.node_count} nodes, {first.edge_count} edges) "
            f"second=({second.node_count} nodes, {second.edge_count} edges)"
        )


if __name__ == "__main__":
    sys.exit(main())
