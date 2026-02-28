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
    # Antihypertensives (infusions)
    "nitro drip": "nitroglycerin_iv",
    "nicardipine": "nicardipine_iv",
    "cardene": "nicardipine_iv",
    "clevidipine": "clevidipine_iv",
    "cleviprex": "clevidipine_iv",
    "nitroglycerin": "nitroglycerin_iv",
    "nitroprusside": "nitroprusside_iv",
    "nipride": "nitroprusside_iv",
    # Antihypertensives (bolus-preferred)
    "labetalol": "labetalol_iv",
    "trandate": "labetalol_iv",
    "hydralazine": "hydralazine_iv",
    "apresoline": "hydralazine_iv",
    # Vasopressors / inotropes
    "norepinephrine": "norepinephrine_iv",
    "neosynephrine": "phenylephrine_iv",
    "neosynephrine drip": "phenylephrine_iv",
    "epinephrine": "epinephrine_iv",
    "phenylephrine": "phenylephrine_iv",
    "levophed": "norepinephrine_iv",
    "dopamine": "dopamine_iv",
    "dobutamine": "dobutamine_iv",
    "vasopressin": "vasopressin_iv",
    "norepi": "norepinephrine_iv",
    "epi drip": "epinephrine_iv",
    "neo drip": "phenylephrine_iv",
    "levo": "norepinephrine_iv",
}
_MED_NAMES = sorted(_MED_ID, key=len, reverse=True)

# Default infusion rate when no rate is specified
_DEFAULT_RATE: dict[str, float] = {
    "nicardipine_iv": 5.0,
    "clevidipine_iv": 1.0,
    "labetalol_iv": 2.0,
    "esmolol_iv": 50.0,
    "nitroglycerin_iv": 20.0,
    "nitroprusside_iv": 0.3,
    "hydralazine_iv": 10.0,
    "norepinephrine_iv": 0.1,
    "epinephrine_iv": 0.05,
    "phenylephrine_iv": 0.5,
    "dopamine_iv": 5.0,
    "dobutamine_iv": 5.0,
    "vasopressin_iv": 0.03,
}

# Medications whose primary route is continuous infusion
_INFUSION_PREFERRED = {
    "nicardipine_iv",
    "clevidipine_iv",
    "esmolol_iv",
    "nitroglycerin_iv",
    "nitroprusside_iv",
    "norepinephrine_iv",
    "epinephrine_iv",
    "dopamine_iv",
    "dobutamine_iv",
    "vasopressin_iv",
}

# Medications whose primary route is IV bolus
_BOLUS_PREFERRED = {"labetalol_iv", "hydralazine_iv", "phenylephrine_iv"}

# Known-safe max bolus doses (mg) — above this triggers unsafe flag
_UNSAFE_BOLUS_DOSE_MG: dict[str, float] = {
    "phenylephrine_iv": 5.0,     # phenylephrine push is in mcg; >5mg almost certainly a unit error
    "labetalol_iv": 200.0,
    "hydralazine_iv": 40.0,
}

_START_RE = re.compile(r"\b(start|begin|initiate|hang|run|get|start up|give|administer)\b")
_ADJUST_RE = re.compile(
    r"\b(increase|decrease|reduce|lower|raise|titrate|adjust|change|"
    r"uptitrate|bump up|slow down|turn up|turn down|up to|down to)\b"
)
_STOP_RE = re.compile(r"\b(stop|discontinue|hold|turn off|d/c|wean off|pull|off)\b")
_BOLUS_RE = re.compile(r"\b(give|push|administer|inject|bolus|iv push|ivp)\b")

# ---------------------------------------------------------------------------
# Diagnostic vocabulary
# ---------------------------------------------------------------------------

