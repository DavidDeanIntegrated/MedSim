"""LLM-based parser mode using Claude with tool-use schema.

Routes through Claude with a tool-use schema matching the existing ParsedAction model.
Falls back to the regex parser if the API key is not set or on error.

parserMode: "llm" → this service
parserMode: "rule" → ParserService (regex, existing)
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from app.core.config import get_settings
from app.models.parser import ParseTurnRequest, RuntimeParserContract

logger = logging.getLogger(__name__)

# Tool-use schema for Claude — maps to ParsedAction fields
_TOOL_SCHEMA = {
    "name": "parse_clinical_order",
    "description": (
        "Parse a clinical order from an emergency medicine resident into structured actions. "
        "Return one or more actions representing medications, diagnostics, assessments, "
        "dispositions, monitoring changes, or supportive care."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "intent_summary": {
                "type": "string",
                "description": "Brief summary of what the resident is ordering",
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "action_type": {
                            "type": "string",
                            "enum": ["tool_call", "dialogue_act", "assessment_capture", "meta_command"],
                        },
                        "tool_name": {
                            "type": "string",
                            "enum": [
                                "start_infusion",
                                "adjust_infusion",
                                "stop_infusion",
                                "give_medication",
                                "order_diagnostic",
                                "set_monitoring",
                                "document_assessment",
                                "set_disposition",
                                "perform_reassessment",
                                "give_supportive_care",
                                "query_infusion_status",
                                "retrieve_diagnostic_result",
                                "clinical_query",
                                "help_command",
                            ],
                        },
                        "action_label": {"type": "string"},
                        "payload": {
                            "type": "object",
                            "description": "Action-specific parameters (medication_id, dose, rate, diagnostic_id, etc.)",
                        },
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                        "engine_hooks": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Scoring hooks to trigger (e.g. mark_critical_action_*)",
                        },
                    },
                    "required": ["action_type", "tool_name", "action_label", "payload", "confidence"],
                },
            },
            "needs_clarification": {"type": "boolean"},
            "clarification_question": {"type": "string"},
        },
        "required": ["intent_summary", "actions", "needs_clarification"],
    },
}

_SYSTEM_PROMPT = """You are a clinical order parser for an emergency medicine simulation.
Parse the resident's free-text order into structured actions.

MEDICATION IDs: nicardipine_iv, clevidipine_iv, labetalol_iv, hydralazine_iv, esmolol_iv,
nitroglycerin_iv, nitroprusside_iv, norepinephrine_iv, epinephrine_iv, phenylephrine_iv,
dopamine_iv, dobutamine_iv, vasopressin_iv, insulin_regular_iv, alteplase_iv, heparin_iv,
magnesium_sulfate_iv, furosemide_iv, amiodarone_iv, adenosine_iv, aspirin_po, morphine_iv,
fentanyl_iv, midazolam_iv, lorazepam_iv, dexamethasone_iv, methylprednisolone_iv,
albuterol_neb, ipratropium_neb, normal_saline_iv, lactated_ringers_iv

DIAGNOSTIC IDs: head_ct_noncontrast, mri_brain, ecg, cmp, troponin, pregnancy_test,
urinalysis, bnp, cbc, coagulation_panel, fingerstick_glucose, chest_xray, d_dimer, lactate,
ct_angiography_chest, ct_angiography_abdomen, blood_gas, blood_cultures, lipase, liver_panel,
urine_drug_screen, type_and_screen, procalcitonin

CRITICAL ENGINE HOOKS:
- mark_critical_action_recognize_htn_emergency (when assessing hypertensive emergency)
- mark_critical_action_establish_monitoring (when placing on monitor/telemetry)
- mark_critical_action_start_titratable_iv_agent (when starting nicardipine/clevidipine)
- mark_critical_action_order_neuro_workup (when ordering CT head or MRI brain)
- mark_critical_action_reassess_neuro_status (when reassessing patient)
- mark_critical_action_disposition (when admitting to ICU/floor)

Context: {context}
Active infusions: {active_infusions}
Current sim time: {sim_time_sec}s"""


class LLMParserService:
    """Parse clinical orders using Claude API with tool-use."""

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            settings = get_settings()
            if not settings.anthropic_api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            try:
                import anthropic
                self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
            except ImportError:
                raise ValueError("anthropic package not installed. Run: pip install anthropic")
        return self._client

    def parse_turn(self, request: ParseTurnRequest) -> RuntimeParserContract:
        settings = get_settings()

        try:
            client = self._get_client()
        except ValueError as e:
            logger.warning("LLM parser unavailable: %s — falling back to rule-based", e)
            raise

        system_msg = _SYSTEM_PROMPT.format(
            context=json.dumps(request.context_hints),
            active_infusions=json.dumps([
                {"medication_id": inf.get("medication_id"), "rate": inf.get("current_infusion_rate")}
                for inf in request.active_infusions
            ]),
            sim_time_sec=request.timestamp_sim_sec,
        )

        try:
            response = client.messages.create(
                model=settings.llm_parser_model,
                max_tokens=1024,
                system=system_msg,
                tools=[_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": "parse_clinical_order"},
                messages=[{"role": "user", "content": request.input_text}],
            )
        except Exception as e:
            logger.error("LLM parser API error: %s", e)
            raise ValueError(f"LLM API error: {e}") from e

        # Extract tool use result
        tool_result = None
        for block in response.content:
            if block.type == "tool_use" and block.name == "parse_clinical_order":
                tool_result = block.input
                break

        if tool_result is None:
            raise ValueError("LLM did not return a tool_use block")

        # Convert to RuntimeParserContract
        actions = []
        for i, action_raw in enumerate(tool_result.get("actions", [])):
            actions.append({
                "actionUuid": str(uuid4()),
                "sequenceIndex": i,
                "actionType": action_raw.get("action_type", "tool_call"),
                "toolName": action_raw.get("tool_name"),
                "actionLabel": action_raw.get("action_label", ""),
                "payload": action_raw.get("payload", {}),
                "confidence": action_raw.get("confidence", 0.85),
                "executionMode": "sequential",
                "requiresConfirmation": False,
                "confirmationReason": None,
                "blockingErrors": [],
                "warnings": [],
                "derivedFromTextSpan": request.input_text,
                "mappingActionId": action_raw.get("action_label", ""),
                "engineHooks": action_raw.get("engine_hooks", []),
            })

        needs_clar = tool_result.get("needs_clarification", False)
        clar_q = tool_result.get("clarification_question")

        return RuntimeParserContract(
            contract_version="0.1.0",
            turnId=request.turn_id,
            timestampSimSec=request.timestamp_sim_sec,
            rawInput=request.input_text,
            normalizedInput=request.input_text.lower(),
            parserMode="llm",
            speaker=request.speaker,
            intentSummary=tool_result.get("intent_summary", "LLM parsed"),
            actions=actions,
            needsClarification=needs_clar,
            clarificationQuestion=clar_q if needs_clar else None,
            clarificationTargets=[],
            overallConfidence=0.90 if actions else 0.5,
            parserStatus="clarification_required" if needs_clar else ("ok" if actions else "partial_parse"),
            nonActionableText=[],
            parserNotes=["LLM parser (Claude tool-use)"],
            safetyFlags=[],
        )
