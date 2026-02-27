from __future__ import annotations

import re
from uuid import uuid4

from app.models.parser import ParseTurnRequest, RuntimeParserContract

# ---------------------------------------------------------------------------
# Medication vocabulary
# ---------------------------------------------------------------------------

# lowercase name → internal medication_id
# Kept longest-first so multi-word aliases ("nitro drip") match before substrings ("nitro")
_MED_ID: dict[str, str] = {
    "nitro drip": "nitroglycerin_iv",
    "nicardipine": "nicardipine_iv",
    "cardene": "nicardipine_iv",
    "clevidipine": "clevidipine_iv",
    "cleviprex": "clevidipine_iv",
    "labetalol": "labetalol_iv",
    "trandate": "labetalol_iv",
    "esmolol": "esmolol_iv",
    "brevibloc": "esmolol_iv",
    "nitroglycerin": "nitroglycerin_iv",
    "nitroprusside": "nitroprusside_iv",
    "nipride": "nitroprusside_iv",
    "hydralazine": "hydralazine_iv",
    "apresoline": "hydralazine_iv",
}
_MED_NAMES = sorted(_MED_ID, key=len, reverse=True)

# Default infusion rate (mg/hr or primary unit) when no rate is specified
_DEFAULT_RATE: dict[str, float] = {
    "nicardipine_iv": 5.0,
    "clevidipine_iv": 1.0,
    "labetalol_iv": 2.0,
    "esmolol_iv": 50.0,
    "nitroglycerin_iv": 20.0,
    "nitroprusside_iv": 0.3,
    "hydralazine_iv": 10.0,
}

# Medications whose primary route is continuous infusion
_INFUSION_PREFERRED = {
    "nicardipine_iv",
    "clevidipine_iv",
    "esmolol_iv",
    "nitroglycerin_iv",
    "nitroprusside_iv",
}

# Medications whose primary route is IV bolus (may also be used as infusion with "drip")
_BOLUS_PREFERRED = {"labetalol_iv", "hydralazine_iv"}

# Verbs that indicate starting an infusion
_START_RE = re.compile(r"\b(start|begin|initiate|hang|run|get|start up)\b")

# Verbs that indicate adjusting an infusion
_ADJUST_RE = re.compile(
    r"\b(increase|decrease|reduce|lower|raise|titrate|adjust|change|"
    r"uptitrate|bump up|slow down|turn up|turn down|up to|down to)\b"
)

# Verbs that indicate stopping an infusion
_STOP_RE = re.compile(r"\b(stop|discontinue|hold|turn off|d/c|wean off|pull|off)\b")

# Verbs that indicate giving a bolus
_BOLUS_RE = re.compile(r"\b(give|push|administer|inject|bolus)\b")

# ---------------------------------------------------------------------------
# Diagnostic vocabulary  (regex, diagnostic_id, order_type)
# ---------------------------------------------------------------------------

_DIAGNOSTICS: list[tuple[str, str, str]] = [
    (r"\bct\b.*\bhead\b|\bhead\b.*\bct\b|non.?contrast\s+ct|\bncct\b", "head_ct_noncontrast", "imaging"),
    (r"\bmri(?:\s+(?:brain|head))?\b|brain\s+mri", "mri_brain", "imaging"),
    (r"\b(?:ecg|ekg|twelve.?lead|electrocardiogram)\b", "ecg", "diagnostic"),
    (r"\bcmp\b|\bbmp\b|comprehensive\s+metabolic|basic\s+metabolic|\belectrolytes\b|chem\s*(?:7|panel)", "cmp", "lab"),
    (r"\btroponin\b|\btrop\b", "troponin", "lab"),
    (r"pregnancy\s+test|urine\s+preg|beta.?hcg|\bhcg\b", "pregnancy_test", "lab"),
    (r"\bua\b|urinalysis|urine\s+(?:analysis|culture)", "urinalysis", "lab"),
    (r"\bbnp\b|nt.?probnp|brain\s+natriuretic", "bnp", "lab"),
    (r"\bcbc\b|complete\s+blood\s+count", "cbc", "lab"),
]

# Verb context required for most diagnostics (imaging keywords bypass this)
_ORDER_RE = re.compile(r"\b(order|get|obtain|send|check|draw|request|do|run)\b")
_IMAGING_BYPASS = re.compile(r"\b(ct|mri|scan|ecg|ekg)\b")

# ---------------------------------------------------------------------------
# Assessment vocabulary  (regex, concept_id)
# ---------------------------------------------------------------------------

