from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_report_service, get_session_service
from app.services.report_service import ReportService
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions/{session_id}", tags=["reports"])


@router.post("/reports/final")
def generate_final_report(
    session_id: str,
    request: dict | None = None,
    session_service: SessionService = Depends(get_session_service),
    report_service: ReportService = Depends(get_report_service),
) -> dict:
    try:
        session = session_service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    request = request or {}
    report = report_service.generate_final_report(
        session,
        include_transcript=request.get("includeTranscript", True),
        include_timeline=request.get("includeTimeline", True),
    )
    return {
        "sessionId": session_id,
        "caseId": session.get("activeCaseId"),
        "report": report,
    }
