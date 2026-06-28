"""Route handlers for graph stats and incident subgraph inspection.

These endpoints are intended for debug and inspection use. They expose read-only
graph state and incident-centered traversal payloads without invoking prompting
or llama.cpp.
"""

from __future__ import annotations

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from api.config import get_settings
from api.errors import (
    ApiError,
    GraphUnavailableError,
    IncidentNotFoundError,
    UnexpectedApiError,
    to_error_response,
)
from api.types import ApiErrorResponse, GraphStatsResponse, IncidentGraphResponse
from retrieval.client import Neo4jReadClient
from retrieval.traversal import IncidentTraversal


router = APIRouter(tags=["graph"])


GRAPH_COUNTS_QUERY = """
CALL () {
  MATCH (n)
  RETURN count(n) AS node_count
}
CALL () {
  MATCH ()-[r]->()
  RETURN count(r) AS edge_count
}
CALL () {
  MATCH (incident:Incident)
  RETURN count(incident) AS incident_count
}
RETURN {
  node_count: node_count,
  edge_count: edge_count,
  incident_count: incident_count
} AS result
""".strip()

LABEL_COUNTS_QUERY = """
MATCH (n)
UNWIND labels(n) AS label
RETURN {
  label: label,
  count: count(*)
} AS result
ORDER BY result.label ASC
""".strip()


def _build_graph_client() -> Neo4jReadClient:
    """Create one read-only graph client from centralized API settings."""
    settings = get_settings()
    return Neo4jReadClient(
        uri=settings.neo4j_uri,
        username=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )


@router.get(
    "/graph/stats",
    response_model=GraphStatsResponse,
    responses={
        503: {"model": ApiErrorResponse, "description": "Graph backend is unavailable."},
        500: {"model": ApiErrorResponse, "description": "Unexpected API failure."},
    },
    summary="Inspect runtime graph counts",
)
def graph_stats(
    include_label_counts: bool = Query(default=False, description="Include per-label node counts in the response."),
) -> GraphStatsResponse | JSONResponse:
    """Return debug-friendly counts for the current runtime graph.

    This endpoint reports total node count, total edge count, incident count, and
    optional per-label node counts. It is read-only and does not invoke prompting.
    """
    client = _build_graph_client()
    try:
        rows = client.run_query(GRAPH_COUNTS_QUERY)
        payload = rows[0].get("result", {}) if rows else {}

        label_counts: dict[str, int] | None = None
        if include_label_counts:
            label_counts = {}
            for row in client.run_query(LABEL_COUNTS_QUERY):
                result = row.get("result", {})
                label = result.get("label")
                count = result.get("count")
                if isinstance(label, str) and isinstance(count, int):
                    label_counts[label] = count

        return GraphStatsResponse(
            node_count=int(payload.get("node_count", 0)),
            edge_count=int(payload.get("edge_count", 0)),
            incident_count=int(payload.get("incident_count", 0)),
            label_counts=label_counts,
        )
    except ApiError as exc:
        return JSONResponse(status_code=exc.status_code, content=to_error_response(exc).model_dump())
    except Exception as exc:
        error = _map_graph_error(exc, message="Failed to load graph stats.")
        return JSONResponse(status_code=error.status_code, content=to_error_response(error).model_dump())
    finally:
        client.close()


@router.get(
    "/graph/incident/{incident_id}",
    response_model=IncidentGraphResponse,
    responses={
        404: {"model": ApiErrorResponse, "description": "Incident could not be found."},
        503: {"model": ApiErrorResponse, "description": "Graph backend is unavailable."},
        500: {"model": ApiErrorResponse, "description": "Unexpected API failure."},
    },
    summary="Inspect one incident-centered graph traversal",
)
def incident_graph(incident_id: str) -> IncidentGraphResponse | JSONResponse:
    """Return the incident-centered traversal payload for one incident ID.

    The payload is intentionally debug-friendly and includes the raw traversal
    neighborhood shape: nodes, edges, hypotheses, runbooks, and any traversal
    warnings. Missing incidents return a stable 404-style API error.
    """
    client = _build_graph_client()
    traversal = IncidentTraversal(client)
    try:
        result = traversal.traverse(incident_id)
        if not result.nodes or not any(node.get("node_id") == result.incident_id for node in result.nodes):
            raise IncidentNotFoundError(
                f"Incident not found: {result.incident_id}",
                details={"incident_id": result.incident_id},
            )

        return IncidentGraphResponse(
            incident_id=result.incident_id,
            nodes=result.nodes,
            edges=result.edges,
            hypotheses=result.hypotheses,
            runbooks=result.runbooks,
            warnings=result.warnings,
        )
    except ApiError as exc:
        return JSONResponse(status_code=exc.status_code, content=to_error_response(exc).model_dump())
    except Exception as exc:
        error = _map_graph_error(exc, message=f"Failed to inspect incident graph for '{incident_id}'.")
        return JSONResponse(status_code=error.status_code, content=to_error_response(error).model_dump())
    finally:
        client.close()


def _map_graph_error(exc: Exception, *, message: str) -> GraphUnavailableError:
    """Normalize graph dependency failures into one stable API exception."""
    return GraphUnavailableError(message, details={"reason": str(exc)})


__all__ = ["router"]
