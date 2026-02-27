from __future__ import annotations

import re
from uuid import uuid4

from app.models.parser import ParseTurnRequest, RuntimeParserContract


class ParserService:
    """Very small rule-based parser stub.

    Replace this with the real LLM-backed parser that emits the full runtime parser contract.
    """

    def parse_turn(self, request: ParseTurnRequest) -> RuntimeParserContract:
        text = request.input_text.strip()
        normalized = text.lower()

        actions = []
        needs_clarification = False
        clarification_question = None
        status = "ok"
        notes = ["Rule-based stub parser in use"]

        if not text:
            return RuntimeParserContract(
                contract_version="0.1.0",
                turnId=request.turn_id,
                timestampSimSec=request.timestamp_sim_sec,
                rawInput=request.input_text,
                normalizedInput=normalized,
                parserMode=request.parser_mode,
                speaker=request.speaker,
                intentSummary="No input detected.",
                actions=[],
                needsClarification=True,
                clarificationQuestion="I didn't catch that. What would you like to do?",
                clarificationTargets=[],
                overallConfidence=0.1,
                parserStatus="rejected",
                nonActionableText=[],
                parserNotes=notes,
                safetyFlags=[],
            )

        # Start nicardipine
        if "nicardipine" in normalized or "cardene" in normalized:
            match = re.search(r"(\d+(?:\.\d+)?)", normalized)
            rate = float(match.group(1)) if match else 5.0
            actions.append(
                {
                    "actionUuid": str(uuid4()),
                    "sequenceIndex": len(actions),
                    "actionType": "tool_call",
                    "toolName": "start_infusion",
                    "actionLabel": "start_nicardipine",
                    "payload": {
                        "medication_id": "nicardipine_iv",
                        "infusion_rate": rate,
                        "dose_unit": "mg_per_hour",
                        "route": "IV",
                        "administration_mode": "infusion_start",
                    },
                    "confidence": 0.95,
                    "executionMode": "sequential",
                    "requiresConfirmation": False,
                    "confirmationReason": None,
                    "blockingErrors": [],
                    "warnings": [],
                    "derivedFromTextSpan": text,
                    "mappingActionId": "start_nicardipine",
                    "engineHooks": ["mark_critical_action_start_titratable_iv_agent"],
                }
            )

        # Give labetalol bolus
        if "labetalol" in normalized:
            match = re.search(r"(\d+)", normalized)
            dose = int(match.group(1)) if match else None
            if dose in {10, 20, 40, 80}:
                actions.append(
                    {
                        "actionUuid": str(uuid4()),
                        "sequenceIndex": len(actions),
                        "actionType": "tool_call",
                        "toolName": "give_medication",
                        "actionLabel": "give_labetalol_bolus",
                        "payload": {
                            "medication_id": "labetalol_iv",
                            "dose": dose,
                            "dose_unit": "mg",
                            "route": "IV",
                            "administration_mode": "bolus",
                        },
                        "confidence": 0.95,
                        "executionMode": "sequential",
                        "requiresConfirmation": False,
                        "confirmationReason": None,
                        "blockingErrors": [],
                        "warnings": [],
                        "derivedFromTextSpan": text,
                        "mappingActionId": "give_labetalol_bolus",
                        "engineHooks": ["mark_critical_action_start_titratable_iv_agent_if_no_prior_iv_agent"],
                    }
                )
            elif "labetalol" in normalized:
                needs_clarification = True
                clarification_question = "The simulator currently supports labetalol bolus doses of 10, 20, 40, or 80 mg. Which dose would you like?"
                status = "clarification_required"

        # Order head CT
        if "head ct" in normalized or "ct head" in normalized:
            actions.append(
                {
                    "actionUuid": str(uuid4()),
                    "sequenceIndex": len(actions),
                    "actionType": "tool_call",
                    "toolName": "order_diagnostic",
                    "actionLabel": "order_head_ct",
                    "payload": {
                        "diagnostic_id": "head_ct_noncontrast",
                        "order_type": "imaging",
                        "priority": "urgent",
                    },
                    "confidence": 0.98,
                    "executionMode": "parallel_safe",
                    "requiresConfirmation": False,
                    "confirmationReason": None,
                    "blockingErrors": [],
                    "warnings": [],
                    "derivedFromTextSpan": text,
                    "mappingActionId": "order_head_ct",
                    "engineHooks": ["mark_critical_action_order_neuro_workup"],
                }
            )

        # Monitoring
        if "telemetry" in normalized or "monitor" in normalized:
            actions.append(
                {
                    "actionUuid": str(uuid4()),
                    "sequenceIndex": len(actions),
                    "actionType": "tool_call",
                    "toolName": "set_monitoring",
                    "actionLabel": "set_monitoring_continuous",
                    "payload": {
                        "monitor_action": "enable_continuous_monitoring",
                        "telemetry": True,
                        "pulse_ox": True,
                    },
                    "confidence": 0.9,
                    "executionMode": "parallel_safe",
                    "requiresConfirmation": False,
                    "confirmationReason": None,
                    "blockingErrors": [],
                    "warnings": [],
                    "derivedFromTextSpan": text,
                    "mappingActionId": "set_monitoring_continuous",
                    "engineHooks": ["mark_critical_action_establish_monitoring"],
                }
            )

        if "every 5" in normalized or "q5" in normalized:
            actions.append(
                {
                    "actionUuid": str(uuid4()),
                    "sequenceIndex": len(actions),
                    "actionType": "tool_call",
                    "toolName": "set_monitoring",
                    "actionLabel": "set_repeat_bp_q5min",
                    "payload": {
                        "monitor_action": "set_nibp_cycle",
                        "nibp_cycle_sec": 300,
                    },
                    "confidence": 0.92,
                    "executionMode": "parallel_safe",
                    "requiresConfirmation": False,
                    "confirmationReason": None,
                    "blockingErrors": [],
                    "warnings": [],
                    "derivedFromTextSpan": text,
                    "mappingActionId": "set_repeat_bp_q5min",
                    "engineHooks": ["mark_critical_action_establish_monitoring"],
                }
            )

        # Assessment
        if "hypertensive emergency" in normalized or "hypertensive encephalopathy" in normalized:
            actions.append(
                {
                    "actionUuid": str(uuid4()),
                    "sequenceIndex": len(actions),
                    "actionType": "tool_call",
                    "toolName": "document_assessment",
                    "actionLabel": "document_hypertensive_emergency_assessment",
                    "payload": {
                        "assessment_concept": "hypertensive_emergency_or_hypertensive_encephalopathy",
                        "certainty": 0.95,
                    },
                    "confidence": 0.94,
                    "executionMode": "parallel_safe",
                    "requiresConfirmation": False,
                    "confirmationReason": None,
                    "blockingErrors": [],
                    "warnings": [],
                    "derivedFromTextSpan": text,
                    "mappingActionId": "document_hypertensive_emergency_assessment",
                    "engineHooks": ["mark_critical_action_recognize_htn_emergency"],
                }
            )

        # Disposition
        if "icu" in normalized:
            actions.append(
                {
                    "actionUuid": str(uuid4()),
                    "sequenceIndex": len(actions),
                    "actionType": "tool_call",
                    "toolName": "set_disposition",
                    "actionLabel": "admit_icu",
                    "payload": {
                        "disposition": "icu_admission",
                        "reason": "hypertensive emergency with neurologic dysfunction",
                    },
                    "confidence": 0.93,
                    "executionMode": "parallel_safe",
                    "requiresConfirmation": False,
                    "confirmationReason": None,
                    "blockingErrors": [],
                    "warnings": [],
                    "derivedFromTextSpan": text,
                    "mappingActionId": "admit_icu",
                    "engineHooks": ["mark_critical_action_disposition"],
                }
            )

        if not actions and status == "ok":
            status = "partial_parse"
            notes.append("No supported action detected from input.")

        return RuntimeParserContract(
            contract_version="0.1.0",
            turnId=request.turn_id,
            timestampSimSec=request.timestamp_sim_sec,
            rawInput=request.input_text,
            normalizedInput=normalized,
            parserMode=request.parser_mode,
            speaker=request.speaker,
            intentSummary="Rule-based parser result",
            actions=actions,
            needsClarification=needs_clarification,
            clarificationQuestion=clarification_question,
            clarificationTargets=[],
            overallConfidence=0.95 if actions else 0.4,
            parserStatus=status,
            nonActionableText=[],
            parserNotes=notes,
            safetyFlags=[],
        )
