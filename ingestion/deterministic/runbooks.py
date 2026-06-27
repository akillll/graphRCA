"""Parse runbook markdown into Runbook and Action payloads."""

from __future__ import annotations

import re
from pathlib import Path

from ingestion.common.ids import action_id, runbook_id
from ingestion.provenance import rule_provenance
from ingestion.types import GraphEdge, GraphNode, IngestionResult


_BULLET_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.*\S)\s*$")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.*\S)\s*$")


def parse_runbooks(runbooks_path: str | Path) -> IngestionResult:
    """Parse one runbook file or a directory of markdown runbooks into canonical payloads."""
    path = Path(runbooks_path)
    result = IngestionResult()

    for runbook_file in _iter_runbook_files(path):
        result.extend(_parse_runbook_file(runbook_file))

    return result


def _iter_runbook_files(path: Path) -> list[Path]:
    """Return sorted markdown runbook files from a directory or single file input."""
    if not path.exists():
        return []
    if path.is_file():
        _validate_runbook_file(path)
        return [path]
    return sorted(file_path for file_path in path.glob("*.md") if file_path.is_file())


def _parse_runbook_file(path: Path) -> IngestionResult:
    """Parse one markdown runbook file."""
    _validate_runbook_file(path)

    content = path.read_text()
    provenance = rule_provenance(str(path))
    runbook_node_id = runbook_id(path.name)
    result = IngestionResult()

    runbook_node = GraphNode(
        label="Runbook",
        properties={
            "id": runbook_node_id,
            "filename": path.name,
            "title": _extract_title(content, path),
            "content": content,
        },
        provenance=provenance,
    )
    result.nodes.append(runbook_node)

    for action_text in _extract_recommended_actions(content):
        action_node = GraphNode(
            label="Action",
            properties={
                "id": action_id(runbook_node_id, action_text),
                "text": action_text,
                "kind": "recommended",
                "runbook_id": runbook_node_id,
            },
            provenance=provenance,
        )
        result.nodes.append(action_node)
        result.edges.append(
            GraphEdge(
                edge_type="RECOMMENDS",
                source_id=runbook_node_id,
                target_id=action_node.id,
                provenance=provenance,
            )
        )

    return result


def _validate_runbook_file(path: Path) -> None:
    """Reject evaluation inputs and non-markdown files."""
    if path.name == "expected_rca.json":
        raise ValueError("expected_rca.json is evaluation-only and must not be parsed as a runbook.")
    if path.suffix.lower() != ".md":
        raise ValueError(f"Expected a markdown runbook file, got {path.name!r}.")


def _extract_title(content: str, path: Path) -> str:
    """Extract the runbook title from the first markdown heading or fallback to filename."""
    for line in content.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            return match.group(1).strip()
    return path.stem.replace("_", " ").strip().title()


def _extract_recommended_actions(content: str) -> list[str]:
    """Extract bullet or numbered items from the Recommended Actions section when present."""
    lines = content.splitlines()
    actions: list[str] = []
    in_section = False

    for line in lines:
        normalized = line.strip()
        if normalized.startswith("## "):
            heading = normalized[3:].strip().lower()
            if heading == "recommended actions":
                in_section = True
                continue
            if in_section:
                break

        if not in_section:
            continue

        bullet_match = _BULLET_RE.match(line)
        if bullet_match:
            actions.append(bullet_match.group(1).strip())
            continue

        if in_section and normalized.startswith("#"):
            break

    return actions
