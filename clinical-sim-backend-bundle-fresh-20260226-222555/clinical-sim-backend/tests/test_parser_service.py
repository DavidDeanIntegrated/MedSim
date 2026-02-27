"""Tests for the rule-based ParserService.

Covers the five primary scenarios requested:
  1. Start nicardipine infusion
  2. Give labetalol IV bolus
  3. Order head CT
  4. Admit to ICU
  5. Ambiguous stop infusion (with / without clarification)

Each test calls ParserService directly (unit-level, no HTTP).
"""

from __future__ import annotations

import pytest

from app.models.parser import ParseTurnRequest
from app.services.parser_service import ParserService

svc = ParserService()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _req(
    input_text: str,
    *,
    active_infusions: list[dict] | None = None,
    turn_id: str = "t_test",
) -> ParseTurnRequest:
    return ParseTurnRequest(
        turnId=turn_id,
        timestampSimSec=0,
        inputText=input_text,
        parserMode="rule",
        activeInfusions=active_infusions or [],
    )


def _first_action(input_text: str, *, active_infusions: list[dict] | None = None):
    result = svc.parse_turn(_req(input_text, active_infusions=active_infusions))
    assert result.actions, f"Expected at least one action for: {input_text!r}"
    return result.actions[0]


# ---------------------------------------------------------------------------
# 1. Start nicardipine infusion
# ---------------------------------------------------------------------------


class TestStartNicardipine:
    def test_start_with_mg_per_hour_rate(self):
        action = _first_action("start nicardipine at 5 mg/hr")
        assert action.tool_name == "start_infusion"
        assert action.payload["medication_id"] == "nicardipine_iv"
        assert action.payload["infusion_rate"] == 5.0
        assert action.payload["administration_mode"] == "infusion_start"

    def test_start_with_spelled_out_rate(self):
        # "at 5 milligrams" — captured by the "at X" fallback in _extract_rate
        action = _first_action("start nicardipine at 5 milligrams per hour")
        assert action.tool_name == "start_infusion"
        assert action.payload["infusion_rate"] == 5.0

    def test_start_with_higher_rate(self):
        action = _first_action("start nicardipine 10 mg/hr")
        assert action.payload["infusion_rate"] == 10.0

    def test_start_without_rate_uses_default(self):
        action = _first_action("start nicardipine")
        assert action.tool_name == "start_infusion"
        assert action.payload["medication_id"] == "nicardipine_iv"
        assert action.payload["infusion_rate"] == 5.0  # default

    def test_cardene_alias(self):
        action = _first_action("hang a cardene drip at 5 mg/hr")
        assert action.payload["medication_id"] == "nicardipine_iv"

    def test_status_ok_on_success(self):
        result = svc.parse_turn(_req("start nicardipine 5 mg/hr"))
        assert result.parser_status == "ok"
        assert not result.needs_clarification

    def test_engine_hook_marks_titratable_agent(self):
        action = _first_action("start nicardipine")
        assert "mark_critical_action_start_titratable_iv_agent" in action.engine_hooks

    def test_clevidipine_starts_as_infusion(self):
        action = _first_action("start clevidipine at 1 mg/hr")
        assert action.payload["medication_id"] == "clevidipine_iv"
        assert action.tool_name == "start_infusion"

    def test_begin_nicardipine(self):
        action = _first_action("begin nicardipine drip")
        assert action.tool_name == "start_infusion"
        assert action.payload["medication_id"] == "nicardipine_iv"


# ---------------------------------------------------------------------------
# 2. Give labetalol IV bolus
# ---------------------------------------------------------------------------


class TestGiveLabetalol:
    def test_give_20mg_bolus(self):
        action = _first_action("give labetalol 20 mg IV")
        assert action.tool_name == "give_medication"
        assert action.payload["medication_id"] == "labetalol_iv"
        assert action.payload["dose"] == 20.0
        assert action.payload["administration_mode"] == "bolus"

    def test_give_40mg_bolus(self):
        action = _first_action("give labetalol 40 mg")
        assert action.payload["dose"] == 40.0

    def test_give_10mg_bolus(self):
        action = _first_action("push labetalol 10 mg")
        assert action.tool_name == "give_medication"
        assert action.payload["dose"] == 10.0

    def test_give_80mg_bolus(self):
        action = _first_action("administer labetalol 80 mg IV push")
        assert action.payload["dose"] == 80.0

    def test_arbitrary_dose_accepted(self):
        # No artificial restriction to 10/20/40/80 mg
        action = _first_action("give labetalol 60 mg IV")
        assert action.payload["dose"] == 60.0

    def test_missing_dose_requests_clarification(self):
        result = svc.parse_turn(_req("give labetalol"))
        assert result.needs_clarification is True
        assert result.parser_status == "clarification_required"
        assert result.clarification_question is not None
        assert "labetalol" in result.clarification_question.lower()

    def test_status_ok_with_dose(self):
        result = svc.parse_turn(_req("give labetalol 20 mg"))
        assert result.parser_status == "ok"

    def test_engine_hook_present(self):
        action = _first_action("give labetalol 20 mg IV")
        assert any("titratable" in h for h in action.engine_hooks)

    def test_hydralazine_bolus(self):
        action = _first_action("give hydralazine 10 mg IV")
        assert action.tool_name == "give_medication"
        assert action.payload["medication_id"] == "hydralazine_iv"
        assert action.payload["dose"] == 10.0

    def test_labetalol_drip_routes_to_infusion_not_bolus(self):
        result = svc.parse_turn(_req("start labetalol drip"))
        assert any(a.tool_name == "start_infusion" for a in result.actions)
        assert all(a.tool_name != "give_medication" for a in result.actions)


