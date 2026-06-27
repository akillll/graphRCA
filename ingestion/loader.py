"""Graph loading helpers for persisting canonical nodes and edges."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import dotenv_values

from ingestion.types import GraphEdge, GraphNode, IngestionResult, NodeLabel, provenance_to_dict

if TYPE_CHECKING:
    from neo4j import Driver


@dataclass(slots=True)
class IngestStats:
    """Summary stats returned after persisting canonical graph payloads."""

    nodes_created_or_seen: int = 0
    edges_created_or_seen: int = 0


class Neo4jLoader:
    """Persist canonical graph payloads into Neo4j with idempotent upserts."""

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str,
        driver: "Driver | None" = None,
    ) -> None:
        """Initialize a loader from explicit Neo4j connection settings."""
        self._database = database
        self._driver = driver or self._create_driver(uri=uri, username=username, password=password)

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "Neo4jLoader":
        """Build a loader from .env-backed Neo4j settings."""
        env_values = _load_env_file(env_path)
        uri = env_values.get("NEO4J_URI") or os.environ.get("NEO4J_URI")
        username = (
            env_values.get("NEO4J_USERNAME")
            or env_values.get("NEO4J_USER")
            or os.environ.get("NEO4J_USERNAME")
            or os.environ.get("NEO4J_USER")
        )
        password = env_values.get("NEO4J_PASSWORD") or os.environ.get("NEO4J_PASSWORD")
        database = env_values.get("NEO4J_DATABASE") or os.environ.get("NEO4J_DATABASE")

        missing = [
            name
            for name, value in (
                ("NEO4J_URI", uri),
                ("NEO4J_USERNAME", username),
                ("NEO4J_PASSWORD", password),
                ("NEO4J_DATABASE", database),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"Missing Neo4j settings in environment or .env: {', '.join(missing)}")

        return cls(uri=str(uri), username=str(username), password=str(password), database=str(database))

    def close(self) -> None:
        """Close the underlying Neo4j driver."""
        self._driver.close()

    def __enter__(self) -> "Neo4jLoader":
        """Support context-manager usage."""
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the driver when leaving a context-manager block."""
        self.close()

    def ensure_constraints(self) -> None:
        """Create uniqueness constraints for canonical node IDs."""
        with self._driver.session(database=self._database) as session:
            for label in _allowed_labels():
                session.run(
                    f"CREATE CONSTRAINT {label.lower()}_id_unique IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.id IS UNIQUE"
                )

    def load(self, payload: GraphNode | GraphEdge | IngestionResult) -> IngestStats:
        """Persist one canonical node, edge, or whole ingestion result."""
        if isinstance(payload, GraphNode):
            result = IngestionResult(nodes=[payload])
        elif isinstance(payload, GraphEdge):
            result = IngestionResult(edges=[payload])
        elif isinstance(payload, IngestionResult):
            result = payload
        else:
            raise TypeError("Neo4jLoader.load accepts only GraphNode, GraphEdge, or IngestionResult.")

        self.ensure_constraints()
        with self._driver.session(database=self._database) as session:
            for node in result.nodes:
                session.execute_write(self._upsert_node, node)
            for edge in result.edges:
                session.execute_write(self._upsert_edge, edge)

        return IngestStats(
            nodes_created_or_seen=len(result.nodes),
            edges_created_or_seen=len(result.edges),
        )

    @staticmethod
    def _create_driver(*, uri: str, username: str, password: str) -> "Driver":
        """Create a Neo4j driver lazily so the module imports without the package installed."""
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise ImportError(
                "The neo4j package is required to use Neo4jLoader. Install it in the project environment."
            ) from exc

        return GraphDatabase.driver(uri, auth=(username, password))

    @staticmethod
    def _upsert_node(tx: Any, node: GraphNode) -> None:
        """Upsert one canonical node by deterministic ID."""
        tx.run(
            f"MERGE (n:{node.label} {{id: $node_id}}) "
            "SET n += $properties",
            node_id=node.id,
            properties=_node_properties(node),
        )

    @staticmethod
    def _upsert_edge(tx: Any, edge: GraphEdge) -> None:
        """Upsert one canonical edge by source node, relationship type, and target node."""
        tx.run(
            f"MATCH (source {{id: $source_id}}) "
            f"MATCH (target {{id: $target_id}}) "
            f"MERGE (source)-[r:{edge.edge_type}]->(target) "
            "SET r += $properties",
            source_id=edge.source_id,
            target_id=edge.target_id,
            properties=_edge_properties(edge),
        )


def _node_properties(node: GraphNode) -> dict[str, Any]:
    """Flatten canonical node properties and provenance into one Neo4j property map."""
    return {
        **dict(node.properties),
        **provenance_to_dict(node.provenance),
    }


def _edge_properties(edge: GraphEdge) -> dict[str, Any]:
    """Flatten canonical edge properties and provenance into one Neo4j property map."""
    return {
        **dict(edge.properties),
        **provenance_to_dict(edge.provenance),
    }


def _allowed_labels() -> tuple[NodeLabel, ...]:
    """Return the canonical node labels requiring ID constraints."""
    return (
        "Incident",
        "Service",
        "Deployment",
        "Commit",
        "Metric",
        "MetricSeries",
        "LogEvent",
        "TimelineEvent",
        "Runbook",
        "Action",
        "Hypothesis",
        "Configuration",
        "LogPattern",
    )


def _load_env_file(env_path: str | Path) -> dict[str, str]:
    """Load .env values with python-dotenv when the file is present."""
    path = Path(env_path)
    if not path.exists():
        return {}
    return {key: value for key, value in dotenv_values(path).items() if value is not None}
