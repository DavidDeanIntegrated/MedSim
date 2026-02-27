from __future__ import annotations

from app.domain.state_machine import SimulationStateMachine
from app.models.engine import (
    ActionResult,
    EngineExecutorContract,
    ExecuteTurnRequest,
    ScoringUpdates,
    SimEvent,
    UIUpdates,
)


class EngineService:
    def __init__(self) -> None:
        self.state_machine = SimulationStateMachine()

    def execute_turn(self, patient_state: dict, request: ExecuteTurnRequest) -> EngineExecutorContract:
        parsed_actions = [action.model_dump(by_alias=False) for action in request.parsed_turn.actions]
        new_state, delta, events_raw = self.state_machine.apply_actions(
            patient_state=patient_state,
            actions=parsed_actions,
            advance_time_sec=request.advance_time_sec,
        )

        action_results = []
        for action in request.parsed_turn.actions:
            action_results.append(
                ActionResult(
                    actionUuid=action.action_uuid,
                    sequenceIndex=action.sequence_index,
                    toolName=action.tool_name,
                    requestedPayload=action.payload,
                    executionResult="executed" if not action.blocking_errors else "deferred",
                    appliedPayload=action.payload if not action.blocking_errors else None,
                    executionReason="Executed by deterministic MVP engine" if not action.blocking_errors else "Blocked by validation",
                    blockingErrors=action.blocking_errors,
                    warnings=action.warnings,
                    stateChangeSummary=["Turn executed by deterministic engine"],
                    generatedEvents=[e["eventId"] for e in events_raw],
                )
            )

        sim_events = [SimEvent(**event) for event in events_raw]
        hemo = new_state.get("hemodynamics", {})
        resp = new_state.get("respiratory", {})
        ui = UIUpdates(
            monitorUpdates={
                "sbp": hemo.get("sbp"),
                "dbp": hemo.get("dbp"),
                "map": hemo.get("map"),
                "hr": hemo.get("hr"),
                "rr": resp.get("rr"),
                "spo2": resp.get("spo2"),
                "rhythm": hemo.get("rhythm"),
                "alarm_flags": new_state.get("monitor", {}).get("waveform_flags", []),
            },
            panelUpdates={
                "new_lab_results": [
                    {
                        "lab_id": order.get("payload", {}).get("diagnostic_id"),
                        "display_text": order.get("payload", {}).get("result_text"),
                    }
                    for order in new_state.get("orders", [])
                    if order.get("payload", {}).get("status") == "resulted"
                    and order.get("payload", {}).get("diagnostic_id") in {"cmp", "troponin", "pregnancy_test", "urinalysis"}
                ],
                "new_imaging_results": [
                    {
                        "study_id": order.get("payload", {}).get("diagnostic_id"),
                        "display_text": order.get("payload", {}).get("result_text"),
                    }
                    for order in new_state.get("orders", [])
                    if order.get("payload", {}).get("status") == "resulted"
                    and order.get("payload", {}).get("diagnostic_id") in {"head_ct_noncontrast", "mri_brain", "ecg"}
                ],
                "active_infusions": [
                    {
                        "medication_id": med.get("medication_id"),
                        "display_rate": f"{med.get('current_infusion_rate')} mg/hr" if med.get("current_infusion_rate") else "0",
                    }
                    for med in new_state.get("active_medications", [])
                    if med.get("active")
                ],
                "exam_findings": [
                    f"Mental status: {new_state.get('neurologic', {}).get('mental_status', 'unknown')}",
                    f"GCS: {new_state.get('neurologic', {}).get('gcs', 'unknown')}",
                ],
            },
            notificationUpdates=[
                {"level": "critical" if event.severity == "critical" else "info", "message": event.summary}
                for event in sim_events[:3]
            ],
        )
        runtime_scoring = new_state.get("scoring", {}).get("runtime", {})
        scoring = ScoringUpdates(
            criticalActionsCompleted=runtime_scoring.get("critical_actions_completed_this_turn", []),
            harmEventsTriggered=runtime_scoring.get("harm_events_triggered_this_turn", []),
            scoreDelta=runtime_scoring.get("score_delta_this_turn", 0),
            runningScore=new_state.get("scoring", {}).get("final_score", 0),
            teachingMarkersAdded=runtime_scoring.get("teaching_markers_added_this_turn", []),
        )

        before_time = request.parsed_turn.timestamp_sim_sec
        after_time = new_state.get("case_metadata", {}).get("time_elapsed_sec", before_time)

        return EngineExecutorContract(
            contract_version="0.1.0",
            turnId=request.parsed_turn.turn_id,
            timestampSimSecBefore=before_time,
            timestampSimSecAfter=after_time,
            executionStatus="ok" if request.parsed_turn.parser_status == "ok" else "partial_success",
            actionResults=action_results,
            stateDelta=delta,
            updatedPatientState=new_state if request.include_full_state else {},
            newEvents=sim_events,
            uiUpdates=ui,
            voiceResponsePlan={
                "patient_response": {"should_speak": False, "text": None},
                "nurse_response": {"should_speak": True, "text": "Orders completed."},
                "system_response": {"should_speak": False, "text": None},
            },
            scoringUpdates=scoring,
            executorNotes=["Deterministic MVP engine in use"],
        )
