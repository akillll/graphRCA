"""Smoke-check CLI for question resolution, traversal, and evidence assembly."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from retrieval.assembly import EvidenceAssembler
from retrieval.entity_extractor import EntityExtractor
from retrieval.resolution import IncidentResolver
from retrieval.traversal import IncidentTraversal


DEFAULT_DATA_DIR = Path("data/incidents")
DEFAULT_ENV_PATH = ".env"
DEFAULT_EXAMPLE_QUESTION = "Why did catalog-api latency spike on April 21?"


def main(argv: list[str] | None = None) -> int:
    """Run the retrieval smoke-check CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    known_services, known_incident_ids = _load_known_entities(Path(args.data_dir))
    extractor = EntityExtractor(
        known_services=known_services,
        known_incident_ids=known_incident_ids,
    )

    if args.command == "resolve-question":
        resolver = IncidentResolver.from_env(args.env_path, data_dir=Path(args.data_dir))
        return _resolve_question(args.question, extractor, resolver)

    if args.command == "traverse-incident":
        traversal = IncidentTraversal.from_env(args.env_path)
        return _traverse_incident(args.incident_id, traversal)

    if args.command == "bundle-question":
        resolver = IncidentResolver.from_env(args.env_path, data_dir=Path(args.data_dir))
        traversal = IncidentTraversal.from_env(args.env_path)
        assembler = EvidenceAssembler()
        return _bundle_question(args.question, extractor, resolver, traversal, assembler, output_json=args.json)

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(description="Retrieval smoke-check CLI for GraphRCA.")
    parser.add_argument(
        "--env-path",
        default=DEFAULT_ENV_PATH,
        help=f"Path to .env file containing Neo4j settings. Default: {DEFAULT_ENV_PATH}",
    )
    parser.add_argument(
        "--data-dir",
        default=str(DEFAULT_DATA_DIR),
        help=f"Path to local incident fixtures for known entity extraction. Default: {DEFAULT_DATA_DIR}",
    )

    subparsers = parser.add_subparsers(dest="command")

    resolve_parser = subparsers.add_parser(
        "resolve-question",
        help="Extract entities from a question and return ranked incident candidates.",
        description="Example: retrieval/cli.py resolve-question "
        f"\"{DEFAULT_EXAMPLE_QUESTION}\"",
    )
    resolve_parser.add_argument("question", help="Natural-language question to resolve.")

    traverse_parser = subparsers.add_parser(
        "traverse-incident",
        help="Traverse a selected incident and print a traversal summary.",
    )
    traverse_parser.add_argument("incident_id", help="Raw or canonical incident ID to traverse.")

    bundle_parser = subparsers.add_parser(
        "bundle-question",
        help="Resolve a question, traverse the top incident, and print the evidence bundle.",
        description="Example: retrieval/cli.py bundle-question "
        f"\"{DEFAULT_EXAMPLE_QUESTION}\"",
    )
    bundle_parser.add_argument("question", help="Natural-language question to bundle.")
    bundle_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the final EvidenceBundle as JSON instead of a readable summary.",
    )

    return parser


def _resolve_question(question: str, extractor: EntityExtractor, resolver: IncidentResolver) -> int:
    """Extract entities and print ranked incident candidates for one question."""
    entities = extractor.extract(question)
    candidates = resolver.resolve(entities)

    print("Entities")
    print(json.dumps(asdict(entities), indent=2))
    print()
    print("Incident Candidates")
    if not candidates:
        print("No candidate incidents found.")
        return 0

    for index, candidate in enumerate(candidates, start=1):
        print(f"{index}. {candidate.incident_id} score={candidate.score:.3f}")
        for reason in candidate.reasons:
            print(f"   - {reason}")
    return 0


