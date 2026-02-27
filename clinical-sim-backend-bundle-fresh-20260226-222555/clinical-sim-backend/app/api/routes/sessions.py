from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.api.deps import get_session_service
from app.models.session import (
    CreateSessionRequest,
    CreateSessionResponse,
    ResetCaseResponse,
    SessionSummary,
    StartCaseRequest,
    StartCaseResponse,
)
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["session"])


@router.post("", response_model=CreateSessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(
    request: CreateSessionRequest,
    service: SessionService = Depends(get_session_service),
) -> CreateSessionResponse:
    session = service.create_session(request.user_id, request.site_id, request.device_mode, request.metadata)
    return CreateSessionResponse(
        sessionId=session["sessionId"],
        createdAt=session["lastActivityAt"],
        status="created",
        summary=SessionSummary(
            sessionId=session["sessionId"],
            status="created",
            activeCaseId=session["activeCaseId"],
            startedAt=session["startedAt"],
            lastActivityAt=session["lastActivityAt"],
        ),
    )


@router.get("/{session_id}", response_model=SessionSummary)
def get_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> SessionSummary:
    try:
        session = service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return SessionSummary(
        sessionId=session["sessionId"],
        status=session["status"],
        activeCaseId=session.get("activeCaseId"),
        startedAt=session.get("startedAt"),
        lastActivityAt=session.get("lastActivityAt"),
    )


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> Response:
    service.delete_session(session_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{session_id}/start-case", response_model=StartCaseResponse)
def start_case(
    session_id: str,
    request: StartCaseRequest,
    service: SessionService = Depends(get_session_service),
) -> StartCaseResponse:
    try:
        result = service.start_case(session_id, request.case_id, request.difficulty, request.custom_case_overrides)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return StartCaseResponse(**result)


@router.post("/{session_id}/reset-case", response_model=ResetCaseResponse)
def reset_case(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> ResetCaseResponse:
    try:
        result = service.reset_case(session_id)
    except (FileNotFoundError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return ResetCaseResponse(**result)
