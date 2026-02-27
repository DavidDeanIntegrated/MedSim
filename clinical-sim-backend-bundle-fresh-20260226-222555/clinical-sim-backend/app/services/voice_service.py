from __future__ import annotations

from app.models.voice import BuildVoicePlanRequest, VoiceDialogueResponseContract


class VoiceService:
    def build_voice_plan(self, request: BuildVoicePlanRequest) -> VoiceDialogueResponseContract:
        sim_time = request.engine_result.timestamp_sim_sec_after
        nurse_text = "Orders completed."
        patient_text = None

        monitor_updates = request.engine_result.ui_updates.monitor_updates
        events = request.engine_result.new_events

        if any(e.severity == "critical" for e in events):
            nurse_text = "The patient is getting worse."
        elif monitor_updates.get("sbp") and monitor_updates["sbp"] > 220:
            nurse_text = "Her pressure is still very high."
        elif monitor_updates.get("sbp") and monitor_updates["sbp"] < 170:
            nurse_text = "Pressure is coming down now."
            patient_text = "My head feels a little better."

        responses = [
            {
                "responseId": "resp_nurse_001",
                "speakerRole": "nurse",
                "speakerId": "nurse_primary",
                "shouldSpeak": True,
                "text": nurse_text,
                "ssmlText": None,
                "tone": "urgent" if "worse" in nurse_text.lower() else "neutral",
                "priority": "nurse_urgent" if "worse" in nurse_text.lower() else "nurse_routine",
                "interruptive": "worse" in nurse_text.lower(),
                "canBeInterrupted": not ("worse" in nurse_text.lower()),
                "blocking": "worse" in nurse_text.lower(),
                "latencyTargetMs": 400,
                "estimatedDurationMs": 1800,
                "subtitleText": f"Nurse: {nurse_text}",
                "subtitleStyle": "critical" if "worse" in nurse_text.lower() else "default",
                "animationCue": "nurse_alert" if "worse" in nurse_text.lower() else "nurse_routine",
                "emotionScore": 0.8 if "worse" in nurse_text.lower() else 0.2,
                "sourceEventIds": [e.event_id for e in events[:2]],
                "followedByResponseIds": ["resp_patient_001"] if patient_text else [],
                "suppressIfUserSpeaking": False,
                "expireIfNotPlayedWithinMs": 5000 if "worse" in nurse_text.lower() else 8000,
            }
        ]

        if patient_text:
            responses.append(
                {
                    "responseId": "resp_patient_001",
                    "speakerRole": "patient",
                    "speakerId": "patient_main",
                    "shouldSpeak": True,
                    "text": patient_text,
                    "ssmlText": None,
                    "tone": "improving",
                    "priority": "patient_routine",
                    "interruptive": False,
                    "canBeInterrupted": True,
                    "blocking": False,
                    "latencyTargetMs": 900,
                    "estimatedDurationMs": 1800,
                    "subtitleText": f"Patient: {patient_text}",
                    "subtitleStyle": "default",
                    "animationCue": "patient_improving",
                    "emotionScore": 0.4,
                    "sourceEventIds": [],
                    "followedByResponseIds": [],
                    "suppressIfUserSpeaking": False,
                    "expireIfNotPlayedWithinMs": 10000,
                }
            )

        return VoiceDialogueResponseContract(
            contract_version="0.1.0",
            turnId=request.engine_result.turn_id,
            timestampSimSec=sim_time,
            responseStatus="ok",
            audioQueuePolicy={
                "mode": "priority_serial",
                "max_parallel_voices": 1,
                "interrupt_priority_order": [
                    "critical_system",
                    "nurse_urgent",
                    "patient_distress",
                    "nurse_routine",
                    "patient_routine",
                    "family",
                    "attending",
                    "system_info",
                ],
                "drop_low_priority_if_busy": False,
            },
            responses=responses,
            inputGate={
                "allow_new_user_input": True,
                "push_to_talk_enabled": True,
                "barge_in_allowed": True,
                "block_reason": None,
                "resume_input_after_ms": None,
            },
            subtitlePlan={
                "enabled": True,
                "show_speaker_label": True,
                "max_visible_lines": 3,
                "display_mode": "live_plus_history",
                "history_length": 6,
            },
            audioEngineHints={
                "preferred_sample_rate_hz": 22050,
                "normalize_output_volume": True,
                "duck_background_audio": True,
            },
            notes=["Simple voice planner in use"],
        )