_DIAGNOSTICS: list[tuple[str, str, str]] = [
    (r"\bct\b.*\bhead\b|\bhead\b.*\bct\b|non.?contrast\s+ct|\bncct\b|head\s+ct|ct\s+head", "head_ct_noncontrast", "imaging"),
    (r"\bmri(?:\s+(?:brain|head))?\b|brain\s+mri", "mri_brain", "imaging"),
    (r"\b(?:ecg|ekg|twelve.?lead|12.?lead|electrocardiogram)\b", "ecg", "diagnostic"),
    (r"\bcmp\b|\bbmp\b|comprehensive\s+metabolic|basic\s+metabolic|\belectrolytes\b|chem\s*(?:7|panel)", "cmp", "lab"),
    (r"\btroponin\b|\btrop\b", "troponin", "lab"),
    (r"pregnancy\s+test|urine\s+preg|beta.?hcg|\bhcg\b|urine\s+hcg", "pregnancy_test", "lab"),
    (r"\bua\b|urinalysis|urine\s+(?:analysis|culture)", "urinalysis", "lab"),
    (r"\bbnp\b|nt.?probnp|brain\s+natriuretic", "bnp", "lab"),
    (r"\bcbc\b|complete\s+blood\s+count", "cbc", "lab"),
    (r"\bcoags?\b|coagulation\s+(?:panel|studies?|study)|coag\s+(?:panel|study)|pt\s+ptt|ptt\s+inr", "coagulation_panel", "lab"),
    (r"\bfingerstick\b|\bfsbg?\b|\bfsbs?\b|finger\s+stick|point\s+of\s+care\s+glucose|poc\s+glucose", "fingerstick_glucose", "lab"),
    (r"\bchest\s+(?:x.?ray|xr|cxr)\b|\bcxr\b|\bchest\s+film\b", "chest_xray", "imaging"),
    (r"\bd.?dimer\b", "d_dimer", "lab"),
    (r"\blactic?\s+acid\b|\blactate\b", "lactate", "lab"),
]

# Order verb (for labs) and imaging/common-lab bypass patterns
_ORDER_RE = re.compile(r"\b(order|get|obtain|send|check|draw|request|do|run|stat)\b")
# Labs and imaging that can be recognized without an explicit order verb
_LAB_BYPASS = re.compile(
    r"\b(cbc|bmp|cmp|coags?|troponin|trop|ua\b|hcg|ecg|ekg|ct|mri|scan|labs?|"
    r"fingerstick|fsbg|bnp|d.?dimer|lactate|lactic|cxr|x.?ray|xray)\b"
)

# ---------------------------------------------------------------------------
# Assessment vocabulary
# ---------------------------------------------------------------------------

_ASSESSMENTS: list[tuple[str, str]] = [
    (
        r"hypertensive\s+emergency|htn\s+emergency|hypertensive\s+encephalopathy|"
        r"htn\s+enceph|hypertensive\s+crisis|htn\s+crisis",
        "hypertensive_emergency_or_hypertensive_encephalopathy",
    ),
    (r"\bpres\b|posterior\s+reversible", "pres_syndrome"),
    (r"hypertensive\s+urgency|htn\s+urgency", "hypertensive_urgency"),
    (r"ischemic\s+stroke|cva\b|cerebrovascular", "ischemic_stroke"),
    (r"hemorrhagic\s+stroke|ich\b|intracranial\s+hemorrhage", "hemorrhagic_stroke"),
]

# ---------------------------------------------------------------------------
# Disposition vocabulary
# ---------------------------------------------------------------------------

_DISPOSITIONS: list[tuple[str, str]] = [
    (r"\bicu\b|intensive\s+care\s+unit|intensive\s+care(?!\s+unit)|critical\s+care", "icu_admission"),
    (r"\bfloor\b|med(?:ical)?\s+(?:floor|ward)|step.?down(?!\s+icu)", "floor_admission"),
    (r"\bdischarge\b|send\s+(?:her|him|them)?\s*home", "discharge"),
    (r"\bobservation\b|\bobs\b(?!\s+unit)", "observation"),
]

# ---------------------------------------------------------------------------
# NIBP interval vocabulary
# ---------------------------------------------------------------------------

_NIBP_INTERVALS: list[tuple[str, int]] = [
    (r"(?:every|q)\s*2\s*min|q2(?:min)?(?!\d)", 120),
    (r"(?:every|q)\s*5\s*min|q5(?:min)?(?!\d)", 300),
    (r"(?:every|q)\s*10\s*min|q10(?:min)?(?!\d)", 600),
    (r"(?:every|q)\s*15\s*min|q15(?:min)?(?!\d)", 900),
    (r"(?:every|q)\s*30\s*min|q30(?:min)?(?!\d)", 1800),
    (r"\bcontinuous\s+(?:bp|blood\s+pressure)", 60),
]

