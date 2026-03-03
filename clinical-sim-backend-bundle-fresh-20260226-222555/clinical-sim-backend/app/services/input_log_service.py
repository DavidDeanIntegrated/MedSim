"""Service for persisting and querying user input logs.

Every turn submitted to the sim is logged to SQLite for later review,
search, and export. Supports flagging problematic inputs for follow-up.
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Feedback, InputLog


class InputLogService:
    """Writes and reads from the input_logs and feedback tables."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ── Write ──────────────────────────────────────────────────────

    def log_input(
        self,
        *,
        session_id: str,
        case_id: str | None,
        user_id: str | None,
        turn_index: int,
        turn_id: str | None,
        sim_time_sec: float,
        raw_input: str,
        normalized_input: str | None = None,
        parser_mode: str | None = None,
        action_count: int = 0,
        parsed_actions_summary: str | None = None,
        had_parse_failure: bool = False,
    ) -> InputLog:
        entry = InputLog(
            session_id=session_id,
            case_id=case_id,
            user_id=user_id,
            turn_index=turn_index,
            turn_id=turn_id,
            sim_time_sec=sim_time_sec,
            raw_input=raw_input,
            normalized_input=normalized_input,
            parser_mode=parser_mode,
            action_count=action_count,
            parsed_actions_summary=parsed_actions_summary,
            had_parse_failure=had_parse_failure,
        )
        self.db.add(entry)
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def flag_input(self, input_log_id: str, reason: str, category: str = "other", notes: str | None = None) -> InputLog | None:
        entry = self.db.query(InputLog).filter(InputLog.id == input_log_id).first()
        if not entry:
            return None
        entry.flagged = True
        entry.flag_reason = reason
        entry.flag_category = category
        if notes:
            entry.notes = notes
        self.db.commit()
        self.db.refresh(entry)
        return entry

    def add_feedback(
        self,
        *,
        title: str,
        category: str = "general",
        severity: str = "low",
        description: str | None = None,
        input_log_id: str | None = None,
        session_id: str | None = None,
    ) -> Feedback:
        fb = Feedback(
            title=title,
            category=category,
            severity=severity,
            description=description,
            input_log_id=input_log_id,
            session_id=session_id,
        )
        self.db.add(fb)
        self.db.commit()
        self.db.refresh(fb)
        return fb

    def update_feedback_status(self, feedback_id: str, status: str) -> Feedback | None:
        fb = self.db.query(Feedback).filter(Feedback.id == feedback_id).first()
        if not fb:
            return None
        fb.status = status
        if status == "resolved":
            fb.resolved_at = datetime.now(timezone.utc)
        self.db.commit()
        self.db.refresh(fb)
        return fb

    # ── Read ───────────────────────────────────────────────────────

    def list_inputs(
        self,
        *,
        flagged_only: bool = False,
        case_id: str | None = None,
        session_id: str | None = None,
        search: str | None = None,
        category: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = self.db.query(InputLog)
        if flagged_only:
            q = q.filter(InputLog.flagged == True)  # noqa: E712
        if case_id:
            q = q.filter(InputLog.case_id == case_id)
        if session_id:
            q = q.filter(InputLog.session_id == session_id)
        if search:
            q = q.filter(InputLog.raw_input.ilike(f"%{search}%"))
        if category:
            q = q.filter(InputLog.flag_category == category)

        total = q.count()
        items = q.order_by(InputLog.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": [self._input_to_dict(i) for i in items],
        }

    def get_input(self, input_log_id: str) -> dict | None:
        entry = self.db.query(InputLog).filter(InputLog.id == input_log_id).first()
        if not entry:
            return None
        return self._input_to_dict(entry)

    def list_feedback(
        self,
        *,
        status: str | None = None,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        q = self.db.query(Feedback)
        if status:
            q = q.filter(Feedback.status == status)
        if category:
            q = q.filter(Feedback.category == category)

        total = q.count()
        items = q.order_by(Feedback.created_at.desc()).offset(offset).limit(limit).all()

        return {
            "total": total,
            "offset": offset,
            "limit": limit,
            "items": [self._feedback_to_dict(f) for f in items],
        }

    def get_stats(self) -> dict[str, Any]:
        total = self.db.query(InputLog).count()
        flagged = self.db.query(InputLog).filter(InputLog.flagged == True).count()  # noqa: E712
        parse_failures = self.db.query(InputLog).filter(InputLog.had_parse_failure == True).count()  # noqa: E712
        open_feedback = self.db.query(Feedback).filter(Feedback.status == "open").count()

        # Unique sessions and cases
        from sqlalchemy import func
        unique_sessions = self.db.query(func.count(func.distinct(InputLog.session_id))).scalar() or 0
        unique_cases = self.db.query(func.count(func.distinct(InputLog.case_id))).scalar() or 0

        return {
            "total_inputs": total,
            "flagged_inputs": flagged,
            "parse_failures": parse_failures,
            "open_feedback": open_feedback,
            "unique_sessions": unique_sessions,
            "unique_cases": unique_cases,
        }

    def export_csv(
        self,
        *,
        flagged_only: bool = False,
        case_id: str | None = None,
    ) -> str:
        q = self.db.query(InputLog)
        if flagged_only:
            q = q.filter(InputLog.flagged == True)  # noqa: E712
        if case_id:
            q = q.filter(InputLog.case_id == case_id)
        items = q.order_by(InputLog.created_at.desc()).all()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "id", "session_id", "case_id", "user_id", "turn_index", "turn_id",
            "sim_time_sec", "raw_input", "action_count", "parsed_actions_summary",
            "had_parse_failure", "flagged", "flag_reason", "flag_category", "notes", "created_at",
        ])
        for i in items:
            writer.writerow([
                i.id, i.session_id, i.case_id, i.user_id, i.turn_index, i.turn_id,
                i.sim_time_sec, i.raw_input, i.action_count, i.parsed_actions_summary,
                i.had_parse_failure, i.flagged, i.flag_reason, i.flag_category, i.notes,
                i.created_at.isoformat() if i.created_at else "",
            ])
        return output.getvalue()

    # ── Helpers ────────────────────────────────────────────────────

    @staticmethod
    def _input_to_dict(entry: InputLog) -> dict:
        return {
            "id": entry.id,
            "session_id": entry.session_id,
            "case_id": entry.case_id,
            "user_id": entry.user_id,
            "turn_index": entry.turn_index,
            "turn_id": entry.turn_id,
            "sim_time_sec": entry.sim_time_sec,
            "raw_input": entry.raw_input,
            "normalized_input": entry.normalized_input,
            "parser_mode": entry.parser_mode,
            "action_count": entry.action_count,
            "parsed_actions_summary": entry.parsed_actions_summary,
            "had_parse_failure": entry.had_parse_failure,
            "flagged": entry.flagged,
            "flag_reason": entry.flag_reason,
            "flag_category": entry.flag_category,
            "notes": entry.notes,
            "created_at": entry.created_at.isoformat() if entry.created_at else None,
        }

    @staticmethod
    def _feedback_to_dict(fb: Feedback) -> dict:
        return {
            "id": fb.id,
            "input_log_id": fb.input_log_id,
            "session_id": fb.session_id,
            "category": fb.category,
            "severity": fb.severity,
            "title": fb.title,
            "description": fb.description,
            "status": fb.status,
            "resolved_at": fb.resolved_at.isoformat() if fb.resolved_at else None,
            "created_at": fb.created_at.isoformat() if fb.created_at else None,
        }
