from __future__ import annotations

from copy import deepcopy
from typing import Any


class SimulationStateMachine:
    """Deterministic MVP engine for hypertensive emergency case families.

    This version is intentionally narrow and explicit. It is designed to be:
    - auditable
    - easy to tune
    - easy to replace later with a richer physiology engine

    Current focus:
    - hypertensive encephalopathy / PRES-style case progression
    - IV antihypertensive actions
    - diagnostic scheduling
    - harm event detection
    - critical-action scoring
    """

    def apply_actions(
        self,
        patient_state: dict[str, Any],
        actions: list[dict[str, Any]],
        advance_time_sec: int,
    ) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
        state_before = deepcopy(patient_state)
        state_after = deepcopy(patient_state)
        events: list[dict[str, Any]] = []
        current_time = state_after.get("case_metadata", {}).get("time_elapsed_sec", 0)
        next_time = current_time + advance_time_sec

        state_after.setdefault("orders", [])
        state_after.setdefault("event_log", [])
        state_after.setdefault("active_medications", [])
        state_after.setdefault("monitor", {}).setdefault("waveform_flags", [])
        state_after.setdefault("scoring", {}).setdefault("critical_actions", [])
        state_after.setdefault("scoring", {}).setdefault("harm_events", [])
        state_after.setdefault("scoring", {}).setdefault("teaching_points", [])
        state_after.setdefault("scoring", {}).setdefault("final_score", 0)

        critical_completed: list[str] = []
        harm_triggered: list[str] = []
        teaching_markers: list[str] = []

        # 1) Apply explicit actions
        for action in sorted(actions, key=lambda a: a.get("sequence_index", 0)):
            tool_name = action.get("tool_name") or action.get("toolName")
            payload = action.get("payload", {})
            if tool_name == "start_infusion":
                self._start_infusion(state_after, payload, next_time, events)
            elif tool_name == "adjust_infusion":
                self._adjust_infusion(state_after, payload, next_time, events)
            elif tool_name == "stop_infusion":
                self._stop_infusion(state_after, payload, next_time, events)
            elif tool_name == "give_medication":
                self._give_bolus(state_after, payload, next_time, events)
            elif tool_name == "order_diagnostic":
                self._order_diagnostic(state_after, payload, next_time, events)
            elif tool_name == "set_monitoring":
                self._set_monitoring(state_after, payload, next_time, events)
            elif tool_name == "perform_reassessment":
                self._perform_reassessment(state_after, payload, next_time, events)
            elif tool_name == "set_disposition":
                self._set_disposition(state_after, payload, next_time, events)
            elif tool_name == "document_assessment":
                self._document_assessment(state_after, payload, next_time, events)

        # 2) Progress medication effects and disease state over time
        self._progress_active_medications(state_after, advance_time_sec, next_time, events)
        self._apply_disease_progression(state_after, advance_time_sec, next_time, events)
        self._release_due_diagnostics(state_after, next_time, events)

        # 3) Recompute derived monitor fields
        self._recompute_monitor(state_after)

        # 4) Evaluate scoring and harm
        critical_completed.extend(self._evaluate_critical_actions(state_after))
        new_harm_ids, new_harm_events = self._evaluate_harm_events(state_after, next_time)
        harm_triggered.extend(new_harm_ids)
        events.extend(new_harm_events)

        # 5) Update running score
        score_delta = len(critical_completed) * 8 - len(harm_triggered) * 12
        state_after["scoring"]["final_score"] = max(
            0,
            min(100, state_after["scoring"].get("final_score", 0) + score_delta),
        )
        if critical_completed:
            teaching_markers.append("critical_actions_completed")
        if harm_triggered:
            teaching_markers.append("harm_events_triggered")

        state_after["scoring"].setdefault("runtime", {})
        state_after["scoring"]["runtime"]["critical_actions_completed_this_turn"] = critical_completed
        state_after["scoring"]["runtime"]["harm_events_triggered_this_turn"] = harm_triggered
        state_after["scoring"]["runtime"]["teaching_markers_added_this_turn"] = teaching_markers
        state_after["scoring"]["runtime"]["score_delta_this_turn"] = score_delta

        state_after["case_metadata"]["time_elapsed_sec"] = next_time
        self._append_events_to_log(state_after, events)

        delta = self._build_delta(state_before, state_after)
        return state_after, delta, events

    # --------------------
    # Action handlers
    # --------------------

    def _start_infusion(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        med_id = payload.get("medication_id")
        rate = payload.get("infusion_rate", 0)
        existing = self._find_active_med(state, med_id)
        if existing:
            existing["current_infusion_rate"] = rate
            existing["active"] = True
            existing["last_dose_time_sec"] = now
            events.append(self._evt(now, "medication_effect", "info", f"{med_id} infusion adjusted to {rate}.", {"medication_id": med_id, "rate": rate}))
            return

        entry = {
            "medication_id": med_id,
            "route": payload.get("route", "IV"),
            "mode": "infusion",
            "active": True,
            "last_dose_time_sec": now,
            "effect_site_concentration": 0.0,
            "current_infusion_rate": rate,
            "cumulative_dose": 0.0,
            "toxicity_flags": [],
        }
        state["active_medications"].append(entry)
        events.append(self._evt(now, "medication_effect", "info", f"{med_id} infusion started.", {"medication_id": med_id, "rate": rate}))

    def _adjust_infusion(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        med_id = payload.get("medication_id")
        med = self._find_active_med(state, med_id)
        if not med:
            events.append(self._evt(now, "state_update", "low", f"No active infusion found for {med_id}.", {"medication_id": med_id}))
            return
        med["current_infusion_rate"] = payload.get("new_infusion_rate", payload.get("infusion_rate", med.get("current_infusion_rate", 0)))
        med["last_dose_time_sec"] = now
        events.append(self._evt(now, "medication_effect", "info", f"{med_id} infusion adjusted.", {"medication_id": med_id, "rate": med["current_infusion_rate"]}))

    def _stop_infusion(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        med_id = payload.get("medication_id")
        med = self._find_active_med(state, med_id)
        if not med:
            return
        med["active"] = False
        med["current_infusion_rate"] = 0
        med["last_dose_time_sec"] = now
        events.append(self._evt(now, "medication_effect", "info", f"{med_id} infusion stopped.", {"medication_id": med_id}))

    def _give_bolus(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        med_id = payload.get("medication_id")
        dose = float(payload.get("dose", 0))
        med = self._find_active_med(state, med_id, include_inactive=True)
        if not med:
            med = {
                "medication_id": med_id,
                "route": payload.get("route", "IV"),
                "mode": "bolus",
                "active": True,
                "last_dose_time_sec": now,
                "effect_site_concentration": 0.0,
                "current_infusion_rate": 0.0,
                "cumulative_dose": 0.0,
                "toxicity_flags": [],
            }
            state["active_medications"].append(med)
        med["last_dose_time_sec"] = now
        med["cumulative_dose"] += dose
        med["effect_site_concentration"] += self._bolus_to_effect(med_id, dose)
        events.append(self._evt(now, "medication_effect", "info", f"{med_id} bolus given.", {"medication_id": med_id, "dose": dose}))

    def _order_diagnostic(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        diag_id = payload.get("diagnostic_id")
        if any(o.get("payload", {}).get("diagnostic_id") == diag_id for o in state.get("orders", [])):
            return
        result_delay = {
            "head_ct_noncontrast": 900,
            "mri_brain": 2700,
            "ecg": 180,
            "cmp": 300,
            "troponin": 300,
            "pregnancy_test": 240,
            "urinalysis": 300,
        }.get(diag_id, 300)
        state["orders"].append(
            {
                "time_sec": now,
                "actor": "resident",
                "order_type": payload.get("order_type", "diagnostic"),
                "payload": {
                    **payload,
                    "status": "pending",
                    "result_available_at_sec": now + result_delay,
                },
            }
        )
        events.append(self._evt(now, "state_update", "info", f"Diagnostic ordered: {diag_id}.", {"diagnostic_id": diag_id, "result_available_at_sec": now + result_delay}))

    def _set_monitoring(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        action = payload.get("monitor_action")
        if action == "set_nibp_cycle":
            state.setdefault("monitor", {})["nibp_cycle_sec"] = payload.get("nibp_cycle_sec", 300)
        if action == "enable_continuous_monitoring":
            state.setdefault("monitor", {})["telemetry_quality"] = "good"
        events.append(self._evt(now, "state_update", "info", "Monitoring updated.", {"monitor_action": action}))

    def _perform_reassessment(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        reassessment_type = payload.get("reassessment_type")
        state.setdefault("orders", []).append(
            {
                "time_sec": now,
                "actor": "resident",
                "order_type": "note",
                "payload": {"reassessment_type": reassessment_type, "status": "completed"},
            }
        )
        events.append(self._evt(now, "state_update", "info", f"Reassessment performed: {reassessment_type}.", {"reassessment_type": reassessment_type}))

    def _set_disposition(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        state.setdefault("orders", []).append(
            {
                "time_sec": now,
                "actor": "resident",
                "order_type": "note",
                "payload": {"disposition": payload.get("disposition"), "status": "requested"},
            }
        )
        events.append(self._evt(now, "state_update", "info", f"Disposition selected: {payload.get('disposition')}.", {"disposition": payload.get("disposition")}))

    def _document_assessment(self, state: dict[str, Any], payload: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        state.setdefault("orders", []).append(
            {
                "time_sec": now,
                "actor": "resident",
                "order_type": "note",
                "payload": {"assessment_concept": payload.get("assessment_concept"), "status": "documented"},
            }
        )
        events.append(self._evt(now, "state_update", "info", "Assessment documented.", {"assessment": payload.get("assessment_concept")}))

    # --------------------
    # Physiology progression
    # --------------------

    def _progress_active_medications(self, state: dict[str, Any], dt_sec: int, now: int, events: list[dict[str, Any]]) -> None:
        hemo = state.setdefault("hemodynamics", {})
        neuro = state.setdefault("neurologic", {})
        disease = state.setdefault("disease_model", {})
        renal = state.setdefault("renal", {})

        total_svr_drop = 0.0
        total_hr_drop = 0.0
        total_brady_risk = 0.0

        for med in state.get("active_medications", []):
            med_id = med.get("medication_id")
            rate = float(med.get("current_infusion_rate", 0) or 0)
            ce = float(med.get("effect_site_concentration", 0) or 0)
            active = bool(med.get("active", False))

            if active and rate > 0:
                med["cumulative_dose"] += self._infusion_dose_increment(med_id, rate, dt_sec)
                ce += self._infusion_to_effect(med_id, rate, dt_sec)
            ce *= self._washout_factor(med_id, dt_sec)
            med["effect_site_concentration"] = max(0.0, ce)

            if med_id == "nicardipine_iv":
                effect = min(0.35, ce * 0.22)
                total_svr_drop += effect
            elif med_id == "clevidipine_iv":
                effect = min(0.42, ce * 0.28)
                total_svr_drop += effect
            elif med_id == "labetalol_iv":
                effect = min(0.45, ce * 0.20)
                total_svr_drop += effect * 0.75
                total_hr_drop += effect * 28
                total_brady_risk += effect
            elif med_id == "esmolol_iv":
                effect = min(0.5, ce * 0.30)
                total_hr_drop += effect * 36
                total_brady_risk += effect * 1.2
            elif med_id == "nitroglycerin_iv":
                effect = min(0.25, ce * 0.18)
                total_svr_drop += effect * 0.45
            elif med_id == "nitroprusside_iv":
                effect = min(0.55, ce * 0.35)
                total_svr_drop += effect

        starting_map = state.get("case_runtime", {}).get("starting_map")
        if starting_map is None:
            state.setdefault("case_runtime", {})["starting_map"] = hemo.get("map", 0)
            starting_map = hemo.get("map", 0)

        svr_index = float(hemo.get("svr_index", 1.5))
        hr = float(hemo.get("hr", 100))
        map_before = float(hemo.get("map", 150))

        svr_index = max(0.7, svr_index - total_svr_drop)
        hr = max(32, hr - total_hr_drop)

        new_map = max(45, map_before - (total_svr_drop * 40) - max(0, total_hr_drop * 0.35))
        map_drop_fraction = 0.0 if starting_map <= 0 else max(0.0, (starting_map - new_map) / starting_map)

        # Controlled improvement in hypertensive encephalopathy
        if 0.10 <= map_drop_fraction <= 0.25:
            disease["cerebral_edema_index"] = max(0.0, float(disease.get("cerebral_edema_index", 0.5)) - 0.03)
            neuro["headache_index"] = max(0.0, float(neuro.get("headache_index", 0.8)) - 0.03)
            neuro["vision_change_index"] = max(0.0, float(neuro.get("vision_change_index", 0.6)) - 0.025)
            if neuro.get("mental_status") in {"confused", "somnolent"} and map_drop_fraction >= 0.15:
                neuro["mental_status"] = "anxious"
                neuro["gcs"] = max(14, int(neuro.get("gcs", 14)))
                events.append(self._evt(now, "clinical_improvement", "moderate", "Neurologic symptoms improving with controlled BP reduction.", {}))

        # Overcorrection penalty
        if map_drop_fraction > 0.25:
            neuro["cerebral_hypoperfusion_index"] = min(1.0, float(neuro.get("cerebral_hypoperfusion_index", 0.0)) + 0.25)
            neuro["mental_status"] = "somnolent"
            neuro["gcs"] = max(7, int(neuro.get("gcs", 14)) - 2)
            renal["renal_perfusion_index"] = max(0.3, float(renal.get("renal_perfusion_index", 0.8)) - 0.12)
            events.append(self._evt(now, "clinical_deterioration", "high", "Patient worsened from overly rapid blood pressure reduction.", {}))

        if total_brady_risk > 0.35 and hr < 55:
            hemo["rhythm"] = "sinus_bradycardia"
        if total_brady_risk > 0.55 and hr < 45:
            hemo["rhythm"] = "high_grade_av_block"

        pulse_pressure = max(20, (new_map * 0.72) - (new_map * 0.45))
        sbp = int(round(new_map + pulse_pressure / 2))
        dbp = int(round(new_map - pulse_pressure / 2))

        hemo["svr_index"] = round(svr_index, 3)
        hemo["hr"] = int(round(hr))
        hemo["map"] = int(round(new_map))
        hemo["sbp"] = max(40, sbp)
        hemo["dbp"] = max(20, dbp)

    def _apply_disease_progression(self, state: dict[str, Any], dt_sec: int, now: int, events: list[dict[str, Any]]) -> None:
        hemo = state.setdefault("hemodynamics", {})
        neuro = state.setdefault("neurologic", {})
        disease = state.setdefault("disease_model", {})
        renal = state.setdefault("renal", {})

        map_val = float(hemo.get("map", 150))
        cerebral_edema = float(disease.get("cerebral_edema_index", 0.5))

        # Untreated or undertreated progression
        if map_val > 145:
            disease["cerebral_edema_index"] = min(1.0, cerebral_edema + (0.01 * dt_sec / 60.0))
            neuro["headache_index"] = min(1.0, float(neuro.get("headache_index", 0.8)) + (0.01 * dt_sec / 60.0))
            neuro["vision_change_index"] = min(1.0, float(neuro.get("vision_change_index", 0.7)) + (0.008 * dt_sec / 60.0))
            if disease["cerebral_edema_index"] > 0.66 and neuro.get("mental_status") == "confused":
                neuro["mental_status"] = "somnolent"
                neuro["gcs"] = max(11, int(neuro.get("gcs", 14)) - 1)
                events.append(self._evt(now, "clinical_deterioration", "moderate", "Patient is becoming more drowsy as cerebral edema worsens.", {}))
            if disease["cerebral_edema_index"] > 0.82 and neuro.get("mental_status") != "seizing":
                neuro["mental_status"] = "agitated"
                events.append(self._evt(now, "case_progression", "high", "Impending seizure behavior: agitation and staring episodes.", {}))
            if disease["cerebral_edema_index"] > 0.90:
                neuro["mental_status"] = "seizing"
                neuro["gcs"] = 6
                events.append(self._evt(now, "clinical_deterioration", "critical", "Generalized seizure due to uncontrolled hypertensive encephalopathy.", {}))

        if map_val < 70:
            renal["renal_perfusion_index"] = max(0.2, float(renal.get("renal_perfusion_index", 0.8)) - 0.08)
            renal["aki_risk_index"] = min(1.0, float(renal.get("aki_risk_index", 0.2)) + 0.06)

        # Update UOP roughly from perfusion
        perf = float(renal.get("renal_perfusion_index", 0.8))
        renal["urine_output_ml_per_hr"] = int(round(20 + perf * 40))

    def _release_due_diagnostics(self, state: dict[str, Any], now: int, events: list[dict[str, Any]]) -> None:
        case_def = state.get("case_definition_inline", {})
        hidden_truth = case_def.get("hidden_truth", {}) if isinstance(case_def, dict) else {}
        for order in state.get("orders", []):
            payload = order.get("payload", {})
            if payload.get("status") != "pending":
                continue
            if payload.get("result_available_at_sec", 10**12) > now:
                continue
            diag_id = payload.get("diagnostic_id")
            result_map = {
                "head_ct_noncontrast": hidden_truth.get("head_ct_result_if_ordered", "No acute intracranial process."),
                "mri_brain": hidden_truth.get("mri_brain_result_if_ordered", "No MRI result configured."),
                "ecg": case_def.get("initial_state", {}).get("monitor", {}).get("ecg_text", "ECG result unavailable."),
                "cmp": f"Creatinine {state.get('labs', {}).get('creatinine_mg_dl', 'NA')}, electrolytes otherwise unremarkable.",
                "troponin": f"Troponin {state.get('labs', {}).get('troponin_ng_l', 'NA')}.",
                "pregnancy_test": hidden_truth.get("pregnancy_test_if_ordered", "Negative."),
                "urinalysis": hidden_truth.get("ua_if_ordered", "Unremarkable."),
            }
            payload["status"] = "resulted"
            payload["result_text"] = result_map.get(diag_id, "Result available.")
            events.append(self._evt(now, "diagnostic_result_available", "info", f"Result available for {diag_id}.", {"diagnostic_id": diag_id, "result_text": payload["result_text"]}))

    # --------------------
    # Scoring and harm
    # --------------------

    def _evaluate_critical_actions(self, state: dict[str, Any]) -> list[str]:
        runtime = state.setdefault("scoring", {}).setdefault("runtime_flags", {})
        completed: list[str] = []

        if not runtime.get("recognize_htn_emergency") and self._assessment_documented(state, "hypertensive_emergency_or_hypertensive_encephalopathy"):
            runtime["recognize_htn_emergency"] = True
            completed.append("recognize_htn_emergency")

        if not runtime.get("establish_monitoring"):
            nibp = state.get("monitor", {}).get("nibp_cycle_sec")
            if nibp is not None and nibp <= 300:
                runtime["establish_monitoring"] = True
                completed.append("establish_monitoring")

        if not runtime.get("start_titratable_iv_agent"):
            if any(m.get("medication_id") in {"nicardipine_iv", "clevidipine_iv", "labetalol_iv"} for m in state.get("active_medications", [])):
                runtime["start_titratable_iv_agent"] = True
                completed.append("start_titratable_iv_agent")

        if not runtime.get("order_neuro_workup"):
            if any(o.get("payload", {}).get("diagnostic_id") == "head_ct_noncontrast" for o in state.get("orders", [])):
                runtime["order_neuro_workup"] = True
                completed.append("order_neuro_workup")

        if not runtime.get("reassess_neuro_status"):
            reassessment_types = {o.get("payload", {}).get("reassessment_type") for o in state.get("orders", []) if o.get("order_type") == "note"}
            if "neurologic_reassessment" in reassessment_types and "hemodynamic_reassessment" in reassessment_types:
                runtime["reassess_neuro_status"] = True
                completed.append("reassess_neuro_status")

        if not runtime.get("disposition"):
            if any(o.get("payload", {}).get("disposition") == "icu_admission" for o in state.get("orders", [])):
                runtime["disposition"] = True
                completed.append("disposition")

        if not runtime.get("avoid_overcorrection"):
            starting_map = state.get("case_runtime", {}).get("starting_map", state.get("hemodynamics", {}).get("map", 0))
            current_map = state.get("hemodynamics", {}).get("map", 0)
            if starting_map:
                drop_fraction = (starting_map - current_map) / starting_map
                if drop_fraction <= 0.25:
                    runtime["avoid_overcorrection"] = True
                    completed.append("avoid_overcorrection")

        return completed

    def _evaluate_harm_events(self, state: dict[str, Any], now: int) -> tuple[list[str], list[dict[str, Any]]]:
        runtime = state.setdefault("scoring", {}).setdefault("harm_runtime_flags", {})
        hemo = state.get("hemodynamics", {})
        neuro = state.get("neurologic", {})
        events: list[dict[str, Any]] = []
        harms: list[str] = []

        starting_map = state.get("case_runtime", {}).get("starting_map", hemo.get("map", 0))
        current_map = float(hemo.get("map", 0))
        drop_fraction = 0.0 if not starting_map else max(0.0, (starting_map - current_map) / starting_map)

        if drop_fraction > 0.25 and not runtime.get("rapid_overcorrection"):
            runtime["rapid_overcorrection"] = True
            harms.append("rapid_overcorrection")
            events.append(self._evt(now, "harm_event_triggered", "critical", "Rapid overcorrection triggered cerebral hypoperfusion harm event.", {"harm_event_id": "rapid_overcorrection"}))

        if float(hemo.get("hr", 100)) < 45 and current_map < 65 and not runtime.get("iatrogenic_bradycardic_hypoperfusion"):
            runtime["iatrogenic_bradycardic_hypoperfusion"] = True
            harms.append("iatrogenic_bradycardic_hypoperfusion")
            events.append(self._evt(now, "harm_event_triggered", "high", "Bradycardic hypoperfusion harm event triggered.", {"harm_event_id": "iatrogenic_bradycardic_hypoperfusion"}))

        if neuro.get("mental_status") == "seizing" and not runtime.get("progression_to_seizure"):
            runtime["progression_to_seizure"] = True
            harms.append("progression_to_seizure")
            events.append(self._evt(now, "harm_event_triggered", "critical", "Uncontrolled disease progression caused seizure.", {"harm_event_id": "progression_to_seizure"}))

        if not runtime.get("missed_hypertensive_emergency") and state.get("case_metadata", {}).get("time_elapsed_sec", 0) >= 1200:
            if not any(m.get("medication_id") in {"nicardipine_iv", "clevidipine_iv", "labetalol_iv"} for m in state.get("active_medications", [])):
                runtime["missed_hypertensive_emergency"] = True
                harms.append("missed_hypertensive_emergency")
                events.append(self._evt(now, "harm_event_triggered", "high", "Delay in IV therapy triggered missed hypertensive emergency harm event.", {"harm_event_id": "missed_hypertensive_emergency"}))

        return harms, events

    # --------------------
    # Utility helpers
    # --------------------

    def _find_active_med(self, state: dict[str, Any], med_id: str | None, include_inactive: bool = False) -> dict[str, Any] | None:
        if med_id is None:
            return None
        for med in state.get("active_medications", []):
            if med.get("medication_id") == med_id and (include_inactive or med.get("active", False)):
                return med
        return None

    def _bolus_to_effect(self, med_id: str, dose: float) -> float:
        if med_id == "labetalol_iv":
            return dose / 40.0
        if med_id == "esmolol_iv":
            return dose / 50.0
        return dose / 20.0

    def _infusion_to_effect(self, med_id: str, rate: float, dt_sec: int) -> float:
        dt_min = dt_sec / 60.0
        if med_id == "nicardipine_iv":
            return rate * 0.06 * dt_min
        if med_id == "clevidipine_iv":
            return rate * 0.18 * dt_min
        if med_id == "labetalol_iv":
            return rate * 0.10 * dt_min
        if med_id == "esmolol_iv":
            return rate * 0.02 * dt_min
        if med_id == "nitroglycerin_iv":
            return rate * 0.015 * dt_min
        if med_id == "nitroprusside_iv":
            return rate * 0.20 * dt_min
        return rate * 0.05 * dt_min

    def _infusion_dose_increment(self, med_id: str, rate: float, dt_sec: int) -> float:
        hours = dt_sec / 3600.0
        if med_id in {"nicardipine_iv", "clevidipine_iv"}:
            return rate * hours
        if med_id == "labetalol_iv":
            return rate * (dt_sec / 60.0)
        if med_id == "esmolol_iv":
            return rate * (dt_sec / 60.0)
        return rate * hours

    def _washout_factor(self, med_id: str, dt_sec: int) -> float:
        dt_min = dt_sec / 60.0
        half_life_min = {
            "nicardipine_iv": 30,
            "clevidipine_iv": 3,
            "labetalol_iv": 45,
            "esmolol_iv": 5,
            "nitroglycerin_iv": 3,
            "nitroprusside_iv": 2,
        }.get(med_id, 15)
        return 0.5 ** (dt_min / half_life_min)

    def _assessment_documented(self, state: dict[str, Any], concept: str) -> bool:
        for order in state.get("orders", []):
            payload = order.get("payload", {})
            if payload.get("assessment_concept") == concept:
                return True
        return False

    def _recompute_monitor(self, state: dict[str, Any]) -> None:
        monitor = state.setdefault("monitor", {})
        hemo = state.get("hemodynamics", {})
        resp = state.get("respiratory", {})
        flags: list[str] = []
        if hemo.get("sbp", 0) > 180:
            flags.append("hypertension_alarm")
        if hemo.get("map", 999) < 65:
            flags.append("hypotension_alarm")
        if hemo.get("hr", 0) < 50:
            flags.append("bradyarrhythmia")
        if hemo.get("hr", 0) > 120:
            flags.append("tachyarrhythmia")
        if resp.get("spo2", 100) < 90:
            flags.append("desaturation_alarm")
        monitor["waveform_flags"] = flags

    def _append_events_to_log(self, state: dict[str, Any], events: list[dict[str, Any]]) -> None:
        for event in events:
            state.setdefault("event_log", []).append(
                {
                    "time_sec": event["timeSec"],
                    "event_type": event["eventType"],
                    "summary": event["summary"],
                    "structured_data": event.get("structuredData", {}),
                }
            )

    def _build_delta(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        def delta_num(a: Any, b: Any) -> dict[str, Any]:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return {"before": a, "after": b, "delta": round(b - a, 4)}
            return {"before": a, "after": b, "delta": None}

        hemo_before = before.get("hemodynamics", {})
        hemo_after = after.get("hemodynamics", {})
        neuro_before = before.get("neurologic", {})
        neuro_after = after.get("neurologic", {})
        renal_before = before.get("renal", {})
        renal_after = after.get("renal", {})
        disease_before = before.get("disease_model", {})
        disease_after = after.get("disease_model", {})

        return {
            "hemodynamics": {
                "sbp": delta_num(hemo_before.get("sbp"), hemo_after.get("sbp")),
                "dbp": delta_num(hemo_before.get("dbp"), hemo_after.get("dbp")),
                "map": delta_num(hemo_before.get("map"), hemo_after.get("map")),
                "hr": delta_num(hemo_before.get("hr"), hemo_after.get("hr")),
                "rhythm": delta_num(hemo_before.get("rhythm"), hemo_after.get("rhythm")),
            },
            "neurologic": {
                "gcs": delta_num(neuro_before.get("gcs"), neuro_after.get("gcs")),
                "mental_status": delta_num(neuro_before.get("mental_status"), neuro_after.get("mental_status")),
                "headache_index": delta_num(neuro_before.get("headache_index"), neuro_after.get("headache_index")),
                "vision_change_index": delta_num(neuro_before.get("vision_change_index"), neuro_after.get("vision_change_index")),
                "cerebral_hypoperfusion_index": delta_num(neuro_before.get("cerebral_hypoperfusion_index"), neuro_after.get("cerebral_hypoperfusion_index")),
            },
            "renal": {
                "urine_output_ml_per_hr": delta_num(renal_before.get("urine_output_ml_per_hr"), renal_after.get("urine_output_ml_per_hr")),
                "renal_perfusion_index": delta_num(renal_before.get("renal_perfusion_index"), renal_after.get("renal_perfusion_index")),
            },
            "disease_model": {
                "cerebral_edema_index": delta_num(disease_before.get("cerebral_edema_index"), disease_after.get("cerebral_edema_index")),
            },
            "active_medications": after.get("active_medications", []),
        }

    def _evt(self, now: int, event_type: str, severity: str, summary: str, structured_data: dict[str, Any]) -> dict[str, Any]:
        safe_type = event_type.replace("-", "_")
        return {
            "eventId": f"evt_{safe_type}_{now}_{abs(hash(summary)) % 10000}",
            "timeSec": now,
            "eventType": event_type,
            "severity": severity,
            "summary": summary,
            "structuredData": structured_data,
        }
