from typing import Literal

from pydantic import Field

from app.models.common import APIModel
from app.models.engine import EngineExecutorContract


class VoiceResponse(APIModel):
    response_id: str = Field(alias="responseId")
    speaker_role: Literal["patient", "nurse", "family", "attending", "system"] = Field(alias="speakerRole")
    speaker_id: str = Field(alias="speakerId")
    should_speak: bool = Field(alias="shouldSpeak")
    text: str | None = None
    ssml_text: str | None = Field(default=None, alias="ssmlText")
    tone: str
    priority: str
    interruptive: bool
    can_be_interrupted: bool = Field(default=True, alias="canBeInterrupted")
    blocking: bool
    latency_target_ms: int = Field(alias="latencyTargetMs")
    estimated_duration_ms: int = Field(alias="estimatedDurationMs")
    subtitle_text: str | None = Field(default=None, alias="subtitleText")
    subtitle_style: str | None = Field(default=None, alias="subtitleStyle")
    animation_cue: str | None = Field(default=None, alias="animationCue")
    emotion_score: float = Field(alias="emotionScore")
    source_event_ids: list[str] = Field(default_factory=list, alias="sourceEventIds")
    followed_by_response_ids: list[str] = Field(default_factory=list, alias="followedByResponseIds")
    suppress_if_user_speaking: bool = Field(default=False, alias="suppressIfUserSpeaking")
    expire_if_not_played_within_ms: int = Field(default=10000, alias="expireIfNotPlayedWithinMs")


class BuildVoicePlanRequest(APIModel):
    engine_result: EngineExecutorContract = Field(alias="engineResult")
    audio_mode: Literal["local_tts", "cloud_tts", "silent_subtitles_only"] = Field(default="local_tts", alias="audioMode")
    allow_interruptions: bool = Field(default=True, alias="allowInterruptions")


class VoiceDialogueResponseContract(APIModel):
    contract_version: str
    turn_id: str = Field(alias="turnId")
    timestamp_sim_sec: float = Field(alias="timestampSimSec")
    response_status: Literal["ok", "partial", "suppressed", "error"] = Field(alias="responseStatus")
    audio_queue_policy: dict = Field(alias="audioQueuePolicy")
    responses: list[VoiceResponse]
    input_gate: dict = Field(alias="inputGate")
    subtitle_plan: dict = Field(alias="subtitlePlan")
    audio_engine_hints: dict = Field(default_factory=dict, alias="audioEngineHints")
    notes: list[str] = Field(default_factory=list)