def _traverse_incident(incident_id: str, traversal: IncidentTraversal) -> int:
    """Traverse one incident and print a compact summary."""
    result = traversal.traverse(incident_id)

    print(f"Incident: {result.incident_id}")
    print(f"Nodes: {len(result.nodes)}")
    print(f"Edges: {len(result.edges)}")
    print(f"Hypotheses: {len(result.hypotheses)}")
    print(f"Runbooks: {len(result.runbooks)}")

    label_counts = _node_label_counts(result.nodes)
    if label_counts:
        print("Node Categories")
        for label in sorted(label_counts):
            print(f"  {label}: {label_counts[label]}")

    if result.warnings:
        print("Warnings")
        for warning in result.warnings:
            print(f"  - {warning}")
    return 0


def _bundle_question(
    question: str,
    extractor: EntityExtractor,
    resolver: IncidentResolver,
    traversal: IncidentTraversal,
    assembler: EvidenceAssembler,
    *,
    output_json: bool,
) -> int:
    """Resolve a question, traverse the top incident, and print the evidence bundle."""
    entities = extractor.extract(question)
    candidates = resolver.resolve(entities)
    if not candidates:
        print("No incident candidates found.")
        print(json.dumps(asdict(entities), indent=2))
        return 1

    top_candidate = candidates[0]
    traversal_result = traversal.traverse(top_candidate.incident_id)
    bundle = assembler.assemble(traversal_result)

    if output_json:
        print(json.dumps(asdict(bundle), indent=2))
        return 0

    print(f"Question: {question}")
    print(f"Top Incident: {top_candidate.incident_id} score={top_candidate.score:.3f}")
    print("Reasons")
    for reason in top_candidate.reasons:
        print(f"  - {reason}")
    print("Evidence Summary")
    print(f"  Incident: {bundle.incident.get('node_id') if bundle.incident else 'missing'}")
    print(f"  Deployments: {len(bundle.deployments)}")
    print(f"  Commits: {len(bundle.commits)}")
    print(f"  Metrics: {len(bundle.metrics)}")
    print(f"  Logs: {len(bundle.logs)}")
    print(f"  Timeline: {len(bundle.timeline)}")
    print(f"  Services: {len(bundle.services)}")
    print(f"  Configurations: {len(bundle.configurations)}")
    print(f"  Hypotheses: {len(bundle.hypotheses)}")
    print(f"  Runbooks: {len(bundle.runbooks)}")
    print(f"  Citations: {len(bundle.citations)}")

    if traversal_result.warnings:
        print("Warnings")
        for warning in traversal_result.warnings:
            print(f"  - {warning}")
    return 0


def _load_known_entities(data_dir: Path) -> tuple[list[str], list[str]]:
    """Load known service names and incident IDs from local fixture files."""
    service_names: set[str] = set()
    incident_ids: list[str] = []

    for metadata_path in sorted(data_dir.glob("*/*/metadata.json")):
        payload = json.loads(metadata_path.read_text())
        incident_id = payload.get("id")
        if isinstance(incident_id, str) and incident_id.strip():
            incident_ids.append(incident_id.strip())

        primary_service = payload.get("service")
        if isinstance(primary_service, str) and primary_service.strip():
            service_names.add(primary_service.strip())

        for service_name in payload.get("affected_services", []):
            if isinstance(service_name, str) and service_name.strip():
                service_names.add(service_name.strip())

    for services_path in sorted(data_dir.glob("*/*/services.json")):
        payload = json.loads(services_path.read_text())
        for service in payload.get("services", []):
            name = service.get("name")
            if isinstance(name, str) and name.strip():
                service_names.add(name.strip())
            for alias in service.get("aliases", []):
                if isinstance(alias, str) and alias.strip():
                    service_names.add(alias.strip())

    return sorted(service_names), _dedupe_preserve_order(incident_ids)


def _node_label_counts(nodes: list[dict[str, Any]]) -> dict[str, int]:
    """Count nodes by primary label for traversal summary output."""
    counts: dict[str, int] = {}
    for node in nodes:
        labels = node.get("node_labels", [])
        label = labels[0] if labels else "Unknown"
        counts[label] = counts.get(label, 0) + 1
    return counts


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return stable unique values preserving encounter order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


if __name__ == "__main__":
    raise SystemExit(main())