# ---------------------------------------------------------------------------
# 3. Order head CT
# ---------------------------------------------------------------------------


class TestOrderHeadCT:
    def test_order_head_ct(self):
        action = _first_action("order a head CT")
        assert action.tool_name == "order_diagnostic"
        assert action.payload["diagnostic_id"] == "head_ct_noncontrast"

    def test_ct_head_phrasing(self):
        action = _first_action("get a CT head")
        assert action.payload["diagnostic_id"] == "head_ct_noncontrast"

    def test_ct_of_her_head(self):
        action = _first_action("get a CT of her head")
        assert action.payload["diagnostic_id"] == "head_ct_noncontrast"

    def test_noncontrast_ct(self):
        action = _first_action("order non-contrast CT of head")
        assert action.payload["diagnostic_id"] == "head_ct_noncontrast"

    def test_order_type_is_imaging(self):
        action = _first_action("order head CT stat")
        assert action.payload["order_type"] == "imaging"

    def test_priority_is_urgent(self):
        action = _first_action("order head CT")
        assert action.payload["priority"] == "urgent"

    def test_engine_hook_marks_neuro_workup(self):
        action = _first_action("order head CT")
        assert "mark_critical_action_order_neuro_workup" in action.engine_hooks

    def test_ecg_ordered(self):
        action = _first_action("order an ECG")
        assert action.payload["diagnostic_id"] == "ecg"
        assert action.tool_name == "order_diagnostic"

    def test_troponin_ordered(self):
        action = _first_action("check troponin")
        assert action.payload["diagnostic_id"] == "troponin"

    def test_cmp_ordered(self):
        action = _first_action("send a CMP")
        assert action.payload["diagnostic_id"] == "cmp"

    def test_multiple_diagnostics_in_one_turn(self):
        result = svc.parse_turn(_req("order a head CT and get an ECG"))
        diag_ids = {a.payload["diagnostic_id"] for a in result.actions if a.tool_name == "order_diagnostic"}
        assert "head_ct_noncontrast" in diag_ids
        assert "ecg" in diag_ids


# ---------------------------------------------------------------------------
# 4. Admit to ICU
# ---------------------------------------------------------------------------


class TestAdmitICU:
    def test_admit_to_icu(self):
        action = _first_action("admit her to the ICU")
        assert action.tool_name == "set_disposition"
        assert action.payload["disposition"] == "icu_admission"

    def test_icu_abbreviation_alone(self):
        action = _first_action("ICU please")
        assert action.payload["disposition"] == "icu_admission"

    def test_intensive_care_phrase(self):
        action = _first_action("transfer to intensive care")
        assert action.payload["disposition"] == "icu_admission"

    def test_icu_bed(self):
        action = _first_action("she needs an ICU bed")
        assert action.payload["disposition"] == "icu_admission"

    def test_engine_hook_marks_disposition(self):
        action = _first_action("admit to ICU")
        assert "mark_critical_action_disposition" in action.engine_hooks

    def test_status_ok(self):
        result = svc.parse_turn(_req("admit to ICU"))
        assert result.parser_status == "ok"

    def test_icu_combined_with_nicardipine(self):
        """Single turn ordering both medication and disposition."""
        result = svc.parse_turn(_req("start nicardipine and admit to the ICU"))
        tool_names = {a.tool_name for a in result.actions}
        assert "start_infusion" in tool_names
        assert "set_disposition" in tool_names


# ---------------------------------------------------------------------------
# 5. Ambiguous stop infusion
# ---------------------------------------------------------------------------


