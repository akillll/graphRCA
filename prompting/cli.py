"""Smoke-check CLI for prompt construction and grounded RCA draft generation."""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from prompting.context_builder import PromptContextBuilder
from prompting.generator import PromptGenerationError, PromptGenerator
from prompting.templates import render_system_prompt, render_user_prompt
from retrieval.assembly import EvidenceAssembler
from retrieval.entity_extractor import EntityExtractor
from retrieval.resolution import IncidentResolver
from retrieval.traversal import IncidentTraversal
from retrieval.types import EvidenceBundle


DEFAULT_DATA_DIR = Path("data/incidents")
DEFAULT_ENV_PATH = ".env"
DEFAULT_EXAMPLE_QUESTION = "Why did checkout-api latency spike after the rollout on May 14?"


def main(argv: list[str] | None = None) -> int:
    """Run the prompting smoke-check CLI."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return 1

    try:
        if args.command == "build-context":
            return _build_context_command(args)
        if args.command == "render-prompt":
            return _render_prompt_command(args)
        if args.command == "generate-draft":
            return _generate_draft_command(args)
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        _print_error(str(exc) or exc.__class__.__name__)
        return 1

    parser.print_help()
    return 1


def _build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI argument parser."""
    parser = argparse.ArgumentParser(description="Prompting smoke-check CLI for GraphRCA.")
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

    build_context_parser = subparsers.add_parser(
        "build-context",
        help="Resolve a question, retrieve evidence, and print PromptContext as JSON.",
        description=f"Example: prompting/cli.py build-context \"{DEFAULT_EXAMPLE_QUESTION}\"",
    )
    build_context_parser.add_argument("question", help="Natural-language investigation question.")

    render_prompt_parser = subparsers.add_parser(
        "render-prompt",
        help="Resolve a question, build prompts, and print the final system and user prompts.",
        description=f"Example: prompting/cli.py render-prompt \"{DEFAULT_EXAMPLE_QUESTION}\"",
    )
    render_prompt_parser.add_argument("question", help="Natural-language investigation question.")

    generate_draft_parser = subparsers.add_parser(
        "generate-draft",
        help="Run the complete prompting pipeline and print the parsed RCA draft as JSON.",
        description=f"Example: prompting/cli.py generate-draft \"{DEFAULT_EXAMPLE_QUESTION}\"",
    )
    generate_draft_parser.add_argument("question", help="Natural-language investigation question.")

    return parser


def _build_context_command(args: argparse.Namespace) -> int:
    """Run retrieval plus context building and print serialized `PromptContext`."""
    bundle = _retrieve_evidence_bundle(args.question, env_path=args.env_path, data_dir=Path(args.data_dir))
    context_builder = PromptContextBuilder()
    context = context_builder.build(bundle, args.question)
    print(context.model_dump_json(indent=2))
    return 0


def _render_prompt_command(args: argparse.Namespace) -> int:
    """Run retrieval plus prompt rendering and print the final prompt strings."""
    bundle = _retrieve_evidence_bundle(args.question, env_path=args.env_path, data_dir=Path(args.data_dir))
    context_builder = PromptContextBuilder()
    context = context_builder.build(bundle, args.question)

    system_prompt = render_system_prompt()
    user_prompt = render_user_prompt(context, question=args.question)

    print("=== System Prompt ===")
    print(system_prompt)
    print()
    print("=== User Prompt ===")
    print(user_prompt)
    return 0


def _generate_draft_command(args: argparse.Namespace) -> int:
    """Run the full prompting pipeline and print the parsed `RcaDraft` as JSON."""
    bundle = _retrieve_evidence_bundle(args.question, env_path=args.env_path, data_dir=Path(args.data_dir))
    generator = PromptGenerator()
    try:
        draft = generator.generate(args.question, bundle)
    except PromptGenerationError as exc:
        _print_error(str(exc))
        return 1

    print(draft.model_dump_json(indent=2))
    return 0


def _retrieve_evidence_bundle(question: str, *, env_path: str, data_dir: Path) -> EvidenceBundle:
    """Resolve a question into a compact evidence bundle for prompting."""
    known_services, known_incident_ids = _load_known_entities(data_dir)
    extractor = EntityExtractor(
        known_services=known_services,
        known_incident_ids=known_incident_ids,
    )
    resolver = IncidentResolver.from_env(env_path)
    traversal = IncidentTraversal.from_env(env_path)
    assembler = EvidenceAssembler()

    entities = extractor.extract(question)
    candidates = resolver.resolve(entities)
    if not candidates:
        extracted_entities = json.dumps(asdict(entities), indent=2)
        raise ValueError(
            "No incident candidates found for the supplied question.\n"
            f"Extracted entities:\n{extracted_entities}"
        )

    top_candidate = candidates[0]
    traversal_result = traversal.traverse(top_candidate.incident_id)
    return assembler.assemble(traversal_result)


def _load_known_entities(data_dir: Path) -> tuple[list[str], list[str]]:
    """Load stable service names and incident IDs from local fixture files."""
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


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    """Return stable unique values while preserving original order."""
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _print_error(message: str) -> None:
    """Print a readable CLI error message to stderr."""
    print(f"Error: {message}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
