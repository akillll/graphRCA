"""Read-only Neo4j access helpers for retrieval queries."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from dotenv import dotenv_values

if TYPE_CHECKING:
    from neo4j import Driver


class Neo4jReadClient:
    """Minimal read-only Neo4j wrapper for retrieval queries."""

    def __init__(
        self,
        *,
        uri: str,
        username: str,
        password: str,
        database: str,
        driver: "Driver | None" = None,
    ) -> None:
        """Initialize the client from explicit Neo4j connection settings."""
        self._uri = uri
        self._username = username
        self._password = password
        self._database = database
        self._driver = driver

    @classmethod
    def from_env(cls, env_path: str | Path = ".env") -> "Neo4jReadClient":
        """Build a read client from `.env` values and process environment variables."""
        path = Path(env_path)
        env_values = {key: value for key, value in dotenv_values(path).items() if value is not None} if path.exists() else {}
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

    def connect(self) -> "Neo4jReadClient":
        """Create the underlying Neo4j driver lazily and verify connectivity."""
        if self._driver is None:
            self._driver = self._create_driver(
                uri=self._uri,
                username=self._username,
                password=self._password,
            )
            self._driver.verify_connectivity()
        return self

    def close(self) -> None:
        """Close the underlying Neo4j driver if it has been opened."""
        if self._driver is not None:
            self._driver.close()
            self._driver = None

    def run_query(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Execute a read query and return plain Python dictionaries."""
        driver = self.connect()._driver
        assert driver is not None

        with driver.session(database=self._database) as session:
            return session.execute_read(self._run_read_query, query, params or {})

    def __enter__(self) -> "Neo4jReadClient":
        """Support context-manager usage."""
        return self.connect()

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        """Close the driver when leaving a context-manager block."""
        self.close()

    @staticmethod
    def _create_driver(*, uri: str, username: str, password: str) -> "Driver":
        """Create a Neo4j driver lazily so the module imports without the package installed."""
        try:
            from neo4j import GraphDatabase
        except ImportError as exc:
            raise ImportError(
                "The neo4j package is required to use Neo4jReadClient. Install it in the project environment."
            ) from exc

        return GraphDatabase.driver(uri, auth=(username, password))

    @staticmethod
    def _run_read_query(tx: Any, query: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        """Execute one query inside a read transaction and normalize records to dictionaries."""
        result = tx.run(query, params)
        return [dict(record.data()) for record in result]
