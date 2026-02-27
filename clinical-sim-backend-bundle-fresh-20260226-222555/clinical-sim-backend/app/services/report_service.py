from __future__ import annotations

from typing import Any


class ReportService:
    def generate_final_report(self, session: dict[str, Any], include_transcript: bool = True, include_timeline: bool = True) -> dict[str, Any]:
        patient_state = session.get("patientState", {})
        events = session.get("events", [])
        transcript = session.get("transcript", []) if include_transcript else []
        scoring = patient_state.get("scoring", {})

        return {
            "summary": "MVP final report",
            "caseId": session.get("activeCaseId"),
            "sessionId": session.get("sessionId"),
            "finalVitals": patient_state.get("hemodynamics", {}),
            "score": scoring.get("final_score", 0),
            "events": events if include_timeline else [],
            "transcript": transcript,
            "whatWentWell": [k for k, v in scoring.get("runtime_flags", {}).items() if v],
            "whatCouldHaveGoneBetter": [k for k, v in scoring.get("harm_runtime_flags", {}).items() if v],
            "teachingPoints": patient_state.get("case_definition_inline", {}).get("debrief_template", {}).get("teaching_points", []),
        }