_ASSESSMENTS: list[tuple[str, str]] = [
    (
        r"hypertensive\s+emergency|htn\s+emergency|hypertensive\s+encephalopathy|"
        r"htn\s+enceph|hypertensive\s+crisis|htn\s+crisis",
        "hypertensive_emergency_or_hypertensive_encephalopathy",
    ),
    (r"\bpres\b|posterior\s+reversible", "pres_syndrome"),
    (r"hypertensive\s+urgency|htn\s+urgency", "hypertensive_urgency"),
]

# ---------------------------------------------------------------------------
# Disposition vocabulary  (regex, disposition_id)
# ---------------------------------------------------------------------------

_DISPOSITIONS: list[tuple[str, str]] = [
    (r"\bicu\b|intensive\s+care\s+unit|intensive\s+care(?!\s+unit)|critical\s+care", "icu_admission"),
    (r"\bfloor\b|med(?:ical)?\s+(?:floor|ward)|step.?down(?!\s+icu)", "floor_admission"),
    (r"\bdischarge\b|send\s+(?:her|him|them)?\s*home", "discharge"),
    (r"\bobservation\b|\bobs\b(?!\s+unit)", "observation"),
]

# ---------------------------------------------------------------------------
# NIBP interval vocabulary  (regex, interval_seconds)
# ---------------------------------------------------------------------------

_NIBP_INTERVALS: list[tuple[str, int]] = [
    (r"(?:every|q)\s*2\s*min|q2(?:min)?(?!\d)", 120),
    (r"(?:every|q)\s*5\s*min|q5(?:min)?(?!\d)", 300),
    (r"(?:every|q)\s*10\s*min|q10(?:min)?(?!\d)", 600),
    (r"(?:every|q)\s*15\s*min|q15(?:min)?(?!\d)", 900),
    (r"(?:every|q)\s*30\s*min|q30(?:min)?(?!\d)", 1800),
    (r"\bcontinuous\s+(?:bp|blood\s+pressure)", 60),
]


def _drip_keyword(text: str) -> bool:
    """True if text contains a keyword indicating a continuous infusion."""
    return bool(re.search(r"\b(drip|infusion|gtt|continuous|infusing)\b", text))