# ---------------------------------------------------------------------------
# Supportive care vocabulary
# ---------------------------------------------------------------------------

_O2_RE = re.compile(
    r"\b(o2|oxygen|supplemental\s+o2|nasal\s+cannula|non.?rebreather|high.?flow\s+o2|"
    r"nc\b|nrb\b|face\s+mask|blow.?by)\b"
)
_IV_ACCESS_RE = re.compile(
    r"\biv\s+access\b|\biv\s+line\b|\bperipheral\s+iv\b|\bpiv\b|\biv\s+(?:x\s*\d+|start|establish)\b|"
    r"\bplace\s+iv\b|\baccess\s+x\s*\d+\b|\blarge\s+bore\b"
)
_FOLEY_RE = re.compile(r"\bfole(?:y)?\b|\burinary\s+catheter\b|\bfoley\s+catheter\b|\bfoley\s+cath\b|\bfole\s+catheter\b")
_IV_FLUID_RE = re.compile(
    r"\biv\s+fluid|\bfluids?\b(?:\s+(?:bolus|wide\s+open|wob|running|open))?"
    r"|\bnormal\s+saline\b|\bns\b(?!\w)|\blactated\s+ringer|\blr\b(?!\w)"
    r"|\bisotonic\b|\bns\s+bolus\b|\bfluid\s+bolus\b"
)
_HELP_RE = re.compile(r"^\s*(?:help|hint|guidance|what\s+(?:do\s+i\s+do|should\s+i\s+do|next)|"
                       r"assist(?:ance)?|confused|stuck|not\s+sure)\s*\??$")

# Rate / status query — read-only, must not trigger action handlers
# Matches "what is the nicardipine rate", "what is the current epi drip rate", etc.
_RATE_QUERY_RE = re.compile(
    r"\b(?:what(?:'?s|\s+is)\s+(?:the\s+)?(?:current\s+)?(?:\w+\s+){0,3}(?:rate|dose|drip\s+rate|infusion\s+rate)|"
    r"how\s+fast\s+(?:is\s+the|are\s+we\s+running)\s|"
    r"what\s+(?:dose|rate)\s+(?:is|are)\s+(?:the|my|we)|"
    r"(?:check|tell\s+me)\s+(?:the\s+)?(?:current\s+)?(?:drip|infusion)\s+rate|"
    r"what(?:'?s|\s+is)\s+(?:running|infusing))\b"
)

# RSI / intubation — not modeled in this sim
_RSI_RE = re.compile(
    r"\b(?:rsi|rapid\s+sequence|intubat(?:e|ion)|intubating|"
    r"oral\s+tracheal\s+intubation|orotracheal|nasotracheal|"
    r"succinylcholine|suxamethonium|ketamine\s+for\s+rsi|"
    r"rocuronium|etomidate|place(?:ment)?\s+of\s+(?:ett|endotracheal\s+tube)|"
    r"endotracheal|ett\b|(?:bag\s+)?valve\s+mask\b|bvm\b)\b"
)

# Retrieve prior diagnostic result
_RETRIEVE_RESULT_RE = re.compile(
    r"\b(?:what\s+(?:is|are|were|did|was)\s+(?:the\s+)?(?:results?|findings?)|"
    r"(?:show|tell|give)\s+me\s+(?:the\s+)?(?:results?|findings?)|"
    r"what\s+did\s+(?:the\s+)?(?:ct|mri|ecg|ekg|labs?|cbc|bmp|cmp|troponin|echo)\s+(?:show|reveal|find)|"
    r"results?\s+of\s+(?:the\s+)?(?:ct|mri|ecg|ekg|labs?|cbc|bmp|cmp)|"
    r"(?:ct|mri|ecg|ekg|cbc|bmp|cmp|troponin)\s+results?\b)\b"
)

# Clinical / educational query
_CLINICAL_QUERY_RE = re.compile(
    r"\b(?:what\s+(?:is|are|does|do)\s+|"
    r"how\s+does\s+|tell\s+me\s+about\s+|"
    r"explain\s+|why\s+(?:is|are|did|does)\s+|"
    r"what\s+(?:mechanism|effect|action)|"
    r"should\s+(?:i|we)\s+(?:use|give|start|consider))\b"
)

