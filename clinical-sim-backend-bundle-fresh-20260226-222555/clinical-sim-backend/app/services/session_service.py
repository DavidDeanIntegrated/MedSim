from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

from app.domain.case_loader import CaseLoader
from app.repositories.session_repo import SessionRepository


class SessionService:
    def __init__(self, repo: SessionRepository, case_loader: CaseLoader) -> None:
        self.repo = repo
        self.case_loader = case_loader

    def create_session(self, user_id: str, site_id: str | None, device_mode: str, metadata: dict) -> dict:
        session_id = str(uuid4())
        now = datetime.now(timezone.utc).isoformat()
        session = {
            "sessionId": session_id,
            "status": "created",
            "userId": user_id,
            "siteId": site_id,
            "deviceMode": device_mode,
            "metadata": metadata,
            "activeCaseId": None,
            "startedAt": None,
            "lastActivityAt": now,
            "patientState": None,
            "transcript": [],
            "events": [],
        }
        self.repo.save(session_id, session)
        return session

    def get_session(self, session_id: str) -> dict:
        return self.repo.load(session_id)

    def delete_session(self, session_id: str) -> None:
        self.repo.delete(session_id)

    def start_case(self, session_id: str, case_id: str, difficulty: str, custom_case_overrides: dict | None = None) -> dict:
        session = self.repo.load(session_id)
        case = self.case_loader.load_case(case_id)
        initial_state = deepcopy(case["initial_state"])
        initial_state["case_metadata"] = deepcopy(case["case_metadata"])
        initial_state["case_metadata"]["difficulty"] = difficulty
        initial_state["case_metadata"]["status"] = "running"
        initial_state["case_definition_inline"] = {
            "case_id": case.get("case_id", case_id),
            "title": case.get("title"),
            "difficulty": difficulty,
            "scenario_type": case.get("scenario_type"),
            "hidden_truth": deepcopy(case.get("hidden_truth", {})),
            "time_course": deepcopy(case.get("time_course", {})),
            "critical_actions": deepcopy(case.get("critical_actions", [])),
            "harm_events": deepcopy(case.get("harm_events", [])),
            "recommended_management_logic": deepcopy(case.get("recommended_management_logic", {})),
            "triggered_diagnostics": deepcopy(case.get("triggered_diagnostics", {})),
            "success_criteria": deepcopy(case.get("success_criteria", {})),
            "failure_criteria": deepcopy(case.get("failure_criteria", {})),
            "debrief_template": deepcopy(case.get("debrief_template", {})),
        }
        initial_state.setdefault("case_runtime", {})
        initial_state["case_runtime"]["starting_map"] = initial_state.get("hemodynamics", {}).get("map")
        initial_state["case_runtime"]["starting_sbp"] = initial_state.get("hemodynamics", {}).get("sbp")
        initial_state["case_runtime"]["starting_dbp"] = initial_state.get("hemodynamics", {}).get("dbp")
        initial_state["case_runtime"]["starting_hr"] = initial_state.get("hemodynamics", {}).get("hr")
        initial_state["case_runtime"]["diagnostic_results_released"] = []
        initial_state["case_runtime"]["last_turn_time_sec"] = 0

        if custom_case_overrides:
            initial_state.update(custom_case_overrides)

        session["activeCaseId"] = case_id
        session["status"] = "active"
        session["startedAt"] = datetime.now(timezone.utc).isoformat()
        session["patientState"] = initial_state
        session["caseDefinition"] = case
        session["lastActivityAt"] = datetime.now(timezone.utc).isoformat()
        self.repo.save(session_id, session)

        return {
            "sessionId": session_id,
            "caseId": case_id,
            "status": "running",
            "initialState": initial_state,
            "openingScript": case.get("opening_script", {}),
        }

    def reset_case(self, session_id: str) -> dict:
        session = self.repo.load(session_id)
        case_id = session["activeCaseId"]
        if not case_id:
            raise ValueError("No active case to reset")
        case = self.case_loader.load_case(case_id)
        initial_state = deepcopy(case["initial_state"])
        initial_state["case_metadata"] = deepcopy(case["case_metadata"])
        initial_state["case_metadata"]["status"] = "running"
        initial_state["case_definition_inline"] = {
            "case_id": case.get("case_id", case_id),
            "title": case.get("title"),
            "difficulty": initial_state.get("case_metadata", {}).get("difficulty", case.get("difficulty", "moderate")),
            "scenario_type": case.get("scenario_type"),
            "hidden_truth": deepcopy(case.get("hidden_truth", {})),
            "time_course": deepcopy(case.get("time_course", {})),
            "critical_actions": deepcopy(case.get("critical_actions", [])),
            "harm_events": deepcopy(case.get("harm_events", [])),
            "recommended_management_logic": deepcopy(case.get("recommended_management_logic", {})),
            "triggered_diagnostics": deepcopy(case.get("triggered_diagnostics", {})),
            "success_criteria": deepcopy(case.get("success_criteria", {})),
            "failure_criteria": deepcopy(case.get("failure_criteria", {})),
            "debrief_template": deepcopy(case.get("debrief_template", {})),
        }
        initial_state.setdefault("case_runtime", {})
        initial_state["case_runtime"]["starting_map"] = initial_state.get("hemodynamics", {}).get("map")
        initial_state["case_runtime"]["starting_sbp"] = initial_state.get("hemodynamics", {}).get("sbp")
        initial_state["case_runtime"]["starting_dbp"] = initial_state.get("hemodynamics", {}).get("dbp")
        initial_state["case_runtime"]["starting_hr"] = initial_state.get("hemodynamics", {}).get("hr")
        initial_state["case_runtime"]["diagnostic_results_released"] = []
        initial_state["case_runtime"]["last_turn_time_sec"] = 0
        session["patientState"] = initial_state
        session["events"] = []
        session["transcript"] = []
        session["lastActivityAt"] = datetime.now(timezone.utc).isoformat()
        self.repo.save(session_id, session)
        return {"sessionId": session_id, "caseId": case_id, "status": "reset"}

    def update_session_state(self, session_id: str, patient_state: dict, new_events: list[dict], transcript_entry: dict | None = None) -> dict:
        session = self.repo.load(session_id)
        session["patientState"] = patient_state
        session.setdefault("events", []).extend(new_events)
        if transcript_entry is not None:
            session.setdefault("transcript", []).append(transcript_entry)
        session["lastActivityAt"] = datetime.now(timezone.utc).isoformat()
        self.repo.save(session_id, session)
        return session
