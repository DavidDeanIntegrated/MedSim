"""Universal scoring engine for MedSim cases.

Provides weighted scoring with timing bonuses, letter grades, and
percentile estimates. Works with any case that defines critical_actions
and harm_events in the standard schema.

Scoring model:
  base_score = sum(action_weight * timing_multiplier for completed actions)
  penalty    = sum(harm_severity for triggered harm events)
  raw_score  = max(0, base_score - penalty)
  final_pct  = raw_score / max_possible * 100

Timing multiplier:
  If completed before target_time_sec:  1.0 + 0.25 * (1 - elapsed/target)
  If completed after target_time_sec:   max(0.5, 1.0 - 0.25 * (elapsed - target) / target)
  So fast action gets up to 1.25x, slow action gets min 0.5x.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ActionScore:
    action_id: str
    description: str
    weight: float
    target_time_sec: float
    completed: bool = False
    completed_at_sec: float | None = None
    timing_multiplier: float = 0.0
    points_earned: float = 0.0


@dataclass
class HarmScore:
    harm_id: str
    description: str
    severity: float
    triggered: bool = False
    triggered_at_sec: float | None = None
    penalty: float = 0.0


@dataclass
class SessionGrade:
    raw_score: float
    max_possible: float
    penalty_total: float
    final_percent: float
    letter_grade: str
    action_scores: list[ActionScore]
    harm_scores: list[HarmScore]
    time_to_first_action_sec: float | None
    total_sim_time_sec: float
    summary: str

    def to_dict(self) -> dict:
        return {
            "raw_score": round(self.raw_score, 1),
            "max_possible": round(self.max_possible, 1),
            "penalty_total": round(self.penalty_total, 1),
            "final_percent": round(self.final_percent, 1),
            "letter_grade": self.letter_grade,
            "time_to_first_action_sec": self.time_to_first_action_sec,
            "total_sim_time_sec": round(self.total_sim_time_sec, 1),
            "summary": self.summary,
            "action_scores": [
                {
                    "action_id": a.action_id,
                    "description": a.description,
                    "weight": a.weight,
                    "target_time_sec": a.target_time_sec,
                    "completed": a.completed,
                    "completed_at_sec": a.completed_at_sec,
                    "timing_multiplier": round(a.timing_multiplier, 2),
                    "points_earned": round(a.points_earned, 1),
                }
                for a in self.action_scores
            ],
            "harm_scores": [
                {
                    "harm_id": h.harm_id,
                    "description": h.description,
                    "severity": h.severity,
                    "triggered": h.triggered,
                    "triggered_at_sec": h.triggered_at_sec,
                    "penalty": round(h.penalty, 1),
                }
                for h in self.harm_scores
            ],
        }


_GRADE_THRESHOLDS = [
    (93, "A"),
    (85, "B+"),
    (78, "B"),
    (70, "C+"),
    (63, "C"),
    (55, "D"),
    (0, "F"),
]


def _letter_grade(pct: float) -> str:
    for threshold, grade in _GRADE_THRESHOLDS:
        if pct >= threshold:
            return grade
    return "F"


def compute_timing_multiplier(target_time_sec: float, completed_at_sec: float) -> float:
    """Reward early action, penalize late action."""
    if target_time_sec <= 0:
        return 1.0
    if completed_at_sec <= target_time_sec:
        # Early bonus: up to 1.25x for instant action
        fraction_early = 1.0 - (completed_at_sec / target_time_sec)
        return 1.0 + 0.25 * fraction_early
    else:
        # Late penalty: down to 0.5x
        fraction_late = (completed_at_sec - target_time_sec) / target_time_sec
        return max(0.5, 1.0 - 0.25 * fraction_late)


class ScoringEngine:
    """Computes final session grade from case definition and session events."""

    def grade_session(
        self,
        critical_actions: list[dict],
        harm_events: list[dict],
        completed_action_ids: dict[str, float],  # action_id -> completed_at_sec
        triggered_harm_ids: dict[str, float],     # harm_id -> triggered_at_sec
        total_sim_time_sec: float,
    ) -> SessionGrade:
        action_scores: list[ActionScore] = []
        for ca in critical_actions:
            aid = ca.get("id", "")
            weight = float(ca.get("weight", 8))
            target = float(ca.get("target_time_sec", 600))
            desc = ca.get("description", aid)

            a = ActionScore(action_id=aid, description=desc, weight=weight, target_time_sec=target)
            if aid in completed_action_ids:
                a.completed = True
                a.completed_at_sec = completed_action_ids[aid]
                a.timing_multiplier = compute_timing_multiplier(target, a.completed_at_sec)
                a.points_earned = weight * a.timing_multiplier
            action_scores.append(a)

        harm_scores: list[HarmScore] = []
        for he in harm_events:
            hid = he.get("id", "")
            severity = float(he.get("severity", 12))
            desc = he.get("description", hid)

            h = HarmScore(harm_id=hid, description=desc, severity=severity)
            if hid in triggered_harm_ids:
                h.triggered = True
                h.triggered_at_sec = triggered_harm_ids[hid]
                h.penalty = severity
            harm_scores.append(h)

        raw_score = sum(a.points_earned for a in action_scores)
        penalty_total = sum(h.penalty for h in harm_scores)
        # Max possible = all actions completed perfectly on time (1.25x bonus)
        max_possible = sum(a.weight * 1.25 for a in action_scores)
        if max_possible == 0:
            max_possible = 100.0

        adjusted = max(0.0, raw_score - penalty_total)
        final_pct = min(100.0, (adjusted / max_possible) * 100)
        letter = _letter_grade(final_pct)

        # Time to first action
        completed_times = [t for t in completed_action_ids.values() if t is not None]
        first_action = min(completed_times) if completed_times else None

        n_completed = sum(1 for a in action_scores if a.completed)
        n_total = len(action_scores)
        n_harms = sum(1 for h in harm_scores if h.triggered)

        summary = (
            f"Completed {n_completed}/{n_total} critical actions. "
            f"{n_harms} harm event{'s' if n_harms != 1 else ''} triggered. "
            f"Score: {final_pct:.0f}% ({letter})."
        )

        return SessionGrade(
            raw_score=raw_score,
            max_possible=max_possible,
            penalty_total=penalty_total,
            final_percent=final_pct,
            letter_grade=letter,
            action_scores=action_scores,
            harm_scores=harm_scores,
            time_to_first_action_sec=first_action,
            total_sim_time_sec=total_sim_time_sec,
            summary=summary,
        )