class TestAmbiguousStopInfusion:
    _two_active = [
        {"medication_id": "nicardipine_iv", "display_rate": "5 mg/hr"},
        {"medication_id": "labetalol_iv", "display_rate": "2 mg/hr"},
    ]
    _one_active = [{"medication_id": "nicardipine_iv", "display_rate": "5 mg/hr"}]

    # -- ambiguous (>1 active, no medication named) --

    def test_stop_infusion_two_active_is_ambiguous(self):
        result = svc.parse_turn(_req("stop the infusion", active_infusions=self._two_active))
        assert result.needs_clarification is True
        assert result.parser_status == "clarification_required"
        assert result.clarification_question is not None

    def test_stop_drip_two_active_is_ambiguous(self):
        result = svc.parse_turn(_req("stop the drip", active_infusions=self._two_active))
        assert result.needs_clarification is True

    def test_clarification_question_lists_active_medications(self):
        result = svc.parse_turn(_req("stop infusion", active_infusions=self._two_active))
        q = result.clarification_question or ""
        assert "nicardipine" in q or "labetalol" in q

    def test_no_actions_when_ambiguous(self):
        result = svc.parse_turn(_req("stop the infusion", active_infusions=self._two_active))
        assert result.actions == []

    # -- unambiguous: medication named explicitly --

    def test_stop_named_medication_is_not_ambiguous(self):
        result = svc.parse_turn(
            _req("stop nicardipine", active_infusions=self._two_active)
        )
        assert result.needs_clarification is False
        assert result.parser_status == "ok"
        assert result.actions[0].tool_name == "stop_infusion"
        assert result.actions[0].payload["medication_id"] == "nicardipine_iv"

    def test_discontinue_named_medication(self):
        result = svc.parse_turn(
            _req("discontinue labetalol", active_infusions=self._two_active)
        )
        assert result.actions[0].payload["medication_id"] == "labetalol_iv"

    # -- auto-disambiguate: exactly one infusion running --

    def test_stop_infusion_one_active_auto_disambiguates(self):
        result = svc.parse_turn(_req("stop the infusion", active_infusions=self._one_active))
        assert result.needs_clarification is False
        assert len(result.actions) == 1
        assert result.actions[0].tool_name == "stop_infusion"
        assert result.actions[0].payload["medication_id"] == "nicardipine_iv"

    def test_hold_drip_one_active_auto_disambiguates(self):
        result = svc.parse_turn(_req("hold the drip", active_infusions=self._one_active))
        assert result.actions[0].payload["medication_id"] == "nicardipine_iv"

    # -- no active infusions --

    def test_stop_infusion_no_active_is_partial_parse(self):
        result = svc.parse_turn(_req("stop infusion", active_infusions=[]))
        assert result.parser_status == "partial_parse"
        assert result.needs_clarification is False
        assert result.actions == []


# ---------------------------------------------------------------------------
# Edge cases and multi-intent turns
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_input_rejected(self):
        result = svc.parse_turn(_req(""))
        assert result.parser_status == "rejected"
        assert result.needs_clarification is True

    def test_unrecognised_input_partial_parse(self):
        result = svc.parse_turn(_req("the patient looks better"))
        assert result.parser_status == "partial_parse"
        assert result.actions == []

    def test_reassess_generates_two_actions(self):
        result = svc.parse_turn(_req("reassess the patient"))
        reassess = [a for a in result.actions if a.tool_name == "perform_reassessment"]
        rtypes = {a.payload["reassessment_type"] for a in reassess}
        assert "neurologic_reassessment" in rtypes
        assert "hemodynamic_reassessment" in rtypes

    def test_adjust_infusion_increase(self):
        result = svc.parse_turn(_req("increase nicardipine to 10 mg/hr"))
        assert any(a.tool_name == "adjust_infusion" for a in result.actions)
        adj = next(a for a in result.actions if a.tool_name == "adjust_infusion")
        assert adj.payload["medication_id"] == "nicardipine_iv"
        assert adj.payload["new_infusion_rate"] == 10.0

    def test_adjust_infusion_decrease(self):
        result = svc.parse_turn(_req("decrease nicardipine to 2.5 mg/hr"))
        adj = next(a for a in result.actions if a.tool_name == "adjust_infusion")
        assert adj.payload["new_infusion_rate"] == 2.5

    def test_hypertensive_emergency_assessment(self):
        result = svc.parse_turn(_req("this is a hypertensive emergency"))
        assert any(a.tool_name == "document_assessment" for a in result.actions)

    def test_nibp_every_5_minutes(self):
        result = svc.parse_turn(_req("check blood pressure every 5 minutes"))
        nibp = next(
            (a for a in result.actions if a.payload.get("monitor_action") == "set_nibp_cycle"),
            None,
        )
        assert nibp is not None
        assert nibp.payload["nibp_cycle_sec"] == 300

    def test_sequence_indices_are_contiguous(self):
        result = svc.parse_turn(
            _req("start nicardipine, order head CT, and admit to ICU")
        )
        indices = [a.sequence_index for a in result.actions]
        assert indices == list(range(len(indices)))