class ParserService:
    """Deterministic rule-based parser for the hypertensive encephalopathy case family.

    Covers all actions a resident trainee would take:
    - IV antihypertensive management (start / adjust / stop / bolus)
    - Diagnostic ordering (CT, MRI, ECG, labs)
    - Monitoring setup (telemetry, NIBP intervals)
    - Clinical assessment documentation
    - Patient disposition
    - Neurological/hemodynamic reassessment

    Ambiguous inputs (e.g. "stop infusion" with multiple active drips) return
    clarification_required so the UI can prompt the user.
    """

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse_turn(self, request: ParseTurnRequest) -> RuntimeParserContract:
        text = request.input_text.strip()
        normalized = text.lower()

        if not text:
            return self._empty_response(request, normalized)

        actions: list[dict] = []
        needs_clarification = False
        clarification_question: str | None = None
        status = "ok"
        notes: list[str] = ["Rule-based parser v2"]

        # ---- medication intents (order matters: stop > adjust > start > bolus) ----
        stop_actions = self._match_stop_infusion(normalized, text, request.active_infusions)
        actions.extend(stop_actions)

        if not stop_actions:
            actions.extend(self._match_infusion_adjust(normalized, text))
            actions.extend(self._match_infusion_start(normalized, text))
            bolus_actions, bolus_clar, bolus_q = self._match_bolus(normalized, text)
            actions.extend(bolus_actions)
            if bolus_clar:
                needs_clarification = True
                clarification_question = bolus_q
                status = "clarification_required"

        # Ambiguous stop: stop verb present, no med named, >1 active infusion
        if not stop_actions and self._is_ambiguous_stop(normalized, request.active_infusions):
            needs_clarification = True
            names = ", ".join(
                i.get("medication_id", "?").replace("_iv", "") for i in request.active_infusions
            )
            clarification_question = f"Which infusion would you like to stop? Active: {names}."
            status = "clarification_required"

        # ---- non-medication intents (order-independent) ----
        actions.extend(self._match_diagnostics(normalized, text))
        actions.extend(self._match_monitoring(normalized, text))
        actions.extend(self._match_assessment(normalized, text))
        actions.extend(self._match_disposition(normalized, text))
        actions.extend(self._match_reassessment(normalized, text))

        # Re-number sequence indices
        for i, a in enumerate(actions):
            a["sequenceIndex"] = i

        if not actions and not needs_clarification and status == "ok":
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
            overallConfidence=0.95 if actions else (0.5 if needs_clarification else 0.3),
            parserStatus=status,
            nonActionableText=[],
            parserNotes=notes,
            safetyFlags=[],
        )

    # ------------------------------------------------------------------
    # Intent: start infusion
    # ------------------------------------------------------------------

    def _match_infusion_start(self, normalized: str, raw: str) -> list[dict]:
        """Detect 'start/begin/initiate [med] [at rate]'."""
        med_id, med_name = self._detect_med(normalized)
        if med_id is None:
            return []
        # Bolus-preferred meds only qualify here when "drip/infusion" keyword present
        if med_id in _BOLUS_PREFERRED and not _drip_keyword(normalized):
            return []
        # Require a start verb unless medication is infusion-primary (standalone mention)
        if not (_START_RE.search(normalized) or med_id in _INFUSION_PREFERRED):
            return []
        # Yield to stop/adjust handlers
        if _STOP_RE.search(normalized) or _ADJUST_RE.search(normalized):
            return []
        rate = self._extract_rate(normalized) or _DEFAULT_RATE.get(med_id, 5.0)
        label = f"start_{med_name.replace(' ', '_')}"
        hooks: list[str] = []
        if med_id in {"nicardipine_iv", "clevidipine_iv", "labetalol_iv"}:
            hooks.append("mark_critical_action_start_titratable_iv_agent")
        return [
            self._action(
                tool_name="start_infusion",
                action_label=label,
                payload={
                    "medication_id": med_id,
                    "infusion_rate": rate,
                    "dose_unit": "mg_per_hour",
                    "route": "IV",
                    "administration_mode": "infusion_start",
                },
                raw=raw,
                confidence=0.95,
                execution_mode="sequential",
                mapping_action_id=label,
                engine_hooks=hooks,
            )
        ]

    # ------------------------------------------------------------------
    # Intent: adjust infusion
    # ------------------------------------------------------------------

    def _match_infusion_adjust(self, normalized: str, raw: str) -> list[dict]:
        """Detect 'increase/decrease/titrate [med] to [rate]'."""
        if not _ADJUST_RE.search(normalized):
            return []
        med_id, med_name = self._detect_med(normalized)
        if med_id is None:
            return []
        rate = self._extract_rate(normalized)
        if rate is None:
            return []  # directional without a target rate is not actionable
        label = f"adjust_{med_name.replace(' ', '_')}"
        return [
            self._action(
                tool_name="adjust_infusion",
                action_label=label,
                payload={
                    "medication_id": med_id,
                    "new_infusion_rate": rate,
                    "dose_unit": "mg_per_hour",
                    "route": "IV",
                },
                raw=raw,
                confidence=0.92,
                execution_mode="sequential",
                mapping_action_id=label,
                engine_hooks=[],
            )
        ]

    # ------------------------------------------------------------------
    # Intent: stop infusion
    # ------------------------------------------------------------------

    def _match_stop_infusion(
        self, normalized: str, raw: str, active_infusions: list[dict]
    ) -> list[dict]:
        """Detect 'stop/hold/discontinue [med]'. Auto-disambiguates when one infusion active."""
        if not _STOP_RE.search(normalized):
            return []
        med_id, med_name = self._detect_med(normalized)
        if med_id is not None:
            label = f"stop_{med_name.replace(' ', '_')}"
            return [
                self._action(
                    tool_name="stop_infusion",
                    action_label=label,
                    payload={"medication_id": med_id, "route": "IV"},
                    raw=raw,
                    confidence=0.95,
                    execution_mode="sequential",
                    mapping_action_id=label,
                    engine_hooks=[],
                )
            ]
        # Auto-disambiguate when exactly one infusion is running
        if len(active_infusions) == 1:
            only_id = active_infusions[0].get("medication_id", "unknown_iv")
            label = f"stop_{only_id.replace('_iv', '')}"
            return [
                self._action(
                    tool_name="stop_infusion",
                    action_label=label,
                    payload={"medication_id": only_id, "route": "IV"},
                    raw=raw,
                    confidence=0.80,
                    execution_mode="sequential",
                    mapping_action_id=label,
                    engine_hooks=[],
                )
            ]
        return []  # let ambiguity detection in parse_turn handle >1 case

    def _is_ambiguous_stop(self, normalized: str, active_infusions: list[dict]) -> bool:
        if not _STOP_RE.search(normalized):
            return False
        med_id, _ = self._detect_med(normalized)
        if med_id is not None:
            return False
        return len(active_infusions) > 1

    # ------------------------------------------------------------------
    # Intent: give bolus
    # ------------------------------------------------------------------

    def _match_bolus(
        self, normalized: str, raw: str
    ) -> tuple[list[dict], bool, str | None]:
        """Detect 'give/push/administer [med] [dose] mg'.

        Returns (actions, needs_clarification, clarification_question).
        """
        med_id, med_name = self._detect_med(normalized)
        if med_id is None or med_id not in _BOLUS_PREFERRED:
            return [], False, None
        if _drip_keyword(normalized):
            return [], False, None  # defer to start_infusion
        if not _BOLUS_RE.search(normalized):
            return [], False, None
        dose = self._extract_dose(normalized)
        if dose is None:
            return (
                [],
                True,
                f"What dose of {med_name} would you like to give? (e.g., 20 mg IV)",
            )
        label = f"give_{med_name.replace(' ', '_')}_bolus"
        hooks = (
            ["mark_critical_action_start_titratable_iv_agent_if_no_prior_iv_agent"]
            if med_id == "labetalol_iv"
            else []
        )
        return (
            [
                self._action(
                    tool_name="give_medication",
                    action_label=label,
                    payload={
                        "medication_id": med_id,
                        "dose": dose,
                        "dose_unit": "mg",
                        "route": "IV",
                        "administration_mode": "bolus",
                    },
                    raw=raw,
                    confidence=0.95,
                    execution_mode="sequential",
                    mapping_action_id=label,
                    engine_hooks=hooks,
                )
            ],
            False,
            None,
        )

    # ------------------------------------------------------------------
    # Intent: order diagnostics
    # ------------------------------------------------------------------

    def _match_diagnostics(self, normalized: str, raw: str) -> list[dict]:
        actions: list[dict] = []
        has_order_verb = bool(_ORDER_RE.search(normalized))
        has_imaging_bypass = bool(_IMAGING_BYPASS.search(normalized))
        for pattern, diag_id, order_type in _DIAGNOSTICS:
            if not re.search(pattern, normalized):
                continue
            if not has_order_verb and not has_imaging_bypass:
                continue
            hooks: list[str] = []
            if diag_id in {"head_ct_noncontrast", "mri_brain"}:
                hooks.append("mark_critical_action_order_neuro_workup")
            label = f"order_{diag_id}"
            actions.append(
                self._action(
                    tool_name="order_diagnostic",
                    action_label=label,
                    payload={
                        "diagnostic_id": diag_id,
                        "order_type": order_type,
                        "priority": "urgent" if order_type == "imaging" else "routine",
                    },
                    raw=raw,
                    confidence=0.97,
                    execution_mode="parallel_safe",
                    mapping_action_id=label,
                    engine_hooks=hooks,
                )
            )
        return actions

    # ------------------------------------------------------------------
    # Intent: set monitoring
    # ------------------------------------------------------------------

    def _match_monitoring(self, normalized: str, raw: str) -> list[dict]:
        actions: list[dict] = []
        if re.search(
            r"\b(telemetry|continuous\s+monitor(?:ing)?|cardiac\s+monitor(?:ing)?|"
            r"put\s+(?:her|him|them)\s+on\s+(?:the\s+)?monitor|on\s+telemetry)\b",
            normalized,
        ):
            actions.append(
                self._action(
                    tool_name="set_monitoring",
                    action_label="enable_continuous_monitoring",
                    payload={
                        "monitor_action": "enable_continuous_monitoring",
                        "telemetry": True,
                        "pulse_ox": True,
                    },
                    raw=raw,
                    confidence=0.92,
                    execution_mode="parallel_safe",
                    mapping_action_id="enable_continuous_monitoring",
                    engine_hooks=["mark_critical_action_establish_monitoring"],
                )
            )
        nibp_sec = self._extract_nibp_interval(normalized)
        if nibp_sec:
            label = f"set_nibp_q{nibp_sec // 60}min"
            actions.append(
                self._action(
                    tool_name="set_monitoring",
                    action_label=label,
                    payload={
                        "monitor_action": "set_nibp_cycle",
                        "nibp_cycle_sec": nibp_sec,
                    },
                    raw=raw,
                    confidence=0.93,
                    execution_mode="parallel_safe",
                    mapping_action_id=label,
                    engine_hooks=["mark_critical_action_establish_monitoring"],
                )
            )
        return actions

    # ------------------------------------------------------------------
    # Intent: document clinical assessment
    # ------------------------------------------------------------------

    def _match_assessment(self, normalized: str, raw: str) -> list[dict]:
        actions: list[dict] = []
        for pattern, concept in _ASSESSMENTS:
            if re.search(pattern, normalized):
                label = f"document_{concept[:40]}"
                actions.append(
                    self._action(
                        tool_name="document_assessment",
                        action_label=label,
                        payload={"assessment_concept": concept, "certainty": 0.95},
                        raw=raw,
                        confidence=0.94,
                        execution_mode="parallel_safe",
                        mapping_action_id=label,
                        engine_hooks=["mark_critical_action_recognize_htn_emergency"],
                    )
                )
        return actions

    # ------------------------------------------------------------------
    # Intent: patient disposition
    # ------------------------------------------------------------------

    def _match_disposition(self, normalized: str, raw: str) -> list[dict]:
        for pattern, disposition in _DISPOSITIONS:
            if re.search(pattern, normalized):
                label = f"set_disposition_{disposition}"
                return [
                    self._action(
                        tool_name="set_disposition",
                        action_label=label,
                        payload={
                            "disposition": disposition,
                            "reason": "hypertensive emergency with neurologic dysfunction",
                        },
                        raw=raw,
                        confidence=0.93,
                        execution_mode="parallel_safe",
                        mapping_action_id=label,
                        engine_hooks=["mark_critical_action_disposition"],
                    )
                ]
        return []

    # ------------------------------------------------------------------
    # Intent: reassess patient
    # ------------------------------------------------------------------

    def _match_reassessment(self, normalized: str, raw: str) -> list[dict]:
        if not re.search(r"\b(reassess|reassessment|re-assess|recheck|re-evaluate)\b", normalized):
            return []
        actions: list[dict] = []
        for rtype in ("neurologic_reassessment", "hemodynamic_reassessment"):
            actions.append(
                self._action(
                    tool_name="perform_reassessment",
                    action_label=f"perform_{rtype}",
                    payload={"reassessment_type": rtype},
                    raw=raw,
                    confidence=0.90,
                    execution_mode="sequential",
                    mapping_action_id=f"perform_{rtype}",
                    engine_hooks=["mark_critical_action_reassess_neuro_status"],
                )
            )
        return actions

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_med(normalized: str) -> tuple[str | None, str]:
        """Return (med_id, matched_name) or (None, '') if no medication found."""
        for name in _MED_NAMES:
            if name in normalized:
                return _MED_ID[name], name
        return None, ""

    @staticmethod
    def _extract_rate(text: str) -> float | None:
        """Extract infusion rate; returns mg/hr equivalent (or raw value for mcg units)."""
        # "X mg/hr" or "X mg per hour"
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg\s*(?:per\s+)?/?h(?:r|our)?", text)
        if m:
            return float(m.group(1))
        # "at X" or "to X" (optionally followed by mg)
        m = re.search(r"(?:at|to)\s+(\d+(?:\.\d+)?)\s*(?:mg)?", text)
        if m:
            return float(m.group(1))
        # "X mg" bare (e.g., "nicardipine 5 mg")
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", text)
        if m:
            return float(m.group(1))
        return None

    @staticmethod
    def _extract_dose(text: str) -> float | None:
        """Extract a bolus dose in mg."""
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", text)
        if m:
            return float(m.group(1))
        # bare integer as last resort
        m = re.search(r"\b(\d+)\b", text)
        if m:
            return float(m.group(1))
        return None

    @staticmethod
    def _extract_nibp_interval(text: str) -> int | None:
        for pattern, sec in _NIBP_INTERVALS:
            if re.search(pattern, text):
                return sec
        # generic "BP every X minutes"
        m = re.search(
            r"(?:bp|blood\s+pressure|cuff)\s+(?:check\s+)?every\s+(\d+)\s*(?:min|minute)", text
        )
        if m:
            return int(m.group(1)) * 60
        return None

    def _action(
        self,
        *,
        tool_name: str,
        action_label: str,
        payload: dict,
        raw: str,
        confidence: float = 0.90,
        execution_mode: str = "sequential",
        mapping_action_id: str = "",
        engine_hooks: list[str] | None = None,
    ) -> dict:
        return {
            "actionUuid": str(uuid4()),
            "sequenceIndex": 0,  # re-numbered by caller
            "actionType": "tool_call",
            "toolName": tool_name,
            "actionLabel": action_label,
            "payload": payload,
            "confidence": confidence,
            "executionMode": execution_mode,
            "requiresConfirmation": False,
            "confirmationReason": None,
            "blockingErrors": [],
            "warnings": [],
            "derivedFromTextSpan": raw,
            "mappingActionId": mapping_action_id,
            "engineHooks": engine_hooks or [],
        }

    def _empty_response(self, request: ParseTurnRequest, normalized: str) -> RuntimeParserContract:
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
            parserNotes=["Rule-based parser v2"],
            safetyFlags=[],
        )