# Titration step sizes when no target rate is given
_TITRATION_STEP: dict[str, float] = {
    "nicardipine_iv": 2.5,
    "clevidipine_iv": 0.5,
    "labetalol_iv": 2.0,
    "esmolol_iv": 25.0,
    "nitroglycerin_iv": 10.0,
    "nitroprusside_iv": 0.1,
    "hydralazine_iv": 2.5,
    "norepinephrine_iv": 0.05,
    "epinephrine_iv": 0.02,
    "phenylephrine_iv": 0.2,
    "dopamine_iv": 2.0,
    "dobutamine_iv": 2.0,
    "vasopressin_iv": 0.01,
}

# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _drip_keyword(text: str) -> bool:
    return bool(re.search(r"\b(drip|infusion|gtt|continuous|infusing)\b", text))


class ParserService:
    """Deterministic rule-based parser for the hypertensive encephalopathy case family."""

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------

    def parse_turn(self, request: ParseTurnRequest) -> RuntimeParserContract:
        text = request.input_text.strip()
        normalized = text.lower()

        if not text:
            return self._empty_response(request, normalized)

        # Help command — highest priority
        if _HELP_RE.match(normalized):
            return RuntimeParserContract(
                contract_version="0.1.0",
                turnId=request.turn_id,
                timestampSimSec=request.timestamp_sim_sec,
                rawInput=request.input_text,
                normalizedInput=normalized,
                parserMode=request.parser_mode,
                speaker=request.speaker,
                intentSummary="Help command",
                actions=[self._action(
                    tool_name="help_command",
                    action_label="help_command",
                    payload={},
                    raw=raw_input,
                    confidence=1.0,
                    execution_mode="parallel_safe",
                    mapping_action_id="help_command",
                    engine_hooks=[],
                ) for raw_input in [request.input_text]],
                needsClarification=False,
                clarificationQuestion=None,
                clarificationTargets=[],
                overallConfidence=1.0,
                parserStatus="ok",
                nonActionableText=[],
                parserNotes=["Help command requested"],
                safetyFlags=[],
            )

        actions: list[dict] = []
        needs_clarification = False
        clarification_question: str | None = None
        status = "ok"
        notes: list[str] = ["Rule-based parser v3"]

        # ---- Rate/status queries — read-only, skip all action parsers ----
        rate_queries = self._match_rate_query(normalized, text, request.active_infusions)
        if rate_queries:
            actions.extend(rate_queries)
            notes.append("Rate query detected — no state mutation.")
            # fall through to renumbering and return below

        # ---- RSI / intubation — unsupported procedure ----
        elif _RSI_RE.search(normalized):
            actions.extend(self._match_unsupported_procedure(normalized, text))

        # ---- Result retrieval ----
        elif _RETRIEVE_RESULT_RE.search(normalized) and not _ORDER_RE.search(normalized):
            actions.extend(self._match_retrieve_result(normalized, text))

        # ---- Clinical / educational queries ----
        elif _CLINICAL_QUERY_RE.search(normalized) and not _ORDER_RE.search(normalized) and not _START_RE.search(normalized):
            actions.extend(self._match_clinical_query(normalized, text))

        else:
            # ---- Supportive care (IV access, O2, foley, fluids) ----
            actions.extend(self._match_supportive_care(normalized, text))

            # ---- Medication intents (order matters: stop > adjust > start > bolus) ----
            stop_actions = self._match_stop_infusion(normalized, text, request.active_infusions)
            actions.extend(stop_actions)

            if not stop_actions:
                actions.extend(self._match_infusion_adjust(normalized, text, request.active_infusions))
                actions.extend(self._match_infusion_start(normalized, text))
                bolus_actions, bolus_clar, bolus_q, bolus_unsafe = self._match_bolus(normalized, text)
                actions.extend(bolus_actions)
                if bolus_unsafe:
                    # Unsafe dose — still add action but mark status
                    status = "partial_parse"
                    notes.append(bolus_q or "Medication dose/unit appears nonstandard.")
                elif bolus_clar:
                    needs_clarification = True
                    clarification_question = bolus_q
                    status = "clarification_required"

            # Ambiguous stop
            if not stop_actions and self._is_ambiguous_stop(normalized, request.active_infusions):
                needs_clarification = True
                names = ", ".join(
                    i.get("medication_id", "?").replace("_iv", "") for i in request.active_infusions
                )
                clarification_question = f"Which infusion would you like to stop? Active: {names}."
                status = "clarification_required"

            # ---- Non-medication intents ----
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
    # Intent: supportive care (O2, IV access, foley, IV fluids)
    # ------------------------------------------------------------------

    def _match_supportive_care(self, normalized: str, raw: str) -> list[dict]:
        actions: list[dict] = []

        if _O2_RE.search(normalized):
            actions.append(self._action(
                tool_name="give_supportive_care",
                action_label="apply_oxygen",
                payload={"care_type": "oxygen"},
                raw=raw,
                confidence=0.97,
                execution_mode="parallel_safe",
                mapping_action_id="apply_oxygen",
                engine_hooks=[],
            ))

        if _IV_ACCESS_RE.search(normalized):
            actions.append(self._action(
                tool_name="give_supportive_care",
                action_label="establish_iv_access",
                payload={"care_type": "iv_access"},
                raw=raw,
                confidence=0.97,
                execution_mode="parallel_safe",
                mapping_action_id="establish_iv_access",
                engine_hooks=[],
            ))

        if _FOLEY_RE.search(normalized):
            actions.append(self._action(
                tool_name="give_supportive_care",
                action_label="place_foley_catheter",
                payload={"care_type": "foley_catheter"},
                raw=raw,
                confidence=0.97,
                execution_mode="parallel_safe",
                mapping_action_id="place_foley_catheter",
                engine_hooks=[],
            ))

        if _IV_FLUID_RE.search(normalized):
            # Don't double-count if it's medication (e.g. "nicardipine in NS")
            med_id, _ = self._detect_med(normalized)
            if med_id is None:
                actions.append(self._action(
                    tool_name="give_supportive_care",
                    action_label="give_iv_fluid_bolus",
                    payload={"care_type": "iv_fluid_bolus"},
                    raw=raw,
                    confidence=0.93,
                    execution_mode="parallel_safe",
                    mapping_action_id="give_iv_fluid_bolus",
                    engine_hooks=[],
                ))

        return actions

    # ------------------------------------------------------------------
    # Intent: start infusion
    # ------------------------------------------------------------------

    def _match_infusion_start(self, normalized: str, raw: str) -> list[dict]:
        med_id, med_name = self._detect_med(normalized)
        if med_id is None:
            return []
        if med_id in _BOLUS_PREFERRED and not _drip_keyword(normalized):
            return []
        if not (_START_RE.search(normalized) or med_id in _INFUSION_PREFERRED):
            return []
        if _STOP_RE.search(normalized) or _ADJUST_RE.search(normalized):
            return []
        rate = self._extract_rate(normalized) or _DEFAULT_RATE.get(med_id, 5.0)
        label = f"start_{med_name.replace(' ', '_')}"
        hooks: list[str] = []
        # Bug 2 fix: only nicardipine/clevidipine infusions count as "titratable IV agent"
        if med_id in {"nicardipine_iv", "clevidipine_iv"}:
            hooks.append("mark_critical_action_start_titratable_iv_agent")
        return [
            self._action(
                tool_name="start_infusion",
                action_label=label,
                payload={
                    "medication_id": med_id,
                    "infusion_rate": rate,
                    "dose_unit": "mcg_per_kg_per_min" if "mcg" in normalized else "mg_per_hour",
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

    def _match_infusion_adjust(
        self, normalized: str, raw: str, active_infusions: list[dict] | None = None
    ) -> list[dict]:
        if not _ADJUST_RE.search(normalized):
            return []
        med_id, med_name = self._detect_med(normalized)
        if med_id is None:
            return []
        rate = self._extract_rate(normalized)
        if rate is None:
            # Bug 9b fix: apply default titration step when no target rate given
            current_rate = _DEFAULT_RATE.get(med_id, 5.0)
            for inf in (active_infusions or []):
                if inf.get("medication_id") == med_id:
                    current_rate = float(inf.get("current_infusion_rate", current_rate))
                    break
            step = _TITRATION_STEP.get(med_id, round(current_rate * 0.25, 1))
            is_increase = bool(re.search(r"\b(increase|raise|uptitrate|bump\s+up|turn\s+up|up)\b", normalized))
            rate = round(max(0.1, current_rate + (step if is_increase else -step)), 2)
        label = f"adjust_{med_name.replace(' ', '_')}"
        return [
            self._action(
                tool_name="adjust_infusion",
                action_label=label,
                payload={"medication_id": med_id, "new_infusion_rate": rate, "dose_unit": "mg_per_hour", "route": "IV"},
                raw=raw,
                confidence=0.90,
                execution_mode="sequential",
                mapping_action_id=label,
                engine_hooks=[],
            )
        ]

    # ------------------------------------------------------------------
    # Intent: stop infusion
    # ------------------------------------------------------------------

    def _match_stop_infusion(self, normalized: str, raw: str, active_infusions: list[dict]) -> list[dict]:
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
        return []

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
    ) -> tuple[list[dict], bool, str | None, bool]:
        """Returns (actions, needs_clarification, message, is_unsafe)."""
        med_id, med_name = self._detect_med(normalized)
        if med_id is None or med_id not in _BOLUS_PREFERRED:
            return [], False, None, False
        if _drip_keyword(normalized):
            return [], False, None, False

        # Allow labetalol/hydralazine without explicit bolus verb if dose present
        has_bolus_verb = bool(_BOLUS_RE.search(normalized))
        dose = self._extract_dose(normalized)
        if not has_bolus_verb and dose is None:
            return [], False, None, False

        if dose is None:
            return (
                [],
                True,
                f"What dose of {med_name} would you like to give? (e.g., 20 mg IV)",
                False,
            )

        # Safety check — flag implausible doses
        max_safe = _UNSAFE_BOLUS_DOSE_MG.get(med_id)
        if max_safe is not None and dose > max_safe:
            unsafe_msg = (
                f"{med_name.capitalize()} recognized, but the entered dose ({dose} mg) "
                f"appears outside the expected IV push range. "
                f"Check units — did you mean {int(dose * 1000)} mcg?"
                if med_id == "phenylephrine_iv"
                else f"{med_name.capitalize()} dose {dose} mg exceeds expected range. Please verify."
            )
            label = f"give_{med_name.replace(' ', '_')}_bolus"
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
                            "safety_flag": "dose_unit_warning",
                        },
                        raw=raw,
                        confidence=0.60,
                        execution_mode="sequential",
                        mapping_action_id=label,
                        engine_hooks=[],
                    )
                ],
                False,
                unsafe_msg,
                True,
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
            False,
        )

    # ------------------------------------------------------------------
    # Intent: order diagnostics
    # ------------------------------------------------------------------

    def _match_diagnostics(self, normalized: str, raw: str) -> list[dict]:
        actions: list[dict] = []
        has_order_verb = bool(_ORDER_RE.search(normalized))
        has_bypass = bool(_LAB_BYPASS.search(normalized))
        for pattern, diag_id, order_type in _DIAGNOSTICS:
            if not re.search(pattern, normalized):
                continue
            if not has_order_verb and not has_bypass:
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
            r"put\s+(?:her|him|them)\s+on\s+(?:the\s+)?monitor|on\s+telemetry|"
            r"monitor(?:ing)?\s+(?:set\s+up|established)|place\s+on\s+monitor)\b",
            normalized,
        ):
            actions.append(
                self._action(
                    tool_name="set_monitoring",
                    action_label="enable_continuous_monitoring",
                    payload={"monitor_action": "enable_continuous_monitoring", "telemetry": True, "pulse_ox": True},
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
                    payload={"monitor_action": "set_nibp_cycle", "nibp_cycle_sec": nibp_sec},
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
                        payload={"disposition": disposition, "reason": "hypertensive emergency with neurologic dysfunction"},
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
        if not re.search(r"\b(reassess|reassessment|re-assess|recheck|re-evaluate|reassess)\b", normalized):
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
    # Intent: rate/status query (read-only)
    # ------------------------------------------------------------------

    def _match_rate_query(self, normalized: str, raw: str, active_infusions: list[dict]) -> list[dict]:
        if not _RATE_QUERY_RE.search(normalized):
            return []
        med_id, med_name = self._detect_med(normalized)
        return [self._action(
            tool_name="query_infusion_status",
            action_label=f"query_{med_name.replace(' ', '_') or 'all_infusions'}_rate",
            payload={"medication_id": med_id},
            raw=raw,
            confidence=0.90,
            execution_mode="parallel_safe",
            mapping_action_id="query_infusion_status",
            engine_hooks=[],
        )]

    # ------------------------------------------------------------------
    # Intent: unsupported procedure (RSI / intubation)
    # ------------------------------------------------------------------

    def _match_unsupported_procedure(self, normalized: str, raw: str) -> list[dict]:
        return [self._action(
            tool_name="unsupported_procedure",
            action_label="unsupported_rsi_intubation",
            payload={"procedure_name": "RSI/intubation"},
            raw=raw,
            confidence=0.95,
            execution_mode="parallel_safe",
            mapping_action_id="unsupported_procedure",
            engine_hooks=[],
        )]

    # ------------------------------------------------------------------
    # Intent: retrieve prior diagnostic result
    # ------------------------------------------------------------------

    def _match_retrieve_result(self, normalized: str, raw: str) -> list[dict]:
        # Try to identify which diagnostic is being asked about
        for pattern, diag_id, _ in _DIAGNOSTICS:
            if re.search(pattern, normalized):
                return [self._action(
                    tool_name="retrieve_diagnostic_result",
                    action_label=f"retrieve_{diag_id}_result",
                    payload={"diagnostic_id": diag_id},
                    raw=raw,
                    confidence=0.88,
                    execution_mode="parallel_safe",
                    mapping_action_id="retrieve_diagnostic_result",
                    engine_hooks=[],
                )]
        return [self._action(
            tool_name="retrieve_diagnostic_result",
            action_label="retrieve_unspecified_result",
            payload={"diagnostic_id": None},
            raw=raw,
            confidence=0.70,
            execution_mode="parallel_safe",
            mapping_action_id="retrieve_diagnostic_result",
            engine_hooks=[],
        )]

    # ------------------------------------------------------------------
    # Intent: clinical / educational query
    # ------------------------------------------------------------------

    def _match_clinical_query(self, normalized: str, raw: str) -> list[dict]:
        return [self._action(
            tool_name="clinical_query",
            action_label="clinical_query",
            payload={"query": normalized},
            raw=raw,
            confidence=0.75,
            execution_mode="parallel_safe",
            mapping_action_id="clinical_query",
            engine_hooks=[],
        )]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _detect_med(normalized: str) -> tuple[str | None, str]:
        for name in _MED_NAMES:
            if name in normalized:
                return _MED_ID[name], name
        return None, ""

    @staticmethod
    def _extract_rate(text: str) -> float | None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg\s*(?:per\s+)?/?h(?:r|our)?", text)
        if m:
            return float(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mcg|μg)\s*/\s*kg\s*/\s*min", text)
        if m:
            return float(m.group(1))
        m = re.search(r"(?:at|to)\s+(\d+(?:\.\d+)?)\s*(?:mg)?", text)
        if m:
            return float(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", text)
        if m:
            return float(m.group(1))
        return None

    @staticmethod
    def _extract_dose(text: str) -> float | None:
        m = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", text)
        if m:
            return float(m.group(1))
        m = re.search(r"(\d+(?:\.\d+)?)\s*(?:mcg|μg)\b", text)
        if m:
            return float(m.group(1)) / 1000  # convert to mg for comparison
        m = re.search(r"\b(\d+)\b", text)
        if m:
            return float(m.group(1))
        return None

    @staticmethod
    def _extract_nibp_interval(text: str) -> int | None:
        for pattern, sec in _NIBP_INTERVALS:
            if re.search(pattern, text):
                return sec
        m = re.search(r"(?:bp|blood\s+pressure|cuff)\s+(?:check\s+)?every\s+(\d+)\s*(?:min|minute)", text)
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
            "sequenceIndex": 0,
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
            parserNotes=["Rule-based parser v3"],
            safetyFlags=[],
        )
