"""Analytics and session replay API endpoints.

Provides:
  GET /sessions/{id}/replay     — full turn-by-turn timeline for session replay
  GET /sessions/{id}/debrief    — structured AI debrief for a session
  GET /analytics/learner/{uid}  — per-learner score trends and performance
  GET /analytics/cohort         — cohort-level analytics for educators
  GET /analytics/leaderboard    — anonymized leaderboard by case
"""

from __future__ import annotations

import os
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_session_service
from app.domain.adaptive_engine import AdaptiveEngine
from app.domain.scoring_engine import ScoringEngine
from app.services.debrief_service import DebriefService
from app.services.session_service import SessionService

router = APIRouter(tags=["analytics"])

_debrief_service = DebriefService()
_scoring_engine = ScoringEngine()
_adaptive_engine = AdaptiveEngine()

# --- Session-level endpoints ---


@router.get("/sessions/{session_id}/replay")
def get_session_replay(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    """Return full turn-by-turn replay data for a session."""
    try:
        session = session_service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    patient_state = session.get("patientState", {})
    transcript = session.get("transcript", [])
    events = session.get("events", [])

    # Build turn summaries from transcript
    turns = []
    for i, entry in enumerate(transcript):
        turns.append({
            "turn_index": i,
            "raw_input": entry.get("rawInput", entry.get("raw_input", "")),
            "sim_time_sec": entry.get("timestampSimSec", entry.get("timestamp_sim_sec", 0)),
            "actions": entry.get("actions", []),
            "vitals_after": entry.get("vitals_after", {}),
            "events_this_turn": entry.get("events", []),
        })

    return {
        "session_id": session_id,
        "case_id": session.get("activeCaseId"),
        "status": session.get("status"),
        "total_turns": len(turns),
        "total_sim_time_sec": patient_state.get("case_metadata", {}).get("time_elapsed_sec", 0),
        "turns": turns,
        "events": events,
        "final_vitals": patient_state.get("hemodynamics", {}),
        "final_score": patient_state.get("scoring", {}).get("final_score", 0),
    }


@router.get("/sessions/{session_id}/debrief")
def get_session_debrief(
    session_id: str,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    """Generate structured debrief for a completed session."""
    try:
        session = session_service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    debrief = _debrief_service.generate_debrief(session)
    return {
        "session_id": session_id,
        "case_id": session.get("activeCaseId"),
        "debrief": debrief,
    }


# --- Learner analytics ---


@router.get("/analytics/learner/{user_id}")
def get_learner_analytics(
    user_id: str,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    """Return per-learner performance history and trends.

    Scans all saved sessions for this user and computes aggregate stats.
    """
    sessions = _load_user_sessions(session_service, user_id)

    if not sessions:
        return {
            "user_id": user_id,
            "total_sessions": 0,
            "sessions": [],
            "trends": {},
            "recommended_difficulty": "standard",
        }

    session_summaries = []
    grades_for_adaptive = []
    cases_attempted: dict[str, list[float]] = {}

    for s in sessions:
        ps = s.get("patientState", {})
        scoring = ps.get("scoring", {})
        case_id = s.get("activeCaseId", "unknown")
        score = scoring.get("final_score", 0)

        summary = {
            "session_id": s.get("sessionId"),
            "case_id": case_id,
            "score": score,
            "started_at": s.get("startedAt"),
            "status": s.get("status", "unknown"),
            "total_time_sec": ps.get("case_metadata", {}).get("time_elapsed_sec", 0),
        }
        session_summaries.append(summary)
        grades_for_adaptive.append({"final_percent": score})
        cases_attempted.setdefault(case_id, []).append(score)

    # Compute trends
    scores = [g["final_percent"] for g in grades_for_adaptive]
    avg_score = sum(scores) / len(scores) if scores else 0

    # Per-case best scores
    case_bests = {cid: max(sc) for cid, sc in cases_attempted.items()}

    # Recommended difficulty
    profile = _adaptive_engine.recommend_difficulty(grades_for_adaptive)

    return {
        "user_id": user_id,
        "total_sessions": len(sessions),
        "average_score": round(avg_score, 1),
        "cases_attempted": len(cases_attempted),
        "case_best_scores": case_bests,
        "recommended_difficulty": profile.level,
        "difficulty_description": profile.description,
        "sessions": sorted(session_summaries, key=lambda x: x.get("started_at", ""), reverse=True),
    }


# --- Cohort analytics ---


@router.get("/analytics/cohort")
def get_cohort_analytics(
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    """Return aggregate cohort analytics across all learners.

    Useful for educators to see overall performance patterns.
    """
    all_sessions = _load_all_sessions(session_service)

    if not all_sessions:
        return {
            "total_sessions": 0,
            "total_learners": 0,
            "cases": {},
        }

    # Group by case
    by_case: dict[str, list[dict]] = {}
    learner_ids: set[str] = set()

    for s in all_sessions:
        case_id = s.get("activeCaseId")
        if not case_id:
            continue
        ps = s.get("patientState", {})
        score = ps.get("scoring", {}).get("final_score", 0)
        uid = s.get("userId", "anonymous")
        learner_ids.add(uid)

        by_case.setdefault(case_id, []).append({
            "score": score,
            "user_id": uid,
            "time_sec": ps.get("case_metadata", {}).get("time_elapsed_sec", 0),
        })

    # Compute per-case stats
    case_stats: dict[str, dict] = {}
    for case_id, entries in by_case.items():
        scores = [e["score"] for e in entries]
        times = [e["time_sec"] for e in entries if e["time_sec"] > 0]
        case_stats[case_id] = {
            "attempts": len(entries),
            "unique_learners": len({e["user_id"] for e in entries}),
            "avg_score": round(sum(scores) / len(scores), 1) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "avg_time_sec": round(sum(times) / len(times), 1) if times else 0,
        }

    return {
        "total_sessions": len(all_sessions),
        "total_learners": len(learner_ids),
        "cases": case_stats,
    }


# --- Leaderboard ---


@router.get("/analytics/leaderboard/{case_id}")
def get_leaderboard(
    case_id: str,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    """Return anonymized leaderboard for a specific case."""
    all_sessions = _load_all_sessions(session_service)

    entries = []
    for s in all_sessions:
        if s.get("activeCaseId") != case_id:
            continue
        ps = s.get("patientState", {})
        score = ps.get("scoring", {}).get("final_score", 0)
        uid = s.get("userId", "anonymous")
        entries.append({
            "user_hash": uid[:8],  # Anonymized
            "score": score,
            "time_sec": ps.get("case_metadata", {}).get("time_elapsed_sec", 0),
        })

    # Sort by score descending
    entries.sort(key=lambda x: x["score"], reverse=True)

    return {
        "case_id": case_id,
        "total_attempts": len(entries),
        "leaderboard": entries[:20],  # Top 20
    }


# --- Adaptive difficulty recommendation ---


@router.get("/analytics/recommend-difficulty/{user_id}")
def recommend_difficulty(
    user_id: str,
    case_id: str | None = None,
    session_service: SessionService = Depends(get_session_service),
) -> dict:
    """Recommend difficulty level for a learner."""
    sessions = _load_user_sessions(session_service, user_id)

    # Filter by case if specified
    if case_id:
        sessions = [s for s in sessions if s.get("activeCaseId") == case_id]

    grades = []
    for s in sessions:
        ps = s.get("patientState", {})
        score = ps.get("scoring", {}).get("final_score", 0)
        grades.append({"final_percent": score})

    profile = _adaptive_engine.recommend_difficulty(grades)

    return {
        "user_id": user_id,
        "case_id": case_id,
        "sessions_analyzed": len(grades),
        "recommended_difficulty": profile.to_dict(),
    }


# --- Helpers ---


def _load_user_sessions(service: SessionService, user_id: str) -> list[dict]:
    """Load all sessions for a given user from the file-based repo."""
    all_sessions = _load_all_sessions(service)
    return [s for s in all_sessions if s.get("userId") == user_id]


def _load_all_sessions(service: SessionService) -> list[dict]:
    """Load all sessions from the file-based session repository."""
    sessions_dir = Path(service.repo.base_dir)
    results = []
    if not sessions_dir.exists():
        return results
    for fpath in sessions_dir.glob("*.json"):
        try:
            with open(fpath) as f:
                data = json.load(f)
            results.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return results
