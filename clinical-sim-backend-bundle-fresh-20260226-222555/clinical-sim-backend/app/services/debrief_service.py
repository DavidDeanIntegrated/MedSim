"""Structured debrief generator for MedSim.

Generates detailed post-case feedback by analyzing the learner's turn
history against the case's critical actions and ideal management pathway.

Rule-based by default (no LLM cost). When LLM_PARSER_ENABLED=True and
an API key is set, the debrief can be optionally enhanced by Claude.

Output structure:
  - overall_assessment: letter grade + summary
  - annotated_timeline: each decision point with feedback
  - critical_actions_analysis: per-action breakdown
  - harm_events_analysis: per-harm breakdown with explanation
  - strengths: what the learner did well
  - areas_for_improvement: specific gaps
  - study_recommendations: targeted reading suggestions
  - board_review_topics: relevant board exam topics
"""

from __future__ import annotations

from typing import Any

from app.domain.scoring_engine import ScoringEngine, SessionGrade


# Mapping from case category to board-relevant study topics
_BOARD_TOPICS: dict[str, list[str]] = {
    "hypertensive_emergency": [
        "Hypertensive emergencies vs urgencies",
        "IV antihypertensive selection and titration",
        "End-organ damage assessment (neuro, cardiac, renal, aortic)",
        "Target MAP reduction: 10-20% in first hour, 25% over 24h",
        "Posterior reversible encephalopathy syndrome (PRES)",
    ],
    "septic_shock": [
        "Sepsis-3 definition and qSOFA criteria",
        "Surviving Sepsis Campaign Hour-1 bundle",
        "Vasopressor pharmacology: NE first-line, vasopressin adjunct",
        "Lactate-guided resuscitation",
        "Source control principles in sepsis",
    ],
    "dka": [
        "DKA diagnostic criteria (glucose, pH, bicarb, anion gap, ketones)",
        "Insulin drip protocol: 0.1 U/kg/hr after K+ > 3.3",
        "Potassium replacement before insulin if K+ < 3.3",
        "Fluid resuscitation: NS then switch to D5 when glucose < 200-250",
        "Anion gap closure as primary endpoint (not glucose)",
        "Cerebral edema risk in young patients",
    ],
    "stemi": [
        "STEMI recognition: ST elevation in contiguous leads",
        "Door-to-balloon time < 90 minutes",
        "Dual antiplatelet therapy (aspirin + P2Y12 inhibitor)",
        "RV infarction: avoid nitroglycerin and preload reducers",
        "Cardiogenic shock complicating MI",
    ],
    "eclampsia": [
        "Magnesium sulfate: first-line for eclamptic seizures",
        "Severe preeclampsia/HELLP syndrome management",
        "Antihypertensive choices in pregnancy (labetalol, hydralazine, nifedipine)",
        "Delivery as definitive treatment",
        "Fetal monitoring and emergent C-section indications",
    ],
    "massive_pe": [
        "Wells criteria and PERC rule",
        "CT pulmonary angiography: diagnostic gold standard",
        "Systemic thrombolysis indications in massive PE",
        "Anticoagulation with unfractionated heparin",
        "RV strain markers: troponin, BNP, RV dilation on echo",
        "Judicious fluid resuscitation (avoid RV overload)",
    ],
    "aortic_dissection": [
        "Stanford classification: Type A vs Type B",
        "Heart rate control BEFORE blood pressure reduction",
        "Target HR < 60 and SBP < 120 mmHg",
        "Esmolol and labetalol as first-line agents",
        "CTA chest/abdomen/pelvis for definitive diagnosis",
        "Emergent surgical consultation for Type A dissection",
    ],
    "anaphylaxis": [
        "Anaphylaxis diagnostic criteria (skin + respiratory/cardiovascular)",
        "Epinephrine IM 0.3-0.5mg: first-line, repeat q5-15 min",
        "Never delay epinephrine for antihistamines/steroids",
        "Biphasic anaphylaxis: observe 4-6 hours minimum",
        "Epinephrine drip for refractory anaphylactic shock",
    ],
    "ich": [
        "Emergent CT head for any suspected stroke",
        "Anticoagulant reversal: 4-factor PCC + IV vitamin K for warfarin",
        "Blood pressure management in ICH (SBP target 140 mmHg per AHA)",
        "Avoiding tPA in hemorrhagic stroke (catastrophic error)",
        "Neurosurgical consultation indications",
        "ICP management: HOB elevation, osmotic therapy",
    ],
    "copd_exacerbation": [
        "GOLD severity classification",
        "Nebulized bronchodilators: albuterol + ipratropium",
        "Systemic corticosteroids for acute exacerbation",
        "NIPPV for hypercapnic respiratory failure (pH < 7.35, PaCO2 > 45)",
        "Oxygen titration: target SpO2 88-92% (avoid hyperoxia-driven CO2 retention)",
        "Antibiotic indications: increased dyspnea + purulent sputum",
    ],
    "acute_pulmonary_edema": [
        "Acute decompensated heart failure: preload vs afterload reduction",
        "NIPPV (BiPAP/CPAP) as first-line respiratory support",
        "Nitroglycerin infusion for preload/afterload reduction",
        "IV furosemide for diuresis",
        "Avoid IV fluids in cardiogenic pulmonary edema",
        "Inotrope/vasopressor indications for cardiogenic shock",
    ],
}


