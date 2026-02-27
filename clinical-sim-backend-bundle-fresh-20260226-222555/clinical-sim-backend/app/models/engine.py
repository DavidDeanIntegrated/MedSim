from typing import Any, Literal

from pydantic import Field

from app.models.common import APIModel
from app.models.parser import RuntimeParserContract


class ActionResult(APIModel):
    action_uuid: str = Field(alias="actionUuid")
    sequence_index: int = Field(alias="sequenceIndex")
    tool_name: str | None = Field(default=None, alias="toolName")
    requested_payload: dict[str, Any] = Field(alias="requestedPayload")
    execution_result: Literal["executed", "executed_with_adjustment", "deferred", "rejected", "noop"] = Field(alias="executionResult")
    applied_payload: dict[str, Any] | None = Field(default=None, alias="appliedPayload")
    execution_reason: str | None = Field(default=None, alias="executionReason")
    blocking_errors: list[str] = Field(default_factory=list, alias="blockingErrors")
    warnings: list[str] = Field(default_factory=list)
    state_change_summary: list[str] = Field(default_factory=list, alias="stateChangeSummary")
    generated_events: list[str] = Field(default_factory=list, alias="generatedEvents")


class SimEvent(APIModel):
    event_id: str = Field(alias="eventId")
    time_sec: float = Field(alias="timeSec")
    event_type: Literal[
        "state_update",
        "medication_effect",
        "diagnostic_result_available",
        "clinical_improvement",
        "clinical_deterioration",
        "adverse_event",
        "critical_action_completed",
        "harm_event_triggered",
        "monitor_alarm",
        "dialogue_trigger",
        "case_progression",
    ] = Field(alias="eventType")
    severity: Literal["info", "low", "moderate", "high", "critical"]
    summary: str
    structured_data: dict[str, Any] = Field(default_factory=dict, alias="structuredData")


class UIUpdates(APIModel):
    monitor_updates: dict[str, Any] = Field(default_factory=dict, alias="monitorUpdates")
    panel_updates: dict[str, Any] = Field(default_factory=dict, alias="panelUpdates")
    notification_updates: list[dict[str, str]] = Field(default_factory=list, alias="notificationUpdates")


class ScoringUpdates(APIModel):
    critical_actions_completed: list[str] = Field(default_factory=list, alias="criticalActionsCompleted")
    harm_events_triggered: list[str] = Field(default_factory=list, alias="harmEventsTriggered")
    score_delta: float = Field(default=0, alias="scoreDelta")
    running_score: float = Field(default=0, alias="runningScore")
    teaching_markers_added: list[str] = Field(default_factory=list, alias="teachingMarkersAdded")


class ExecuteTurnRequest(APIModel):
    parsed_turn: RuntimeParserContract = Field(alias="parsedTurn")
    advance_time_sec: int = Field(default=5, alias="advanceTimeSec")
    include_full_state: bool = Field(default=True, alias="includeFullState")


class EngineExecutorContract(APIModel):
    contract_version: str
    turn_id: str = Field(alias="turnId")
    timestamp_sim_sec_before: float = Field(alias="timestampSimSecBefore")
    timestamp_sim_sec_after: float = Field(alias="timestampSimSecAfter")
    execution_status: Literal["ok", "partial_success", "clarification_needed", "execution_failed"] = Field(alias="executionStatus")
    action_results: list[ActionResult] = Field(default_factory=list, alias="actionResults")
    state_delta: dict[str, Any] = Field(default_factory=dict, alias="stateDelta")
    updated_patient_state: dict[str, Any] = Field(default_factory=dict, alias="updatedPatientState")
    new_events: list[SimEvent] = Field(default_factory=list, alias="newEvents")
    ui_updates: UIUpdates = Field(alias="uiUpdates")
    voice_response_plan: dict[str, Any] = Field(default_factory=dict, alias="voiceResponsePlan")
    scoring_updates: ScoringUpdates = Field(alias="scoringUpdates")
    executor_notes: list[str] = Field(default_factory=list, alias="executorNotes")
