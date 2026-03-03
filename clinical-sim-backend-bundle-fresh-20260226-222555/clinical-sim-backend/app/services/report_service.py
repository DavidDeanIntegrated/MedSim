from __future__ import annotations

from typing import Any

from app.services.debrief_service import DebriefService


class ReportService:
    def __init__(self) -> None:
        self._debrief = DebriefService()

    def generate_final_report(self, session: dict[str, Any], include_transcript: bool = True, include_timeline: bool = True) -> dict[str, Any]:
        patient_state = session.get("patientState", {})
        events = session.get("events", [])
        transcript = session.get("transcript", []) if include_transcript else []
        scoring = patient_state.get("scoring", {})
        case_def = patient_state.get("case_definition_inline", {})

        # Generate structured debrief
        debrief = self._debrief.generate_debrief(session)

        condition = case_def.get("hidden_truth", {}).get("final_diagnosis", "Unknown Condition")
        management = case_def.get("authoring_notes", {}).get("summary", "No management summary provided.")
        opt_logic = case_def.get("recommended_management_logic", {})
        opt_ops = f"Preferred Strategy: {opt_logic.get('preferred_strategy', 'N/A')}\nPreferred Agents: {', '.join(opt_logic.get('preferred_agents', []))}"

        return {
            "condition": condition,
            "management": management,
            "optimalOperations": opt_ops,
            "summary": debrief.get("overall_assessment", {}).get("summary", "Simulation complete"),
            "caseId": session.get("activeCaseId"),
            "sessionId": session.get("sessionId"),
            "finalVitals": patient_state.get("hemodynamics", {}),
            "score": debrief.get("scoring_breakdown", {}).get("final_percent", scoring.get("final_score", 0)),
            "letterGrade": debrief.get("overall_assessment", {}).get("letter_grade", ""),
            "events": events if include_timeline else [],
            "transcript": transcript,
            "criticalActionsAnalysis": debrief.get("critical_actions_analysis", []),
            "harmEventsAnalysis": debrief.get("harm_events_analysis", []),
            "strengths": debrief.get("strengths", []),
            "areasForImprovement": debrief.get("areas_for_improvement", []),
            "studyRecommendations": debrief.get("study_recommendations", []),
            "boardReviewTopics": debrief.get("board_review_topics", []),
            "annotatedTimeline": debrief.get("annotated_timeline", []) if include_timeline else [],
            "scoringBreakdown": debrief.get("scoring_breakdown", {}),
            # Legacy fields for backward compatibility
            "whatWentWell": debrief.get("strengths", []),
            "whatCouldHaveGoneBetter": debrief.get("areas_for_improvement", []),
            "teachingPoints": case_def.get("debrief_template", {}).get("teaching_points", []),
        }
