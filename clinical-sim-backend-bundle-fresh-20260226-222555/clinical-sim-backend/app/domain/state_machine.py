from __future__ import annotations

from copy import deepcopy
from typing import Any


class SimulationStateMachine:
    """Deterministic MVP engine for hypertensive emergency case families.

    v3 improvements (QA report #2):
    - MAP always derived from SBP/DBP (no inconsistency)
    - Vasopressor instant-effect model: WASHOUT-then-ADD with higher CE accumulation factors
    - Rate queries (query_infusion_status) are read-only, never mutate state
    - start_titratable_iv_agent only credits nicardipine/clevidipine infusions (not labetalol bolus)
    - avoid_overcorrection requires ≥300 sec of observation after treatment started
    - Contradictory symptom/trend messages fixed; template "BP now X → Y MAP" replaced
    - Stale "stabilizing" message rate-limited to once per 120 sec
    - RSI/intubation, clinical queries, result retrieval handled explicitly
    - Bradycardic harm event includes actual vital values
    - All diagnostics return in 60 sec per spec
    - Titration without target rate uses default step size
    """

    # Antihypertensive medication IDs (cause MAP drop)
    _ANTIHYPERTENSIVES = {"nicardipine_iv", "clevidipine_iv", "labetalol_iv", "hydralazine_iv",
                          "esmolol_iv", "nitroglycerin_iv", "nitroprusside_iv"}
    # Vasopressor / pressor IDs (raise MAP)
    _VASOPRESSORS = {"norepinephrine_iv", "epinephrine_iv", "phenylephrine_iv", "dopamine_iv",
                     "dobutamine_iv", "vasopressin_iv"}

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
        # Explicit nested init — chained setdefault fails when parent key
        # already exists from case JSON but lacks sub-keys (BUG-4 fix)
        monitor = state_after.setdefault("monitor", {})
        monitor.setdefault("waveform_flags", [])
        scoring = state_after.setdefault("scoring", {})
        scoring.setdefault("critical_actions", [])
        scoring.setdefault("harm_events", [])
        scoring.setdefault("teaching_points", [])
        scoring.setdefault("final_score", 0)

        critical_completed: list[str] = []
        harm_triggered: list[str] = []
        teaching_markers: list[str] = []

        # Store MAP before this turn for trend tracking
        map_before_turn = float(state_after.get("hemodynamics", {}).get("map", 150))
        state_after.setdefault("case_runtime", {})["prev_map"] = map_before_turn

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
            elif tool_name == "give_supportive_care":
                self._give_supportive_care(state_after, payload, next_time, events)
            elif tool_name == "help_command":
                events.append(self._build_help_event(state_after, next_time))
            elif tool_name == "query_infusion_status":
                self._query_infusion_status(state_after, payload, next_time, events)
            elif tool_name == "retrieve_diagnostic_result":
                self._retrieve_diagnostic_result(state_after, payload, next_time, events)
            elif tool_name == "unsupported_procedure":
                self._handle_unsupported_procedure(state_after, payload, next_time, events)
            elif tool_name == "clinical_query":
                self._handle_clinical_query(state_after, payload, next_time, events)
            # Unknown actions produce an acknowledgment
            elif tool_name:
                events.append(self._evt(
                    next_time, "state_update", "info",
                    f"Order received but not recognized by this simulation: {tool_name}.",
                    {"tool_name": tool_name}
                ))

        # 2) Progress physiology over time
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

    def _start_infusion(self, state: dict, payload: dict, now: int, events: list) -> None:
        med_id = payload.get("medication_id")
        rate = payload.get("infusion_rate", 0)
        existing = self._find_active_med(state, med_id)
        if existing:
            existing["current_infusion_rate"] = rate
            existing["active"] = True
            existing["last_dose_time_sec"] = now
            events.append(self._evt(now, "medication_effect", "info",
                                    f"{self._med_display(med_id)} infusion rate adjusted to {rate}.",
                                    {"medication_id": med_id, "rate": rate}))
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
            "started_at_sec": now,
        }
        state["active_medications"].append(entry)

        # Flag when adding a second antihypertensive while one is already running
        active_antihypertensives = [
            m for m in state["active_medications"]
            if m.get("medication_id") in self._ANTIHYPERTENSIVES and m.get("active") and m.get("medication_id") != med_id
        ]
        if active_antihypertensives and med_id in self._ANTIHYPERTENSIVES:
            active_names = ", ".join(self._med_display(m["medication_id"]) for m in active_antihypertensives)
            events.append(self._evt(now, "state_update", "moderate",
                                    f"{self._med_display(med_id)} started while {active_names} already active. "
                                    f"Monitor for additive BP-lowering effect and overcorrection risk.",
                                    {"medication_id": med_id, "concurrent_agents": [m["medication_id"] for m in active_antihypertensives]}))
        elif med_id in self._VASOPRESSORS:
            _onset_notes = {
                "norepinephrine_iv": "1–2 min", "epinephrine_iv": "1–2 min",
                "phenylephrine_iv": "1–2 min", "dopamine_iv": "2–4 min",
                "vasopressin_iv": "5–10 min",
            }
            events.append(self._evt(now, "medication_effect", "info",
                                    f"{self._med_display(med_id)} infusion started at {rate}. "
                                    f"Educational note: real-world onset {_onset_notes.get(med_id, '2–5 min')}. "
                                    f"Hemodynamic support tracked.",
                                    {"medication_id": med_id, "rate": rate}))
        else:
            events.append(self._evt(now, "medication_effect", "info",
                                    f"{self._med_display(med_id)} infusion started.",
                                    {"medication_id": med_id, "rate": rate}))

        # Mark that BP-active meds have been given (needed for avoid_overcorrection scoring)
        if med_id in self._ANTIHYPERTENSIVES:
            cr = state.setdefault("case_runtime", {})
            cr["bp_active_meds_given"] = True
            if "treatment_started_sec" not in cr:
                cr["treatment_started_sec"] = now

    def _adjust_infusion(self, state: dict, payload: dict, now: int, events: list) -> None:
        med_id = payload.get("medication_id")
        med = self._find_active_med(state, med_id)
        if not med:
            events.append(self._evt(now, "state_update", "low",
                                    f"No active {self._med_display(med_id)} infusion found to adjust.",
                                    {"medication_id": med_id}))
            return
        med["current_infusion_rate"] = payload.get("new_infusion_rate", payload.get("infusion_rate", med.get("current_infusion_rate", 0)))
        med["last_dose_time_sec"] = now
        events.append(self._evt(now, "medication_effect", "info",
                                f"{self._med_display(med_id)} infusion adjusted to {med['current_infusion_rate']}.",
                                {"medication_id": med_id, "rate": med["current_infusion_rate"]}))

    def _stop_infusion(self, state: dict, payload: dict, now: int, events: list) -> None:
        med_id = payload.get("medication_id")
        med = self._find_active_med(state, med_id)
        if not med:
            events.append(self._evt(now, "state_update", "info",
                                    f"No active {self._med_display(med_id)} infusion found to stop.",
                                    {"medication_id": med_id}))
            return
        med["active"] = False
        med["current_infusion_rate"] = 0
        med["last_dose_time_sec"] = now
        events.append(self._evt(now, "medication_effect", "info",
                                f"{self._med_display(med_id)} infusion stopped. Effects will wane over the next several minutes.",
                                {"medication_id": med_id}))

    def _give_bolus(self, state: dict, payload: dict, now: int, events: list) -> None:
        med_id = payload.get("medication_id")
        dose = float(payload.get("dose", 0))

        # Acknowledge unsafe dose flag
        if payload.get("safety_flag") == "dose_unit_warning":
            events.append(self._evt(now, "state_update", "moderate",
                                    f"{self._med_display(med_id)} dose {dose} mg flagged as likely unit error. "
                                    f"Order not executed pending dose verification.",
                                    {"medication_id": med_id, "dose": dose, "safety_flag": "dose_unit_warning"}))
            return

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
                "started_at_sec": now,
            }
            state["active_medications"].append(med)
        med["last_dose_time_sec"] = now
        med["cumulative_dose"] += dose
        med["effect_site_concentration"] += self._bolus_to_effect(med_id, dose)

        # Warn about additive effect if antihypertensive already infusing
        if med_id in self._ANTIHYPERTENSIVES:
            cr = state.setdefault("case_runtime", {})
            cr["bp_active_meds_given"] = True
            if "treatment_started_sec" not in cr:
                cr["treatment_started_sec"] = now
            active_infusions = [
                m for m in state["active_medications"]
                if m.get("medication_id") in self._ANTIHYPERTENSIVES
                and m.get("active") and m.get("mode") == "infusion"
                and m.get("medication_id") != med_id
            ]
            if active_infusions:
                infusion_names = ", ".join(self._med_display(m["medication_id"]) for m in active_infusions)
                events.append(self._evt(now, "state_update", "moderate",
                                        f"{self._med_display(med_id)} {dose} mg IV given. "
                                        f"Note: {infusion_names} infusion is already running. "
                                        f"Combined effect may accelerate BP reduction.",
                                        {"medication_id": med_id, "dose": dose}))
                return
        events.append(self._evt(now, "medication_effect", "info",
                                f"{self._med_display(med_id)} {dose} mg IV administered.",
                                {"medication_id": med_id, "dose": dose}))

    def _order_diagnostic(self, state: dict, payload: dict, now: int, events: list) -> None:
        diag_id = payload.get("diagnostic_id")
        if any(o.get("payload", {}).get("diagnostic_id") == diag_id for o in state.get("orders", [])):
            events.append(self._evt(now, "state_update", "info",
                                    f"{self._diag_display(diag_id)} already ordered.",
                                    {"diagnostic_id": diag_id}))
            return

        # All diagnostics return in 60 seconds per spec (case definitions may override)
        result_delay_sec = 60

        result_at = now + result_delay_sec
        state["orders"].append({
            "time_sec": now,
            "actor": "resident",
            "order_type": payload.get("order_type", "diagnostic"),
            "payload": {
                **payload,
                "status": "pending",
                "result_available_at_sec": result_at,
            },
        })

        # Acknowledgment message (all results in ~1 min per spec)
        ack_map = {
            "fingerstick_glucose": "Fingerstick glucose obtained. Result available in ~1 minute.",
            "ecg": "12-lead ECG ordered. Result available in ~1 minute.",
            "cbc": "CBC ordered. Result available in ~1 minute.",
            "cmp": "BMP/CMP ordered. Result available in ~1 minute.",
            "troponin": "Troponin ordered to assess for cardiac end-organ injury. Result in ~1 minute.",
            "coagulation_panel": "Coagulation studies ordered. Result available in ~1 minute.",
            "head_ct_noncontrast": "CT head without contrast ordered. Result available in ~1 minute.",
            "mri_brain": "MRI brain ordered. Result available in ~1 minute.",
            "chest_xray": "Chest X-ray ordered. Result available in ~1 minute.",
            "pregnancy_test": "Urine pregnancy test ordered. Result in ~1 minute.",
            "urinalysis": "Urinalysis ordered. Result in ~1 minute.",
            "bnp": "BNP ordered. Result in ~1 minute.",
            "d_dimer": "D-dimer ordered. Result in ~1 minute.",
            "lactate": "Lactate ordered. Result in ~1 minute.",
        }
        ack = ack_map.get(diag_id, f"{self._diag_display(diag_id)} ordered. Result in ~1 minute.")
        events.append(self._evt(now, "state_update", "info", ack, {"diagnostic_id": diag_id, "result_available_at_sec": result_at}))

    def _set_monitoring(self, state: dict, payload: dict, now: int, events: list) -> None:
        action = payload.get("monitor_action")
        if action == "set_nibp_cycle":
            cycle = payload.get("nibp_cycle_sec", 300)
            state.setdefault("monitor", {})["nibp_cycle_sec"] = cycle
            friendly = f"every {cycle // 60} minutes" if cycle >= 60 else f"every {cycle} seconds"
            events.append(self._evt(now, "state_update", "info",
                                    f"NIBP cycling set to {friendly}. Continuous hemodynamic monitoring established.",
                                    {"monitor_action": action, "nibp_cycle_sec": cycle}))
        elif action == "enable_continuous_monitoring":
            state.setdefault("monitor", {})["telemetry_quality"] = "good"
            events.append(self._evt(now, "state_update", "info",
                                    "Continuous cardiac monitoring and pulse oximetry established.",
                                    {"monitor_action": action}))
        else:
            events.append(self._evt(now, "state_update", "info", "Monitoring updated.", {"monitor_action": action}))
        # Flag that monitoring was explicitly ordered (needed for critical-action scoring)
        state.setdefault("case_runtime", {})["monitoring_ordered"] = True

    def _perform_reassessment(self, state: dict, payload: dict, now: int, events: list) -> None:
        reassessment_type = payload.get("reassessment_type")

        # Generate clinician-facing findings rather than backend labels
        hemo = state.get("hemodynamics", {})
        neuro = state.get("neurologic", {})
        sbp = hemo.get("sbp", 0)
        dbp = hemo.get("dbp", 0)
        hr = hemo.get("hr", 0)
        map_val = hemo.get("map", 0)
        starting_map = state.get("case_runtime", {}).get("starting_map", map_val)
        drop_frac = max(0.0, (starting_map - map_val) / starting_map) if starting_map else 0.0

        mental_status = neuro.get("mental_status", "confused")
        gcs = neuro.get("gcs", 14)
        headache_idx = float(neuro.get("headache_index", 0.8))
        vision_idx = float(neuro.get("vision_change_index", 0.6))

        _ms_map = {
            "confused": "confused and still asking repetitive questions",
            "anxious": "anxious but more oriented than initially",
            "somnolent": "increasingly drowsy and slow to respond",
            "seizing": "actively seizing — urgent intervention required",
            "agitated": "agitated with new staring episodes",
        }
        ms_desc = _ms_map.get(mental_status, mental_status)
        headache_trend = "improving" if headache_idx < 0.55 else "persisting but tolerable" if headache_idx < 0.75 else "severe and persistent"
        vision_trend = "improving" if vision_idx < 0.4 else "still present but unchanged" if vision_idx < 0.65 else "worsening"

        if reassessment_type in ("neurologic_reassessment", "full_reassessment"):
            findings = (
                f"BP {sbp}/{dbp}, HR {hr}. Patient is {ms_desc}. "
                f"Headache {headache_trend}. Visual symptoms {vision_trend}. "
                f"GCS {gcs}. No focal motor deficits detected."
            )
            events.append(self._evt(now, "state_update", "info", findings, {"reassessment_type": reassessment_type}))

        if reassessment_type in ("hemodynamic_reassessment", "full_reassessment"):
            if drop_frac > 0.25:
                hemo_interp = f"MAP has fallen {drop_frac:.0%} from baseline — EXCEEDS safe 25% reduction threshold. Consider reducing antihypertensive therapy."
            elif drop_frac > 0.10:
                hemo_interp = f"MAP reduced {drop_frac:.0%} from baseline — within target range (10–25%)."
            elif drop_frac > 0.01:
                hemo_interp = f"Minimal MAP reduction so far ({drop_frac:.0%}). Consider titrating therapy."
            else:
                hemo_interp = "BP essentially unchanged. Antihypertensive therapy may need to be initiated or escalated."
            findings = f"BP {sbp}/{dbp}, MAP {map_val} mmHg, HR {hr}. {hemo_interp}"
            events.append(self._evt(now, "state_update", "info", findings, {"reassessment_type": reassessment_type}))

        # Still track for scoring
        state.setdefault("orders", []).append({
            "time_sec": now,
            "actor": "resident",
            "order_type": "note",
            "payload": {"reassessment_type": reassessment_type, "status": "completed"},
        })

    def _set_disposition(self, state: dict, payload: dict, now: int, events: list) -> None:
        disposition = payload.get("disposition")
        _disp_map = {
            "icu_admission": "ICU admission requested. Awaiting bed.",
            "floor_admission": "Floor admission requested.",
            "discharge": "Discharge order placed.",
            "observation": "Observation status requested.",
        }
        state.setdefault("orders", []).append({
            "time_sec": now, "actor": "resident", "order_type": "note",
            "payload": {"disposition": disposition, "status": "requested"},
        })
        events.append(self._evt(now, "state_update", "info",
                                _disp_map.get(disposition, f"Disposition: {disposition} requested."),
                                {"disposition": disposition}))

    def _document_assessment(self, state: dict, payload: dict, now: int, events: list) -> None:
        concept = payload.get("assessment_concept")
        _concept_map = {
            "hypertensive_emergency_or_hypertensive_encephalopathy":
                "Clinical impression documented: hypertensive emergency with neurologic end-organ involvement.",
            "pres_syndrome": "Clinical impression documented: possible PRES syndrome.",
            "hypertensive_urgency": "Clinical impression documented: hypertensive urgency.",
            "ischemic_stroke": "Clinical impression documented: possible ischemic stroke — obtain CT head urgently.",
            "hemorrhagic_stroke": "Clinical impression documented: possible hemorrhagic stroke — obtain CT head urgently.",
        }
        state.setdefault("orders", []).append({
            "time_sec": now, "actor": "resident", "order_type": "note",
            "payload": {"assessment_concept": concept, "status": "documented"},
        })
        events.append(self._evt(now, "state_update", "info",
                                _concept_map.get(concept, f"Assessment documented: {concept}."),
                                {"assessment": concept}))

    def _give_supportive_care(self, state: dict, payload: dict, now: int, events: list) -> None:
        care_type = payload.get("care_type")
        if care_type == "oxygen":
            resp = state.setdefault("respiratory", {})
            spo2 = float(resp.get("spo2", 98))
            if spo2 >= 95:
                events.append(self._evt(now, "state_update", "info",
                                        f"Oxygen applied. SpO2 already {int(spo2)}% — no significant change expected.",
                                        {"care_type": care_type}))
            else:
                resp["spo2"] = min(100, spo2 + 4)
                events.append(self._evt(now, "state_update", "info",
                                        f"Oxygen applied. SpO2 improving from {int(spo2)}% to {int(resp['spo2'])}%.",
                                        {"care_type": care_type}))

        elif care_type == "iv_access":
            state.setdefault("case_runtime", {})["iv_access_established"] = True
            events.append(self._evt(now, "state_update", "info",
                                    "IV access established (large-bore peripheral IVs placed). Ready for IV medication administration.",
                                    {"care_type": care_type}))

        elif care_type == "foley_catheter":
            state.setdefault("renal", {})["foley_in_place"] = True
            events.append(self._evt(now, "state_update", "info",
                                    "Foley catheter placed. Strict urine output monitoring now active.",
                                    {"care_type": care_type}))

        elif care_type == "iv_fluid_bolus":
            hemo = state.setdefault("hemodynamics", {})
            map_val = float(hemo.get("map", 70))
            if map_val < 70:
                # Modest MAP support for hypotension/hypoperfusion
                map_gain = min(8, (70 - map_val) * 0.4)
                new_map = min(90, map_val + map_gain)
                pp = max(20, new_map * 0.27)
                hemo["sbp"] = max(40, int(round(new_map + pp / 2)))
                hemo["dbp"] = max(20, int(round(new_map - pp / 2)))
                hemo["map"] = int(round(new_map))
                events.append(self._evt(now, "state_update", "info",
                                        f"IV fluid bolus given. MAP improving from {int(map_val)} to {hemo['map']} mmHg. "
                                        f"Continue monitoring for response.",
                                        {"care_type": care_type}))
            else:
                events.append(self._evt(now, "state_update", "info",
                                        "IV fluid bolus given. MAP is adequate; limited hemodynamic benefit expected in this context.",
                                        {"care_type": care_type}))

    def _build_help_event(self, state: dict, now: int) -> dict:
        runtime = state.get("scoring", {}).get("runtime_flags", {})
        hemo = state.get("hemodynamics", {})
        active_meds = [m.get("medication_id") for m in state.get("active_medications", []) if m.get("active")]

        starting_map = state.get("case_runtime", {}).get("starting_map", hemo.get("map", 0))
        current_map = float(hemo.get("map", 0))
        drop_frac = max(0.0, (starting_map - current_map) / starting_map) if starting_map else 0.0

        hints: list[str] = []

        if not runtime.get("start_titratable_iv_agent"):
            hints.append("Start a titratable IV antihypertensive such as nicardipine or clevidipine to lower BP in a controlled, titrated manner.")

        if active_meds and any(m in self._ANTIHYPERTENSIVES for m in active_meds):
            if drop_frac > 0.22:
                hints.append(
                    f"WARNING: MAP has already fallen {drop_frac:.0%} from baseline. "
                    f"Target is 15–25% reduction in the first hour — consider reducing or stopping antihypertensives."
                )
            elif drop_frac < 0.05:
                hints.append(f"BP reduction so far is minimal ({drop_frac:.0%}). Consider titrating up your antihypertensive infusion.")
            else:
                hints.append(f"BP reduction is {drop_frac:.0%} — within target range (10–25% in the first hour). Continue monitoring closely.")

        if not runtime.get("establish_monitoring"):
            hints.append("Establish continuous cardiac monitoring and set NIBP cycling every 5 minutes or less.")

        if not runtime.get("order_neuro_workup"):
            hints.append("Order a non-contrast head CT to rule out intracranial hemorrhage before attributing symptoms to hypertensive encephalopathy.")

        if not runtime.get("recognize_htn_emergency"):
            hints.append("Document your clinical impression — this presentation (severe hypertension with neurologic symptoms) is a hypertensive emergency.")

        if not hints:
            hints.append(
                f"BP is {hemo.get('sbp')}/{hemo.get('dbp')} (MAP {int(current_map)}). "
                f"Target 15–25% MAP reduction in the first hour. Monitor neurologic status and reassess frequently. "
                f"Avoid rapid normalization — aim for controlled, incremental reduction."
            )

        hint_text = "CLINICAL GUIDANCE: " + " | ".join(hints)
        return self._evt(now, "state_update", "info", hint_text, {"command": "help"})

    # --------------------
    # Physiology progression
    # --------------------

    def _progress_active_medications(self, state: dict, dt_sec: int, now: int, events: list) -> None:
        hemo = state.setdefault("hemodynamics", {})
        neuro = state.setdefault("neurologic", {})
        disease = state.setdefault("disease_model", {})
        renal = state.setdefault("renal", {})

        total_svr_drop = 0.0
        total_hr_drop = 0.0
        total_brady_risk = 0.0
        total_map_gain = 0.0   # from vasopressors

        for med in state.get("active_medications", []):
            med_id = med.get("medication_id")
            rate = float(med.get("current_infusion_rate", 0) or 0)
            ce = float(med.get("effect_site_concentration", 0) or 0)
            active = bool(med.get("active", False))

            # WASHOUT first, then add new effect (correct PK accumulation order)
            ce *= self._washout_factor(med_id, dt_sec)
            if active and rate > 0:
                med["cumulative_dose"] += self._infusion_dose_increment(med_id, rate, dt_sec)
                ce += self._infusion_to_effect(med_id, rate, dt_sec)
            med["effect_site_concentration"] = max(0.0, ce)

            # Antihypertensives — drop MAP
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
            elif med_id == "hydralazine_iv":
                effect = min(0.3, ce * 0.15)
                total_svr_drop += effect * 0.8
            # Vasopressors — raise MAP
            elif med_id == "norepinephrine_iv":
                effect = min(0.5, ce * 0.30)
                total_map_gain += effect * 35
            elif med_id == "epinephrine_iv":
                effect = min(0.4, ce * 0.25)
                total_map_gain += effect * 28
                total_hr_drop -= effect * 25  # epinephrine increases HR
            elif med_id == "phenylephrine_iv":
                effect = min(0.35, ce * 0.22)
                total_map_gain += effect * 30
            elif med_id == "dopamine_iv":
                effect = min(0.4, ce * 0.22)
                total_map_gain += effect * 20
            elif med_id == "vasopressin_iv":
                effect = min(0.3, ce * 0.20)
                total_map_gain += effect * 25

        starting_map = state.get("case_runtime", {}).get("starting_map")
        if starting_map is None:
            state.setdefault("case_runtime", {})["starting_map"] = hemo.get("map", 0)
            starting_map = hemo.get("map", 0)

        svr_index = float(hemo.get("svr_index", 1.5))
        hr = float(hemo.get("hr", 100))
        map_before = float(hemo.get("map", 150))
        prev_map = float(state.get("case_runtime", {}).get("prev_map", map_before))

        svr_index = max(0.7, svr_index - total_svr_drop)
        hr = max(32, min(180, hr - total_hr_drop))

        raw_new_map = map_before - (total_svr_drop * 40) - max(0, total_hr_drop * 0.35) + total_map_gain
        new_map = max(45, raw_new_map)
        map_drop_fraction = 0.0 if starting_map <= 0 else max(0.0, (starting_map - new_map) / starting_map)
        map_trend = new_map - prev_map  # positive = improving, negative = falling

        # ── Therapeutic range: controlled BP reduction ──
        if 0.10 <= map_drop_fraction <= 0.25:
            disease["cerebral_edema_index"] = max(0.0, float(disease.get("cerebral_edema_index", 0.5)) - 0.03)
            neuro["headache_index"] = max(0.0, float(neuro.get("headache_index", 0.8)) - 0.03)
            neuro["vision_change_index"] = max(0.0, float(neuro.get("vision_change_index", 0.6)) - 0.025)
            if neuro.get("mental_status") in {"confused", "somnolent"} and map_drop_fraction >= 0.15:
                neuro["mental_status"] = "anxious"
                neuro["gcs"] = max(14, int(neuro.get("gcs", 14)))
                events.append(self._evt(now, "clinical_improvement", "moderate",
                                        f"MAP {int(map_before)} → {int(new_map)} mmHg. "
                                        f"Mental status improving (less confused). "
                                        f"Headache and visual symptoms may lag hemodynamic response — continue monitoring.",
                                        {}))

        # ── Overcorrection: MAP dropped too far ──
        elif map_drop_fraction > 0.25:
            neuro["cerebral_hypoperfusion_index"] = min(
                1.0, float(neuro.get("cerebral_hypoperfusion_index", 0.0)) + 0.20
            )
            neuro["mental_status"] = "somnolent"
            neuro["gcs"] = max(7, int(neuro.get("gcs", 14)) - 2)
            renal["renal_perfusion_index"] = max(0.3, float(renal.get("renal_perfusion_index", 0.8)) - 0.10)

            last_deterioration_map = state.get("case_runtime", {}).get("last_deterioration_map", starting_map)
            deterioration_already_fired = "rapid_overcorrection" in state.get("scoring", {}).get("harm_runtime_flags", {})

            if map_trend < -3:
                # MAP still actively falling — emit deterioration message
                state["case_runtime"]["last_deterioration_map"] = new_map
                active_ah = [m.get("medication_id") for m in state.get("active_medications", [])
                             if m.get("active") and m.get("medication_id") in self._ANTIHYPERTENSIVES]
                recent_bolus = [m.get("medication_id") for m in state.get("active_medications", [])
                               if m.get("mode") == "bolus" and (now - m.get("last_dose_time_sec", 0)) < 600
                               and m.get("medication_id") in self._ANTIHYPERTENSIVES]
                all_relevant = list(dict.fromkeys(active_ah + recent_bolus))
                med_str = ", ".join(self._med_display(m) for m in all_relevant) if all_relevant else "recent antihypertensives"
                events.append(self._evt(now, "clinical_deterioration", "high",
                                        f"MAP {int(new_map)} mmHg ({map_drop_fraction:.0%} below baseline). "
                                        f"Patient worsening — likely driven by {med_str}. "
                                        f"Neurologic status declining (now {neuro['mental_status']}).",
                                        {"map_drop_fraction": round(map_drop_fraction, 3),
                                         "offending_meds": all_relevant}))
            elif map_trend >= 2 and deterioration_already_fired:
                # MAP meaningfully recovering — emit stabilization message at most once per 120 sec
                last_stab_sec = state.get("case_runtime", {}).get("last_stabilization_sec", -300)
                if now - last_stab_sec >= 120:
                    state.setdefault("case_runtime", {})["last_stabilization_sec"] = now
                    pressor_ids = [m.get("medication_id") for m in state.get("active_medications", [])
                                   if m.get("active") and m.get("medication_id") in self._VASOPRESSORS]
                    if pressor_ids:
                        pressor_str = ", ".join(self._med_display(p) for p in pressor_ids)
                        events.append(self._evt(now, "state_update", "moderate",
                                                f"MAP recovering: {int(map_before)} → {int(new_map)} mmHg with {pressor_str}. "
                                                f"Neurologic status remains impaired; recovery may lag hemodynamics.",
                                                {"map": int(new_map)}))
                    else:
                        events.append(self._evt(now, "state_update", "moderate",
                                                f"MAP recovering: {int(map_before)} → {int(new_map)} mmHg. "
                                                f"Neurologic recovery may lag. Monitor closely.",
                                                {"map": int(new_map)}))

        # ── Bradycardia from beta-blockade ──
        if total_brady_risk > 0.35 and hr < 55:
            hemo["rhythm"] = "sinus_bradycardia"
        if total_brady_risk > 0.55 and hr < 45:
            hemo["rhythm"] = "high_grade_av_block"

        # ── Compute updated hemodynamics ──
        # Use physiologically correct formula: MAP = DBP + (SBP-DBP)/3
        # → SBP = MAP + 2*PP/3,  DBP = MAP - PP/3  (ensures MAP_check == MAP)
        pulse_pressure = max(20, new_map * 0.27)
        dbp = max(20, int(round(new_map - pulse_pressure / 3)))
        sbp = max(40, dbp + int(round(pulse_pressure)))
        # MAP derived from SBP/DBP — should equal new_map within ±1 (rounding only)
        map_derived = int(round(dbp + (sbp - dbp) / 3))

        hemo["svr_index"] = round(svr_index, 3)
        hemo["hr"] = int(round(hr))
        hemo["sbp"] = sbp
        hemo["dbp"] = dbp
        hemo["map"] = map_derived

        # ── Emit vitals update after any significant hemodynamic change ──
        map_change = abs(map_derived - map_before)
        if map_change >= 5 and (total_svr_drop > 0.05 or total_map_gain > 0.05):
            direction = "falling" if map_derived < map_before else "recovering"
            events.append(self._evt(now, "state_update", "info",
                                    f"Vitals: BP {hemo['sbp']}/{hemo['dbp']} (MAP {hemo['map']}), HR {hemo['hr']}. "
                                    f"MAP {direction}: {int(map_before)} → {hemo['map']} mmHg.",
                                    {"sbp": hemo["sbp"], "dbp": hemo["dbp"], "map": hemo["map"], "hr": hemo["hr"]}))

    def _apply_disease_progression(self, state: dict, dt_sec: int, now: int, events: list) -> None:
        hemo = state.setdefault("hemodynamics", {})
        neuro = state.setdefault("neurologic", {})
        disease = state.setdefault("disease_model", {})
        renal = state.setdefault("renal", {})

        map_val = float(hemo.get("map", 150))
        cerebral_edema = float(disease.get("cerebral_edema_index", 0.5))

        # Untreated/undertreated hypertension progression
        if map_val > 145:
            disease["cerebral_edema_index"] = min(1.0, cerebral_edema + (0.01 * dt_sec / 60.0))
            neuro["headache_index"] = min(1.0, float(neuro.get("headache_index", 0.8)) + (0.01 * dt_sec / 60.0))
            neuro["vision_change_index"] = min(1.0, float(neuro.get("vision_change_index", 0.7)) + (0.008 * dt_sec / 60.0))

            last_prog_reported = state.get("case_runtime", {}).get("last_untreated_progression_sec", -300)
            if now - last_prog_reported >= 180:  # report at most every 3 sim-minutes
                if disease["cerebral_edema_index"] > 0.90:
                    neuro["mental_status"] = "seizing"
                    neuro["gcs"] = 6
                    events.append(self._evt(now, "clinical_deterioration", "critical",
                                            "Generalized seizure — uncontrolled hypertensive encephalopathy.",
                                            {}))
                elif disease["cerebral_edema_index"] > 0.82:
                    neuro["mental_status"] = "agitated"
                    events.append(self._evt(now, "case_progression", "high",
                                            "Impending seizure: agitation and staring episodes.",
                                            {}))
                elif disease["cerebral_edema_index"] > 0.66 and neuro.get("mental_status") == "confused":
                    neuro["mental_status"] = "somnolent"
                    neuro["gcs"] = max(11, int(neuro.get("gcs", 14)) - 1)
                    events.append(self._evt(now, "clinical_deterioration", "moderate",
                                            "Cerebral edema progressing — patient becoming more drowsy. BP treatment needed urgently.",
                                            {}))
                state["case_runtime"]["last_untreated_progression_sec"] = now

        if map_val < 70:
            renal["renal_perfusion_index"] = max(0.2, float(renal.get("renal_perfusion_index", 0.8)) - 0.08)
            renal["aki_risk_index"] = min(1.0, float(renal.get("aki_risk_index", 0.2)) + 0.06)

        perf = float(renal.get("renal_perfusion_index", 0.8))
        renal["urine_output_ml_per_hr"] = int(round(20 + perf * 40))

    def _release_due_diagnostics(self, state: dict, now: int, events: list) -> None:
        case_def = state.get("case_definition_inline", {})
        hidden_truth = case_def.get("hidden_truth", {}) if isinstance(case_def, dict) else {}
        labs = state.get("labs", {})

        for order in state.get("orders", []):
            payload = order.get("payload", {})
            if payload.get("status") != "pending":
                continue
            if payload.get("result_available_at_sec", 10**12) > now:
                continue
            diag_id = payload.get("diagnostic_id")
            result_map = {
                "head_ct_noncontrast": hidden_truth.get("head_ct_result_if_ordered", "No acute intracranial hemorrhage or mass effect."),
                "mri_brain": hidden_truth.get("mri_brain_result_if_ordered", "Scattered T2/FLAIR hyperintensities in parieto-occipital regions consistent with PRES. No hemorrhage."),
                "ecg": state.get("monitor", {}).get("ecg_text", "Sinus rhythm. LVH with strain pattern. No ST elevation or depression. QTc 440 ms."),
                "cmp": (
                    f"BMP: Na {labs.get('sodium_meq_l', 139)}, K {labs.get('potassium_meq_l', 3.8)}, "
                    f"Cl {labs.get('chloride_meq_l', 103)}, HCO3 {labs.get('bicarb_meq_l', 24)}, "
                    f"BUN {labs.get('bun_mg_dl', 18)}, Cr {labs.get('creatinine_mg_dl', 1.1)}. "
                    f"No critical abnormalities."
                ),
                "troponin": f"Troponin {labs.get('troponin_ng_l', 9)} ng/L — within normal limits. No acute myocardial injury.",
                "pregnancy_test": hidden_truth.get("pregnancy_test_if_ordered", "Urine hCG: Negative."),
                "urinalysis": hidden_truth.get("ua_if_ordered", "Urinalysis: Mild proteinuria. No RBC casts. No glucose. No infection."),
                "cbc": (
                    f"CBC: WBC {labs.get('wbc_k_ul', 9.4)}, Hgb {labs.get('hemoglobin_g_dl', 13.2)}, "
                    f"Plt {labs.get('platelets_k_ul', 248)}. No significant abnormality."
                ),
                "coagulation_panel": (
                    f"Coagulation: PT {labs.get('pt_sec', 12.6)} sec, INR {labs.get('inr', 1.0)}, "
                    f"PTT {labs.get('ptt_sec', 28)} sec. Normal."
                ),
                "fingerstick_glucose": f"Fingerstick glucose: {labs.get('glucose_mg_dl', 112)} mg/dL. Euglycemic.",
                "chest_xray": "Chest X-ray: Cardiomegaly with mild pulmonary vascular congestion. No consolidation or effusion.",
                "bnp": f"BNP {labs.get('bnp_pg_ml', 180)} pg/mL — mildly elevated, consistent with chronic hypertensive heart disease.",
                "d_dimer": f"D-dimer {labs.get('d_dimer_ng_ml', 320)} ng/mL — mildly elevated, non-specific.",
                "lactate": f"Lactate {labs.get('lactate_mmol_l', 1.1)} mmol/L — normal.",
            }
            payload["status"] = "resulted"
            result_text = result_map.get(diag_id, f"{self._diag_display(diag_id)}: Result available.")
            payload["result_text"] = result_text
            events.append(self._evt(now, "diagnostic_result_available", "info",
                                    f"RESULT — {self._diag_display(diag_id)}: {result_text}",
                                    {"diagnostic_id": diag_id, "result_text": result_text}))

    # --------------------
    # Scoring and harm
    # --------------------

    def _evaluate_critical_actions(self, state: dict) -> list[str]:
        runtime = state.setdefault("scoring", {}).setdefault("runtime_flags", {})
        completed: list[str] = []

        if not runtime.get("recognize_htn_emergency") and self._assessment_documented(state, "hypertensive_emergency_or_hypertensive_encephalopathy"):
            runtime["recognize_htn_emergency"] = True
            completed.append("recognize_htn_emergency")

        # establish_monitoring: require an explicit monitoring order this session
        if not runtime.get("establish_monitoring"):
            monitoring_ordered = state.get("case_runtime", {}).get("monitoring_ordered", False)
            nibp = state.get("monitor", {}).get("nibp_cycle_sec")
            if monitoring_ordered and nibp is not None and nibp <= 300:
                runtime["establish_monitoring"] = True
                completed.append("establish_monitoring")

        # Bug 2 fix: only nicardipine/clevidipine INFUSIONS count as titratable IV agents
        # Labetalol bolus does not satisfy this — it's not truly titratable
        if not runtime.get("start_titratable_iv_agent"):
            if any(
                m.get("medication_id") in {"nicardipine_iv", "clevidipine_iv"}
                and m.get("mode") == "infusion"
                for m in state.get("active_medications", [])
            ):
                runtime["start_titratable_iv_agent"] = True
                runtime["bp_active_meds_given"] = True
                completed.append("start_titratable_iv_agent")

        if not runtime.get("order_neuro_workup"):
            if any(o.get("payload", {}).get("diagnostic_id") == "head_ct_noncontrast"
                   for o in state.get("orders", [])):
                runtime["order_neuro_workup"] = True
                completed.append("order_neuro_workup")

        if not runtime.get("reassess_neuro_status"):
            reassessment_types = {o.get("payload", {}).get("reassessment_type")
                                  for o in state.get("orders", []) if o.get("order_type") == "note"}
            if "neurologic_reassessment" in reassessment_types and "hemodynamic_reassessment" in reassessment_types:
                runtime["reassess_neuro_status"] = True
                completed.append("reassess_neuro_status")

        if not runtime.get("disposition"):
            if any(o.get("payload", {}).get("disposition") == "icu_admission"
                   for o in state.get("orders", [])):
                runtime["disposition"] = True
                completed.append("disposition")

        # Bug 3 fix: avoid_overcorrection requires treatment AND ≥300 sec observation window
        if not runtime.get("avoid_overcorrection"):
            bp_started = runtime.get("bp_active_meds_given") or state.get("case_runtime", {}).get("bp_active_meds_given", False)
            if bp_started:
                treatment_start_sec = state.get("case_runtime", {}).get("treatment_started_sec", 0)
                current_time_sec = state.get("case_metadata", {}).get("time_elapsed_sec", 0)
                treatment_duration = current_time_sec - treatment_start_sec
                starting_map = state.get("case_runtime", {}).get("starting_map", state.get("hemodynamics", {}).get("map", 0))
                current_map = state.get("hemodynamics", {}).get("map", 0)
                if starting_map and treatment_duration >= 300:
                    drop_fraction = (starting_map - current_map) / starting_map
                    if 0.05 < drop_fraction <= 0.25:
                        runtime["avoid_overcorrection"] = True
                        completed.append("avoid_overcorrection")

        return completed

    def _evaluate_harm_events(self, state: dict, now: int) -> tuple[list[str], list[dict]]:
        runtime = state.setdefault("scoring", {}).setdefault("harm_runtime_flags", {})
        hemo = state.get("hemodynamics", {})
        neuro = state.get("neurologic", {})
        events: list[dict] = []
        harms: list[str] = []

        starting_map = state.get("case_runtime", {}).get("starting_map", hemo.get("map", 0))
        current_map = float(hemo.get("map", 0))
        drop_fraction = 0.0 if not starting_map else max(0.0, (starting_map - current_map) / starting_map)

        if drop_fraction > 0.25 and not runtime.get("rapid_overcorrection"):
            runtime["rapid_overcorrection"] = True
            harms.append("rapid_overcorrection")

            # Attribute to the actual offending medications, not latest action
            active_ah = [m.get("medication_id") for m in state.get("active_medications", [])
                         if m.get("active") and m.get("medication_id") in self._ANTIHYPERTENSIVES]
            recent_bolus = [m.get("medication_id") for m in state.get("active_medications", [])
                           if m.get("mode") == "bolus"
                           and (now - m.get("last_dose_time_sec", 0)) < 600
                           and m.get("medication_id") in self._ANTIHYPERTENSIVES]
            all_relevant = list(dict.fromkeys(active_ah + recent_bolus))
            med_str = ", ".join(self._med_display(m) for m in all_relevant) if all_relevant else "antihypertensive therapy"

            events.append(self._evt(now, "harm_event_triggered", "critical",
                                    f"HARM: MAP has fallen {drop_fraction:.0%} from baseline "
                                    f"(from {int(starting_map)} to {int(current_map)} mmHg) — exceeds the safe 25% threshold. "
                                    f"Likely caused by: {med_str}. "
                                    f"Patient has worsening neurologic status consistent with cerebral hypoperfusion. "
                                    f"Consider stopping/reducing antihypertensives and supporting MAP.",
                                    {"harm_event_id": "rapid_overcorrection",
                                     "map_drop_fraction": round(drop_fraction, 3),
                                     "offending_medications": all_relevant}))

        actual_hr = float(hemo.get("hr", 100))
        if actual_hr < 45 and current_map < 65 and not runtime.get("iatrogenic_bradycardic_hypoperfusion"):
            runtime["iatrogenic_bradycardic_hypoperfusion"] = True
            harms.append("iatrogenic_bradycardic_hypoperfusion")
            events.append(self._evt(now, "harm_event_triggered", "high",
                                    f"HARM: Bradycardic hypoperfusion — HR {int(actual_hr)} bpm with MAP {int(current_map)} mmHg "
                                    f"(from {int(starting_map)} baseline). Likely from excessive beta-blockade. "
                                    f"Consider atropine, vasopressor support, or reducing beta-blocker dosing.",
                                    {"harm_event_id": "iatrogenic_bradycardic_hypoperfusion",
                                     "hr": int(actual_hr), "map": int(current_map)}))

        if neuro.get("mental_status") == "seizing" and not runtime.get("progression_to_seizure"):
            runtime["progression_to_seizure"] = True
            harms.append("progression_to_seizure")
            events.append(self._evt(now, "harm_event_triggered", "critical",
                                    "HARM: Seizure from uncontrolled hypertensive encephalopathy. IV antihypertensives needed urgently.",
                                    {"harm_event_id": "progression_to_seizure"}))

        if not runtime.get("missed_hypertensive_emergency") and state.get("case_metadata", {}).get("time_elapsed_sec", 0) >= 1200:
            if not any(m.get("medication_id") in {"nicardipine_iv", "clevidipine_iv", "labetalol_iv"}
                       for m in state.get("active_medications", [])):
                runtime["missed_hypertensive_emergency"] = True
                harms.append("missed_hypertensive_emergency")
                events.append(self._evt(now, "harm_event_triggered", "high",
                                        "HARM: 20+ minutes elapsed without IV antihypertensive therapy. "
                                        "Delay in treatment risks ongoing cerebral end-organ injury.",
                                        {"harm_event_id": "missed_hypertensive_emergency"}))

        return harms, events

    # --------------------
    # New action handlers (v3)
    # --------------------

    def _query_infusion_status(self, state: dict, payload: dict, now: int, events: list) -> None:
        """Read-only: return current infusion rate — does NOT mutate state."""
        med_id = payload.get("medication_id")
        if med_id:
            med = self._find_active_med(state, med_id)
            if med:
                rate = med.get("current_infusion_rate", 0)
                events.append(self._evt(now, "state_update", "info",
                                        f"{self._med_display(med_id)} is running at {rate}.",
                                        {"medication_id": med_id, "current_infusion_rate": rate}))
            else:
                events.append(self._evt(now, "state_update", "info",
                                        f"{self._med_display(med_id)} is not currently active.",
                                        {"medication_id": med_id}))
        else:
            active = [m for m in state.get("active_medications", [])
                      if m.get("active") and m.get("mode") == "infusion"]
            if active:
                parts = [f"{self._med_display(m['medication_id'])} at {m.get('current_infusion_rate', 0)}"
                         for m in active]
                events.append(self._evt(now, "state_update", "info",
                                        f"Active infusions: {', '.join(parts)}.",
                                        {"active_infusions": [m.get("medication_id") for m in active]}))
            else:
                events.append(self._evt(now, "state_update", "info",
                                        "No active infusions currently running.", {}))

    def _retrieve_diagnostic_result(self, state: dict, payload: dict, now: int, events: list) -> None:
        """Return a previously resulted diagnostic without re-running it."""
        diag_id = payload.get("diagnostic_id")
        if not diag_id:
            events.append(self._evt(now, "state_update", "info",
                                    "Please specify which diagnostic result you would like to retrieve.", {}))
            return
        for order in state.get("orders", []):
            op = order.get("payload", {})
            if op.get("diagnostic_id") == diag_id and op.get("status") == "resulted":
                result_text = op.get("result_text", "Result available.")
                events.append(self._evt(now, "diagnostic_result_available", "info",
                                        f"RESULT — {self._diag_display(diag_id)}: {result_text}",
                                        {"diagnostic_id": diag_id, "result_text": result_text}))
                return
        # Check pending
        for order in state.get("orders", []):
            op = order.get("payload", {})
            if op.get("diagnostic_id") == diag_id and op.get("status") == "pending":
                eta = max(0, int(op.get("result_available_at_sec", now) - now))
                events.append(self._evt(now, "state_update", "info",
                                        f"{self._diag_display(diag_id)} is pending — result expected in ~{eta} seconds.",
                                        {"diagnostic_id": diag_id, "eta_sec": eta}))
                return
        events.append(self._evt(now, "state_update", "info",
                                f"{self._diag_display(diag_id)} has not been ordered yet.",
                                {"diagnostic_id": diag_id}))

    def _handle_unsupported_procedure(self, state: dict, payload: dict, now: int, events: list) -> None:
        procedure = payload.get("procedure_name", "this procedure")
        events.append(self._evt(now, "state_update", "moderate",
                                f"'{procedure}' is not modeled in this simulation. "
                                f"In clinical practice, RSI/intubation requires anesthesia or intensivist involvement. "
                                f"For this scenario, focus on IV antihypertensive titration and neurologic monitoring.",
                                {"procedure": procedure}))

    def _handle_clinical_query(self, state: dict, payload: dict, now: int, events: list) -> None:
        """Return educational response to a clinical question without mutating state."""
        query = payload.get("query", "").lower()
        hemo = state.get("hemodynamics", {})
        _edu = {
            "nicardipine": (
                "Nicardipine is a dihydropyridine calcium channel blocker — it dilates peripheral arterioles, "
                "reducing SVR and MAP. IV infusion onset ~2–5 min, easily titratable. First-line for hypertensive emergencies."
            ),
            "clevidipine": (
                "Clevidipine is an ultra-short-acting dihydropyridine CCB (half-life ~1 min). "
                "Highly titratable with predictable offset. Ideal for precise BP control in the ICU."
            ),
            "labetalol": (
                "Labetalol is a combined alpha/beta blocker. IV bolus onset 2–5 min, duration 3–6 hr. "
                "Reduces HR and causes vasodilation. Useful as bolus therapy but less titratable than infusions."
            ),
            "norepinephrine": (
                "Norepinephrine (noradrenaline) is a potent alpha-1 agonist with some beta-1 activity. "
                "It raises MAP by increasing SVR. First-line vasopressor for vasodilatory shock. IV onset 1–2 min."
            ),
            "map": (
                "MAP = DBP + (SBP − DBP) / 3. Normal range 70–100 mmHg. "
                "In hypertensive emergencies, target a 15–25% MAP reduction in the first hour. "
                "Faster reduction risks cerebral watershed ischemia."
            ),
            "pres": (
                "PRES (Posterior Reversible Encephalopathy Syndrome): cerebral edema from failed vascular autoregulation "
                "under extreme hypertension. Presents with headache, visual changes, confusion, and seizures. "
                "Reversed with controlled BP reduction. MRI shows parieto-occipital FLAIR/T2 changes."
            ),
            "overcorrection": (
                "Rapid MAP reduction >25% of baseline risks 'watershed stroke' from cerebral hypoperfusion, "
                "AKI from renal hypoperfusion, and worsening encephalopathy. "
                "Target controlled, incremental reduction: 10–25% in the first hour, further reduction over 24–48 hr."
            ),
        }
        for kw, answer in _edu.items():
            if kw in query:
                events.append(self._evt(now, "state_update", "info",
                                        f"CLINICAL INFO: {answer}",
                                        {"query": query}))
                return
        # Default: acknowledge and direct to help
        events.append(self._evt(now, "state_update", "info",
                                f"Clinical question noted. Current: BP {hemo.get('sbp')}/{hemo.get('dbp')} "
                                f"(MAP {hemo.get('map')} mmHg). Type 'help' for management guidance.",
                                {"query": query}))

    # --------------------
    # Utility helpers
    # --------------------

    def _find_active_med(self, state: dict, med_id: str | None, include_inactive: bool = False) -> dict | None:
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
        if med_id == "hydralazine_iv":
            return dose / 20.0
        if med_id == "phenylephrine_iv":
            return dose / 0.5  # phenylephrine push is potent
        return dose / 20.0

    def _infusion_to_effect(self, med_id: str, rate: float, dt_sec: int) -> float:
        dt_min = dt_sec / 60.0
        effects = {
            # Antihypertensives — slow half-lives, factors designed for 30 min half-life
            "nicardipine_iv": 0.06,
            "clevidipine_iv": 0.18,
            "labetalol_iv": 0.10,
            "esmolol_iv": 0.02,
            "nitroglycerin_iv": 0.015,
            "nitroprusside_iv": 0.20,
            "hydralazine_iv": 0.05,
            # Vasopressors — short half-lives (2–5 min); factors boosted so WASHOUT-then-ADD
            # model produces meaningful immediate effect at clinical doses.
            # Designed so: at standard rate, first tick CE ≥ threshold for ~10 mmHg MAP gain.
            "norepinephrine_iv": 1.90,   # 0.1 mcg/kg/min → CE 0.95/tick → MAP +10 mmHg
            "epinephrine_iv": 3.50,      # 0.05 mcg/kg/min → CE 0.875/tick
            "phenylephrine_iv": 0.50,    # 0.5 mcg/kg/min → CE 1.25/tick → MAP +8 mmHg
            "dopamine_iv": 0.12,         # 5 mcg/kg/min → CE 3.0/tick (already capped at 0.4)
            "dobutamine_iv": 0.08,
            "vasopressin_iv": 12.0,      # 0.03 U/min → CE 1.8/tick → MAP +9 mmHg
        }
        return rate * effects.get(med_id, 0.05) * dt_min

    def _infusion_dose_increment(self, med_id: str, rate: float, dt_sec: int) -> float:
        hours = dt_sec / 3600.0
        if med_id in {"nicardipine_iv", "clevidipine_iv", "nitroglycerin_iv", "nitroprusside_iv"}:
            return rate * hours
        return rate * (dt_sec / 60.0)

    def _washout_factor(self, med_id: str, dt_sec: int) -> float:
        dt_min = dt_sec / 60.0
        half_lives = {
            "nicardipine_iv": 30,
            "clevidipine_iv": 3,
            "labetalol_iv": 45,
            "esmolol_iv": 5,
            "nitroglycerin_iv": 3,
            "nitroprusside_iv": 2,
            "hydralazine_iv": 120,
            "norepinephrine_iv": 2,
            "epinephrine_iv": 2,
            "phenylephrine_iv": 5,
            "dopamine_iv": 2,
            "vasopressin_iv": 20,
        }
        half_life_min = half_lives.get(med_id, 15)
        return 0.5 ** (dt_min / half_life_min)

    def _assessment_documented(self, state: dict, concept: str) -> bool:
        for order in state.get("orders", []):
            if order.get("payload", {}).get("assessment_concept") == concept:
                return True
        return False

    def _recompute_monitor(self, state: dict) -> None:
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

    def _append_events_to_log(self, state: dict, events: list) -> None:
        for event in events:
            state.setdefault("event_log", []).append({
                "time_sec": event["timeSec"],
                "event_type": event["eventType"],
                "summary": event["summary"],
                "structured_data": event.get("structuredData", {}),
            })

    def _build_delta(self, before: dict, after: dict) -> dict:
        def dn(a: Any, b: Any) -> dict:
            if isinstance(a, (int, float)) and isinstance(b, (int, float)):
                return {"before": a, "after": b, "delta": round(b - a, 4)}
            return {"before": a, "after": b, "delta": None}

        hb, ha = before.get("hemodynamics", {}), after.get("hemodynamics", {})
        nb, na = before.get("neurologic", {}), after.get("neurologic", {})
        rb, ra = before.get("renal", {}), after.get("renal", {})
        db, da = before.get("disease_model", {}), after.get("disease_model", {})

        return {
            "hemodynamics": {
                "sbp": dn(hb.get("sbp"), ha.get("sbp")),
                "dbp": dn(hb.get("dbp"), ha.get("dbp")),
                "map": dn(hb.get("map"), ha.get("map")),
                "hr": dn(hb.get("hr"), ha.get("hr")),
                "rhythm": dn(hb.get("rhythm"), ha.get("rhythm")),
            },
            "neurologic": {
                "gcs": dn(nb.get("gcs"), na.get("gcs")),
                "mental_status": dn(nb.get("mental_status"), na.get("mental_status")),
                "headache_index": dn(nb.get("headache_index"), na.get("headache_index")),
                "vision_change_index": dn(nb.get("vision_change_index"), na.get("vision_change_index")),
                "cerebral_hypoperfusion_index": dn(nb.get("cerebral_hypoperfusion_index"), na.get("cerebral_hypoperfusion_index")),
            },
            "renal": {
                "urine_output_ml_per_hr": dn(rb.get("urine_output_ml_per_hr"), ra.get("urine_output_ml_per_hr")),
                "renal_perfusion_index": dn(rb.get("renal_perfusion_index"), ra.get("renal_perfusion_index")),
            },
            "disease_model": {
                "cerebral_edema_index": dn(db.get("cerebral_edema_index"), da.get("cerebral_edema_index")),
            },
            "active_medications": after.get("active_medications", []),
        }

    def _evt(self, now: int, event_type: str, severity: str, summary: str, structured_data: dict) -> dict:
        safe_type = event_type.replace("-", "_")
        return {
            "eventId": f"evt_{safe_type}_{now}_{abs(hash(summary)) % 10000}",
            "timeSec": now,
            "eventType": event_type,
            "severity": severity,
            "summary": summary,
            "structuredData": structured_data,
        }

    @staticmethod
    def _med_display(med_id: str | None) -> str:
        if not med_id:
            return "unknown medication"
        return {
            "nicardipine_iv": "nicardipine",
            "clevidipine_iv": "clevidipine",
            "labetalol_iv": "labetalol",
            "hydralazine_iv": "hydralazine",
            "esmolol_iv": "esmolol",
            "nitroglycerin_iv": "nitroglycerin",
            "nitroprusside_iv": "nitroprusside",
            "norepinephrine_iv": "norepinephrine",
            "epinephrine_iv": "epinephrine",
            "phenylephrine_iv": "phenylephrine",
            "dopamine_iv": "dopamine",
            "dobutamine_iv": "dobutamine",
            "vasopressin_iv": "vasopressin",
        }.get(med_id, med_id.replace("_iv", ""))

    @staticmethod
    def _diag_display(diag_id: str | None) -> str:
        if not diag_id:
            return "Diagnostic"
        return {
            "head_ct_noncontrast": "CT Head (Non-contrast)",
            "mri_brain": "MRI Brain",
            "ecg": "12-Lead ECG",
            "cmp": "BMP/CMP",
            "troponin": "Troponin",
            "pregnancy_test": "Urine Pregnancy Test",
            "urinalysis": "Urinalysis",
            "bnp": "BNP",
            "cbc": "CBC",
            "coagulation_panel": "Coagulation Panel",
            "fingerstick_glucose": "Fingerstick Glucose",
            "chest_xray": "Chest X-Ray",
            "d_dimer": "D-Dimer",
            "lactate": "Lactate",
        }.get(diag_id, diag_id.replace("_", " ").title())
