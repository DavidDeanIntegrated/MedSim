from typing import Any, Literal

from pydantic import Field

from app.models.common import APIModel


class ClarificationTarget(APIModel):
    field: str
    reason: str
    related_action_uuid: str | None = Field(default=None, alias="relatedActionUuid")


class ParsedAction(APIModel):
    action_uuid: str = Field(alias="actionUuid")
    sequence_index: int = Field(alias="sequenceIndex")
    action_type: Literal["tool_call", "dialogue_act", "assessment_capture", "meta_command"] = Field(alias="actionType")
    tool_name: str | None = Field(default=None, alias="toolName")
    action_label: str = Field(alias="actionLabel")
    payload: dict[str, Any]
    confidence: float
    execution_mode: Literal["sequential", "parallel_safe", "hold_for_clarification"] = Field(alias="executionMode")
    requires_confirmation: bool = Field(alias="requiresConfirmation")
    confirmation_reason: str | None = Field(default=None, alias="confirmationReason")
    blocking_errors: list[str] = Field(default_factory=list, alias="blockingErrors")
    warnings: list[str] = Field(default_factory=list)
    derived_from_text_span: str | None = Field(default=None, alias="derivedFromTextSpan")
    mapping_action_id: str | None = Field(default=None, alias="mappingActionId")
    engine_hooks: list[str] = Field(default_factory=list, alias="engineHooks")


class ParseTurnRequest(APIModel):
    turn_id: str = Field(alias="turnId")
    timestamp_sim_sec: float = Field(alias="timestampSimSec")
    input_text: str = Field(alias="inputText")
    parser_mode: Literal["speech_to_actions", "text_to_actions", "mixed_voice_text"] = Field(alias="parserMode")
    speaker: Literal["resident", "attending", "nurse", "system"] = "resident"
    active_infusions: list[dict[str, Any]] = Field(default_factory=list, alias="activeInfusions")
    context_hints: dict[str, Any] = Field(default_factory=dict, alias="contextHints")


class RuntimeParserContract(APIModel):
    contract_version: str
    turn_id: str = Field(alias="turnId")
    timestamp_sim_sec: float = Field(alias="timestampSimSec")
    raw_input: str = Field(alias="rawInput")
    normalized_input: str = Field(alias="normalizedInput")
    parser_mode: str = Field(alias="parserMode")
    speaker: str = "resident"
    intent_summary: str = Field(alias="intentSummary")
    actions: list[ParsedAction]
    needs_clarification: bool = Field(alias="needsClarification")
    clarification_question: str | None = Field(default=None, alias="clarificationQuestion")
    clarification_targets: list[ClarificationTarget] = Field(default_factory=list, alias="clarificationTargets")
    overall_confidence: float = Field(alias="overallConfidence")
    parser_status: Literal["ok", "partial_parse", "clarification_required", "rejected"] = Field(alias="parserStatus")
    non_actionable_text: list[str] = Field(default_factory=list, alias="nonActionableText")
    parser_notes: list[str] = Field(default_factory=list, alias="parserNotes")
    safety_flags: list[str] = Field(default_factory=list, alias="safetyFlags")
