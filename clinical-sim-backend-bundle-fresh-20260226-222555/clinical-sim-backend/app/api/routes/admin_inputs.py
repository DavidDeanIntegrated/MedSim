"""Admin endpoints for browsing, searching, flagging, and exporting user inputs.

Provides:
  GET  /admin/inputs                 — list/search all logged inputs
  GET  /admin/inputs/stats           — summary stats (total, flagged, parse failures)
  GET  /admin/inputs/export          — CSV export of inputs
  GET  /admin/inputs/{id}            — single input detail
  POST /admin/inputs/{id}/flag       — flag an input for review
  POST /admin/feedback               — create a feedback/issue entry
  GET  /admin/feedback               — list feedback entries
  PATCH /admin/feedback/{id}/status  — update feedback status
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.engine import get_db
from app.services.input_log_service import InputLogService

router = APIRouter(prefix="/admin", tags=["admin"])


def _get_service(db: Session = Depends(get_db)) -> InputLogService:
    return InputLogService(db)


# ── Input browsing ─────────────────────────────────────────────────


@router.get("/inputs")
def list_inputs(
    flagged_only: bool = False,
    case_id: str | None = None,
    session_id: str | None = None,
    search: str | None = None,
    category: str | None = None,
    limit: int = 100,
    offset: int = 0,
    svc: InputLogService = Depends(_get_service),
) -> dict:
    """List logged inputs with optional filters."""
    return svc.list_inputs(
        flagged_only=flagged_only,
        case_id=case_id,
        session_id=session_id,
        search=search,
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/inputs/stats")
def input_stats(svc: InputLogService = Depends(_get_service)) -> dict:
    """Summary statistics for logged inputs."""
    return svc.get_stats()


@router.get("/inputs/export")
def export_inputs(
    flagged_only: bool = False,
    case_id: str | None = None,
    svc: InputLogService = Depends(_get_service),
):
    """Export inputs as CSV file download."""
    csv_content = svc.export_csv(flagged_only=flagged_only, case_id=case_id)
    return StreamingResponse(
        iter([csv_content]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=medsim_inputs.csv"},
    )


@router.get("/inputs/{input_id}")
def get_input(input_id: str, svc: InputLogService = Depends(_get_service)) -> dict:
    """Get details for a single input log entry."""
    result = svc.get_input(input_id)
    if not result:
        raise HTTPException(status_code=404, detail="Input not found")
    return result


# ── Flagging ───────────────────────────────────────────────────────


class FlagRequest(BaseModel):
    reason: str
    category: str = "other"  # bug, parser_fail, ux, content, other
    notes: str | None = None


@router.post("/inputs/{input_id}/flag")
def flag_input(
    input_id: str,
    body: FlagRequest,
    svc: InputLogService = Depends(_get_service),
) -> dict:
    """Flag an input for review with a reason and category."""
    result = svc.flag_input(input_id, reason=body.reason, category=body.category, notes=body.notes)
    if not result:
        raise HTTPException(status_code=404, detail="Input not found")
    return {"status": "flagged", "id": result.id}


# ── Feedback / Issues ──────────────────────────────────────────────


class FeedbackRequest(BaseModel):
    title: str
    category: str = "general"
    severity: str = "low"
    description: str | None = None
    input_log_id: str | None = None
    session_id: str | None = None


@router.post("/feedback")
def create_feedback(body: FeedbackRequest, svc: InputLogService = Depends(_get_service)) -> dict:
    """Create a feedback/issue entry (optionally linked to a specific input)."""
    fb = svc.add_feedback(
        title=body.title,
        category=body.category,
        severity=body.severity,
        description=body.description,
        input_log_id=body.input_log_id,
        session_id=body.session_id,
    )
    return {"status": "created", "id": fb.id}


@router.get("/feedback")
def list_feedback(
    status: str | None = None,
    category: str | None = None,
    limit: int = 50,
    offset: int = 0,
    svc: InputLogService = Depends(_get_service),
) -> dict:
    """List feedback entries with optional filters."""
    return svc.list_feedback(status=status, category=category, limit=limit, offset=offset)


class StatusUpdate(BaseModel):
    status: str  # open, in_progress, resolved, wontfix


@router.patch("/feedback/{feedback_id}/status")
def update_feedback_status(
    feedback_id: str,
    body: StatusUpdate,
    svc: InputLogService = Depends(_get_service),
) -> dict:
    """Update the status of a feedback entry."""
    fb = svc.update_feedback_status(feedback_id, body.status)
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return {"status": "updated", "id": fb.id, "new_status": fb.status}
