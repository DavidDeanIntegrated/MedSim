from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_session_service
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions/{session_id}", tags=["state"])


@router.get("/state")
def get_case_state(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> dict:
    try:
        session = service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {
        "sessionId": session_id,
        "caseId": session.get("activeCaseId"),
        "patientState": session.get("patientState"),
    }


@router.get("/state/summary")
def get_case_state_summary(
    session_id: str,
    service: SessionService = Depends(get_session_service),
) -> dict:
    try:
        session = service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    patient_state = session.get("patientState") or {}
    hemo = patient_state.get("hemodynamics", {})
    resp = patient_state.get("respiratory", {})
    return {
        "sessionId": session_id,
        "caseId": session.get("activeCaseId"),
        "timeSec": patient_state.get("case_metadata", {}).get("time_elapsed_sec", 0),
        "status": patient_state.get("case_metadata", {}).get("status", "unknown"),
        "monitor": {
            "sbp": hemo.get("sbp"),
            "dbp": hemo.get("dbp"),
            "map": hemo.get("map"),
            "hr": hemo.get("hr"),
            "rr": resp.get("rr"),
            "spo2": resp.get("spo2"),
            "rhythm": hemo.get("rhythm"),
            "alarmFlags": patient_state.get("monitor", {}).get("waveform_flags", []),
        },
    }


@router.get("/events")
def get_events(
    session_id: str,
    since_time_sec: float | None = None,
    limit: int = 100,
    service: SessionService = Depends(get_session_service),
) -> dict:
    try:
        session = service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    events = session.get("events", [])
    if since_time_sec is not None:
        events = [e for e in events if e.get("timeSec", 0) >= since_time_sec]
    return {"events": events[:limit]}
