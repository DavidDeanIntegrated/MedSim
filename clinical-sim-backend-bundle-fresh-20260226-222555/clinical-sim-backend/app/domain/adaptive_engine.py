"""Adaptive difficulty engine for MedSim.

Adjusts case parameters based on the learner's historical performance
to keep them in the zone of proximal development (challenging but not
overwhelming).

Three difficulty tiers:
  guided   — extra hints, slower disease progression, wider safe ranges
  standard — default case parameters
  expert   — faster progression, narrower safe ranges, complications enabled

The engine examines recent session grades and recommends a difficulty
level plus case-specific parameter overrides.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class DifficultyProfile:
    level: str  # "guided", "standard", "expert"
    time_pressure_multiplier: float  # multiplied into advance_time_sec
    severity_multiplier: float       # scales disease_model.severity_index
    hint_frequency: str              # "frequent", "occasional", "none"
    complication_probability: float  # 0.0 - 1.0
    safe_range_tolerance: float      # multiplier on target ranges (>1 = wider)
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "time_pressure_multiplier": self.time_pressure_multiplier,
            "severity_multiplier": self.severity_multiplier,
            "hint_frequency": self.hint_frequency,
            "complication_probability": self.complication_probability,
            "safe_range_tolerance": self.safe_range_tolerance,
            "description": self.description,
        }


# Default difficulty profiles
PROFILES: dict[str, DifficultyProfile] = {
    "guided": DifficultyProfile(
        level="guided",
        time_pressure_multiplier=0.7,     # Slower time progression
        severity_multiplier=0.8,          # Less severe disease
        hint_frequency="frequent",
        complication_probability=0.0,
        safe_range_tolerance=1.3,         # Wider acceptable ranges
        description="Guided mode: hints provided, slower disease progression, wider margins for error",
    ),
    "standard": DifficultyProfile(
        level="standard",
        time_pressure_multiplier=1.0,
        severity_multiplier=1.0,
        hint_frequency="occasional",
        complication_probability=0.15,
        safe_range_tolerance=1.0,
        description="Standard mode: realistic case parameters with occasional guidance",
    ),
    "expert": DifficultyProfile(
        level="expert",
        time_pressure_multiplier=1.4,     # Faster time progression
        severity_multiplier=1.2,          # More severe disease
        hint_frequency="none",
        complication_probability=0.4,
        safe_range_tolerance=0.8,         # Tighter acceptable ranges
        description="Expert mode: increased severity, faster progression, complications enabled",
    ),
}


class AdaptiveEngine:
    """Recommends difficulty adjustments based on learner performance history."""

    def recommend_difficulty(
        self,
        past_grades: list[dict[str, Any]],
        requested_difficulty: str | None = None,
    ) -> DifficultyProfile:
        """Recommend a difficulty level from past session grades.

        Args:
            past_grades: List of grade dicts with at least 'final_percent' and 'letter_grade'.
                         Most recent first.
            requested_difficulty: If learner explicitly chose a level, respect it.
        """
        if requested_difficulty and requested_difficulty in PROFILES:
            return PROFILES[requested_difficulty]

        if not past_grades:
            return PROFILES["standard"]

        # Look at the last 5 sessions (or fewer)
        recent = past_grades[:5]
        avg_score = sum(g.get("final_percent", 0) for g in recent) / len(recent)

        # Trend: is the learner improving?
        if len(recent) >= 3:
            recent_avg = sum(g.get("final_percent", 0) for g in recent[:2]) / 2
            older_avg = sum(g.get("final_percent", 0) for g in recent[2:]) / len(recent[2:])
            trend = recent_avg - older_avg  # positive = improving
        else:
            trend = 0

        # Decision logic
        if avg_score >= 85 and trend >= 0:
            return PROFILES["expert"]
        elif avg_score < 55:
            return PROFILES["guided"]
        elif avg_score < 70 and trend < -5:
            # Struggling and getting worse -> step down
            return PROFILES["guided"]
        else:
            return PROFILES["standard"]

    def apply_overrides(
        self,
        case_data: dict[str, Any],
        profile: DifficultyProfile,
    ) -> dict[str, Any]:
        """Apply difficulty overrides to case initial state.

        Returns a dict of custom_case_overrides to pass to session_service.start_case().
        """
        overrides: dict[str, Any] = {}

        # Scale disease severity
        if profile.severity_multiplier != 1.0:
            disease = case_data.get("disease_model", {})
            if "severity_index" in disease:
                overrides["disease_severity_override"] = min(
                    1.0, disease["severity_index"] * profile.severity_multiplier
                )

        # Store difficulty metadata for the engine to reference
        overrides["adaptive_difficulty"] = {
            "level": profile.level,
            "time_pressure_multiplier": profile.time_pressure_multiplier,
            "hint_frequency": profile.hint_frequency,
            "complication_probability": profile.complication_probability,
            "safe_range_tolerance": profile.safe_range_tolerance,
        }

        return overrides

    def generate_hint(
        self,
        patient_state: dict[str, Any],
        profile: DifficultyProfile,
        elapsed_sec: float,
    ) -> str | None:
        """Generate a contextual hint for guided/standard modes.

        Returns None if no hint is appropriate (expert mode or no hint needed).
        """
        if profile.hint_frequency == "none":
            return None

        scoring = patient_state.get("scoring", {})
        runtime = scoring.get("runtime_flags", {})
        active_meds = patient_state.get("active_medications", [])
        orders = patient_state.get("orders", [])

        # Check what hasn't been done yet and suggest next steps
        case_def = patient_state.get("case_definition_inline", {})
        critical_actions = case_def.get("critical_actions", [])

        for ca in critical_actions:
            aid = ca.get("id", "")
            target_time = ca.get("target_time_sec", 600)

            if runtime.get(aid):
                continue  # Already completed

            # Determine if hint timing is right
            if profile.hint_frequency == "frequent":
                hint_threshold = target_time * 0.5
            else:  # occasional
                hint_threshold = target_time * 0.8

            if elapsed_sec >= hint_threshold:
                return self._hint_for_action(aid, ca, patient_state)

        return None

    def _hint_for_action(
        self, action_id: str, action_def: dict, state: dict
    ) -> str:
        """Generate a specific hint based on the uncompleted action."""
        desc = action_def.get("description", action_id)

        # Generic hint based on action description
        # Trim to first sentence for brevity
        first_sentence = desc.split(".")[0] if "." in desc else desc
        return f"Consider: {first_sentence}"
