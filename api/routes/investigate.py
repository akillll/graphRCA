"""Route handlers for RCA investigation requests.

This module exposes the main GraphRCA investigation flow over HTTP while keeping
route logic thin. Retrieval, traversal, prompt generation, and RCA shaping stay
inside the service layer.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from api.errors import ApiError, UnexpectedApiError, to_error_response
from api.service import InvestigationService
from api.types import ApiErrorResponse, InvestigateRequest, InvestigateResponse


router = APIRouter(tags=["investigation"])


def _build_service() -> InvestigationService:
    """Create one investigation service instance for the current request."""
    return InvestigationService()


@router.post(
    "/investigate",
    response_model=InvestigateResponse,
    responses={
        400: {"model": ApiErrorResponse, "description": "Invalid investigation request."},
        404: {"model": ApiErrorResponse, "description": "Incident could not be found."},
        502: {"model": ApiErrorResponse, "description": "Prompt generation or parsing failed."},
        503: {"model": ApiErrorResponse, "description": "Graph or model backend is unavailable."},
        500: {"model": ApiErrorResponse, "description": "Unexpected API failure."},
    },
    summary="Investigate one incident question",
)
def investigate(request: InvestigateRequest) -> InvestigateResponse | JSONResponse:
    """Run the full GraphRAG RCA flow for one user question.

    The handler accepts a validated `InvestigateRequest`, delegates orchestration
    to `InvestigationService`, and returns a grounded `InvestigateResponse`.
    Known API failures are converted into a stable `ApiErrorResponse` envelope
    without exposing raw stack traces.
    """
    service = _build_service()
    try:
        return service.investigate(request)
    except ApiError as exc:
        error_response = to_error_response(exc)
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response.model_dump(),
        )
    except Exception:
        error = UnexpectedApiError("Unexpected API failure during investigation.")
        error_response = to_error_response(error)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_response.model_dump(),
        )
    finally:
        service.close()


__all__ = ["router"]
