"""Case library listing endpoint."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/cases", tags=["cases"])


@router.get("")
def list_cases() -> dict:
    """List all available simulation cases with metadata."""
    settings = get_settings()
    cases_dir = settings.data_dir / "cases"
    cases = []

    if cases_dir.exists():
        for case_file in sorted(cases_dir.glob("*.json")):
            try:
                data = json.loads(case_file.read_text(encoding="utf-8"))
                cases.append({
                    "caseId": data.get("case_id", case_file.stem),
                    "title": data.get("title", "Untitled"),
                    "category": data.get("category", data.get("scenario_type", "general")),
                    "difficulty": data.get("difficulty", "moderate"),
                    "description": data.get("authoring_notes", {}).get("summary", ""),
                    "teachingFocus": data.get("authoring_notes", {}).get("teaching_focus", []),
                    "patientName": data.get("patient_profile", {}).get("name", "Unknown"),
                    "patientAge": data.get("patient_profile", {}).get("age_years"),
                    "version": data.get("case_file_version", "1.0.0"),
                })
            except (json.JSONDecodeError, KeyError):
                continue

    return {
        "totalCases": len(cases),
        "cases": cases,
    }


@router.get("/{case_id}")
def get_case_metadata(case_id: str) -> dict:
    """Get detailed metadata for a specific case (without full state data)."""
    settings = get_settings()
    case_path = settings.data_dir / "cases" / f"{case_id}.json"

    if not case_path.exists():
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found")

    data = json.loads(case_path.read_text(encoding="utf-8"))

    return {
        "caseId": data.get("case_id", case_id),
        "title": data.get("title"),
        "category": data.get("category", data.get("scenario_type")),
        "difficulty": data.get("difficulty"),
        "description": data.get("authoring_notes", {}).get("summary"),
        "teachingFocus": data.get("authoring_notes", {}).get("teaching_focus", []),
        "patientProfile": data.get("patient_profile"),
        "openingScript": data.get("opening_script"),
        "criticalActions": [
            {"id": ca["id"], "description": ca["description"], "weight": ca.get("weight", 0)}
            for ca in data.get("critical_actions", [])
        ],
        "harmEvents": [
            {"id": he["id"], "description": he["description"], "severity": he.get("severity", 0)}
            for he in data.get("harm_events", [])
        ],
        "successCriteria": data.get("success_criteria"),
        "version": data.get("case_file_version"),
    }