class DebriefService:
    """Generates structured post-simulation debrief."""

    def __init__(self) -> None:
        self.scoring_engine = ScoringEngine()

    def generate_debrief(
        self,
        session: dict[str, Any],
    ) -> dict[str, Any]:
        patient_state = session.get("patientState", {})
        case_def = patient_state.get("case_definition_inline", {})
        events = session.get("events", [])
        transcript = session.get("transcript", [])
        scoring = patient_state.get("scoring", {})

        # Extract case metadata
        case_id = case_def.get("case_id", session.get("activeCaseId", "unknown"))
        case_title = case_def.get("title", case_id)
        category = session.get("caseDefinition", {}).get("category", "")
        total_time = patient_state.get("case_metadata", {}).get("time_elapsed_sec", 0)

        # Build completed/triggered maps from session scoring data
        runtime_flags = scoring.get("runtime_flags", {})
        harm_flags = scoring.get("harm_runtime_flags", {})
        critical_actions = case_def.get("critical_actions", [])
        harm_events = case_def.get("harm_events", [])

        # Map completed actions with approximate timing from events
        completed_map = self._extract_completed_actions(events, runtime_flags)
        triggered_map = self._extract_triggered_harms(events, harm_flags)

        # Compute detailed grade
        grade = self.scoring_engine.grade_session(
            critical_actions=critical_actions,
            harm_events=harm_events,
            completed_action_ids=completed_map,
            triggered_harm_ids=triggered_map,
            total_sim_time_sec=total_time,
        )

        # Build annotated timeline
        timeline = self._build_annotated_timeline(events, transcript, critical_actions, harm_events)

        # Build analysis sections
        strengths = self._identify_strengths(grade, timeline)
        improvements = self._identify_improvements(grade, critical_actions, harm_events)
        study_recs = self._build_study_recommendations(category, improvements, grade)
        board_topics = _BOARD_TOPICS.get(category, [])

        return {
            "case_id": case_id,
            "case_title": case_title,
            "overall_assessment": {
                "letter_grade": grade.letter_grade,
                "score_percent": round(grade.final_percent, 1),
                "summary": grade.summary,
                "total_sim_time_sec": round(total_time, 1),
                "time_to_first_action_sec": grade.time_to_first_action_sec,
            },
            "annotated_timeline": timeline,
            "critical_actions_analysis": grade.to_dict()["action_scores"],
            "harm_events_analysis": grade.to_dict()["harm_scores"],
            "strengths": strengths,
            "areas_for_improvement": improvements,
            "study_recommendations": study_recs,
            "board_review_topics": board_topics,
            "scoring_breakdown": grade.to_dict(),
        }

    def _extract_completed_actions(
        self, events: list[dict], runtime_flags: dict
    ) -> dict[str, float]:
        """Map action_id -> time_sec when completed, from event log."""
        completed: dict[str, float] = {}
        for evt in events:
            if evt.get("eventType") == "critical_action_completed" or evt.get("event_type") == "critical_action_completed":
                data = evt.get("structuredData") or evt.get("structured_data", {})
                action_id = data.get("action_id", "")
                time = evt.get("timeSec") or evt.get("time_sec", 0)
                if action_id:
                    completed[action_id] = float(time)
        # Also check runtime flags for any completed actions without event timestamps
        for flag_name, flag_val in runtime_flags.items():
            if flag_val and flag_name not in completed:
                completed[flag_name] = 0.0  # Unknown timing
        return completed

    def _extract_triggered_harms(
        self, events: list[dict], harm_flags: dict
    ) -> dict[str, float]:
        """Map harm_id -> time_sec when triggered."""
        triggered: dict[str, float] = {}
        for evt in events:
            if evt.get("eventType") == "harm_event_triggered" or evt.get("event_type") == "harm_event_triggered":
                data = evt.get("structuredData") or evt.get("structured_data", {})
                harm_id = data.get("harm_event_id", "")
                time = evt.get("timeSec") or evt.get("time_sec", 0)
                if harm_id:
                    triggered[harm_id] = float(time)
        for flag_name, flag_val in harm_flags.items():
            if flag_val and flag_name not in triggered:
                triggered[flag_name] = 0.0
        return triggered

    def _build_annotated_timeline(
        self,
        events: list[dict],
        transcript: list[dict],
        critical_actions: list[dict],
        harm_events: list[dict],
    ) -> list[dict]:
        """Build time-ordered timeline with annotations for key decisions."""
        timeline_entries: list[dict] = []

        # Build lookup maps
        ca_map = {ca["id"]: ca for ca in critical_actions if "id" in ca}
        harm_map = {h["id"]: h for h in harm_events if "id" in h}

        for evt in events:
            etype = evt.get("eventType") or evt.get("event_type", "")
            time_sec = evt.get("timeSec") or evt.get("time_sec", 0)
            summary = evt.get("summary", "")
            data = evt.get("structuredData") or evt.get("structured_data", {})

            entry: dict[str, Any] = {
                "time_sec": time_sec,
                "time_display": self._format_time(float(time_sec)),
                "event_type": etype,
                "summary": summary,
            }

            if etype == "critical_action_completed":
                aid = data.get("action_id", "")
                ca = ca_map.get(aid, {})
                entry["annotation"] = f"Correct action: {ca.get('description', aid)}"
                entry["annotation_type"] = "positive"
                target = ca.get("target_time_sec", 0)
                if target and float(time_sec) <= target:
                    entry["timing_note"] = f"Completed within target time ({self._format_time(target)})"
                elif target:
                    entry["timing_note"] = f"Late — target was {self._format_time(target)}"

            elif etype == "harm_event_triggered":
                hid = data.get("harm_event_id", "")
                harm = harm_map.get(hid, {})
                entry["annotation"] = f"Harm: {harm.get('description', summary)}"
                entry["annotation_type"] = "negative"

            elif etype in ("medication_effect", "state_update"):
                entry["annotation_type"] = "neutral"

            elif etype in ("clinical_deterioration", "adverse_event"):
                entry["annotation_type"] = "warning"

            elif etype == "clinical_improvement":
                entry["annotation_type"] = "positive"

            timeline_entries.append(entry)

        timeline_entries.sort(key=lambda x: x.get("time_sec", 0))
        return timeline_entries

    def _identify_strengths(
        self, grade: SessionGrade, timeline: list[dict]
    ) -> list[str]:
        """Identify things the learner did well."""
        strengths: list[str] = []

        # Early actions
        early_actions = [
            a for a in grade.action_scores
            if a.completed and a.completed_at_sec is not None
            and a.timing_multiplier >= 1.0
        ]
        if early_actions:
            names = [a.description[:60] for a in early_actions[:3]]
            strengths.append(
                f"Completed {len(early_actions)} action{'s' if len(early_actions) > 1 else ''} "
                f"within target time: {'; '.join(names)}"
            )

        # No harm events
        harms_triggered = [h for h in grade.harm_scores if h.triggered]
        if not harms_triggered:
            strengths.append("No patient harm events triggered — safe management throughout")

        # High completion
        n_completed = sum(1 for a in grade.action_scores if a.completed)
        n_total = len(grade.action_scores)
        if n_total > 0 and n_completed / n_total >= 0.8:
            strengths.append(
                f"Completed {n_completed}/{n_total} critical actions ({n_completed/n_total:.0%})"
            )

        # Fast first action
        if grade.time_to_first_action_sec is not None and grade.time_to_first_action_sec <= 120:
            strengths.append(
                f"Quick initial response — first critical action at {self._format_time(grade.time_to_first_action_sec)}"
            )

        if not strengths:
            strengths.append("Simulation attempted — continued practice will improve performance")

        return strengths

    def _identify_improvements(
        self,
        grade: SessionGrade,
        critical_actions: list[dict],
        harm_events: list[dict],
    ) -> list[str]:
        """Identify areas for improvement with specific guidance."""
        improvements: list[str] = []

        # Missed actions
        missed = [a for a in grade.action_scores if not a.completed]
        for m in missed:
            improvements.append(f"Missed: {m.description}")

        # Late actions
        late = [
            a for a in grade.action_scores
            if a.completed and a.timing_multiplier < 0.9
        ]
        for la in late:
            if la.completed_at_sec is not None:
                improvements.append(
                    f"Delayed: {la.description[:60]}... — completed at {self._format_time(la.completed_at_sec)}, "
                    f"target was {self._format_time(la.target_time_sec)}"
                )

        # Triggered harms
        for h in grade.harm_scores:
            if h.triggered:
                improvements.append(f"Harm event: {h.description}")

        return improvements

    def _build_study_recommendations(
        self,
        category: str,
        improvements: list[str],
        grade: SessionGrade,
    ) -> list[str]:
        """Generate targeted study recommendations based on gaps."""
        recs: list[str] = []

        if grade.final_percent < 70:
            recs.append(
                "Review the foundational management algorithm for this condition before attempting again"
            )

        # Build recs from missed/delayed actions
        missed_ids = {a.action_id for a in grade.action_scores if not a.completed}
        for a in grade.action_scores:
            if not a.completed:
                recs.append(f"Study: {a.description}")

        if any(h.triggered for h in grade.harm_scores):
            recs.append(
                "Review common medication errors and patient safety considerations for this case type"
            )

        # Add category-specific general recs
        if grade.final_percent < 85:
            topics = _BOARD_TOPICS.get(category, [])
            if topics:
                recs.append(f"Key board review topics: {'; '.join(topics[:3])}")

        if not recs:
            recs.append("Excellent performance — try the case at a higher difficulty level")

        return recs

    @staticmethod
    def _format_time(seconds: float) -> str:
        """Format seconds as M:SS."""
        m = int(seconds) // 60
        s = int(seconds) % 60
        return f"{m}:{s:02d}"
