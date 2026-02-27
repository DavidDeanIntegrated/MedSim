from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from app.models.common import APIModel


class CreateSessionRequest(APIModel):
    user_id: str = Field(alias="userId")
    site_id: str | None = Field(default=None, alias="siteId")
    device_mode: Literal["local_demo", "local_server", "cloud"] = Field(default="local_demo", alias="deviceMode")
    metadata: dict[str, Any] = Field(default_factory=dict)


class SessionSummary(APIModel):
    session_id: str = Field(alias="sessionId")
    status: Literal["created", "active", "completed", "failed"]
    active_case_id: str | None = Field(default=None, alias="activeCaseId")
    started_at: datetime | None = Field(default=None, alias="startedAt")
    last_activity_at: datetime | None = Field(default=None, alias="lastActivityAt")


class CreateSessionResponse(APIModel):
    session_id: str = Field(alias="sessionId")
    created_at: datetime = Field(alias="createdAt")
    status: Literal["created", "active"]
    summary: SessionSummary


class StartCaseRequest(APIModel):
    case_id: str = Field(alias="caseId")
    difficulty: Literal["easy", "moderate", "hard", "expert"] = "moderate"
    custom_case_overrides: dict[str, Any] = Field(default_factory=dict, alias="customCaseOverrides")
    attending_entered_prompt: str | None = Field(default=None, alias="attendingEnteredPrompt")


class StartCaseResponse(APIModel):
    session_id: str = Field(alias="sessionId")
    case_id: str = Field(alias="caseId")
    status: Literal["running"]
    initial_state: dict[str, Any] = Field(alias="initialState")
    opening_script: dict[str, Any] = Field(alias="openingScript")


class ResetCaseResponse(APIModel):
    session_id: str = Field(alias="sessionId")
    case_id: str = Field(alias="caseId")
    status: Literal["reset"]
