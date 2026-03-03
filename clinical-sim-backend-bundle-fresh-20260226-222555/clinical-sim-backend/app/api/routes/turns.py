import logging
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_engine_service,
    get_llm_parser_service,
    get_parser_service,
    get_session_service,
    get_voice_service,
)
from app.api.routes.stream import notify_session_update
from app.core.config import get_settings
from app.models.engine import ExecuteTurnRequest
from app.models.parser import ParseTurnRequest
from app.models.voice import BuildVoicePlanRequest
from app.services.engine_service import EngineService
from app.services.parser_service import ParserService
from app.services.session_service import SessionService
from app.services.voice_service import VoiceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}", tags=["turns"])


def _try_llm_parse(parse_request: ParseTurnRequest):
    """Attempt LLM parsing; returns None on failure."""
    try:
        llm_parser = get_llm_parser_service()
        return llm_parser.parse_turn(parse_request)
    except (ValueError, Exception) as e:
        logger.warning("LLM parser failed, falling back to rule-based: %s", e)
        return None


@router.post("/parse-turn")
def parse_turn(
    session_id: str,
    request: ParseTurnRequest,
    session_service: SessionService = Depends(get_session_service),
    parser_service: ParserService = Depends(get_parser_service),
):
    try:
        session_service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if request.parser_mode == "llm" or (request.parser_mode != "rule" and get_settings().llm_parser_enabled):
        result = _try_llm_parse(request)
        if result is not None:
            return result

    return parser_service.parse_turn(request)


@router.post("/execute-turn")
def execute_turn(
    session_id: str,
    request: ExecuteTurnRequest,
    session_service: SessionService = Depends(get_session_service),
    engine_service: EngineService = Depends(get_engine_service),
):
    try:
        session = session_service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    patient_state = session.get("patientState")
    if not patient_state:
        raise HTTPException(status_code=400, detail="No active case state")

    result = engine_service.execute_turn(patient_state, request)
    transcript_entry = {
        "turnId": request.parsed_turn.turn_id,
        "rawInput": request.parsed_turn.raw_input,
        "parsedActions": [a.model_dump(mode="json", by_alias=True) for a in request.parsed_turn.actions],
    }
    session_service.update_session_state(
        session_id=session_id,
        patient_state=result.updated_patient_state or patient_state,
        new_events=[event.model_dump(mode="json", by_alias=True) for event in result.new_events],
        transcript_entry=transcript_entry,
    )

    if result.updated_patient_state:
        notify_session_update(session_id, result.updated_patient_state)

    return result


@router.post("/voice-plan")
def build_voice_plan(
    session_id: str,
    request: BuildVoicePlanRequest,
    session_service: SessionService = Depends(get_session_service),
    voice_service: VoiceService = Depends(get_voice_service),
):
    try:
        session_service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return voice_service.build_voice_plan(request)


@router.post("/turns")
def process_turn(
    session_id: str,
    request: dict,
    session_service: SessionService = Depends(get_session_service),
    parser_service: ParserService = Depends(get_parser_service),
    engine_service: EngineService = Depends(get_engine_service),
    voice_service: VoiceService = Depends(get_voice_service),
):
    try:
        session = session_service.get_session(session_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    parser_mode = request.get("parserMode", "rule")

    # Auto-generate turnId and timestampSimSec if not provided (BUG-6 fix)
    turn_id = request.get("turnId") or f"turn-{uuid4().hex[:8]}"
    patient_state = session.get("patientState", {})
    timestamp_sim_sec = request.get("timestampSimSec")
    if timestamp_sim_sec is None:
        timestamp_sim_sec = patient_state.get("case_metadata", {}).get("time_elapsed_sec", 0)

    parse_request = ParseTurnRequest(
        turnId=turn_id,
        timestampSimSec=timestamp_sim_sec,
        inputText=request["inputText"],
        parserMode=parser_mode,
        speaker=request.get("speaker", "resident"),
        activeInfusions=request.get("activeInfusions", []),
        contextHints=request.get("contextHints", {}),
    )

    parsed = None
    if parser_mode == "llm" or (parser_mode != "rule" and get_settings().llm_parser_enabled):
        parsed = _try_llm_parse(parse_request)

    if parsed is None:
        parsed = parser_service.parse_turn(parse_request)

    patient_state = session.get("patientState")
    if not patient_state:
        raise HTTPException(status_code=400, detail="No active case state")

    execute_request = ExecuteTurnRequest(
        parsedTurn=parsed,
        advanceTimeSec=request.get("advanceTimeSec", 5),
        includeFullState=request.get("includeFullState", True),
    )
    engine_result = engine_service.execute_turn(patient_state, execute_request)

    session_service.update_session_state(
        session_id=session_id,
        patient_state=engine_result.updated_patient_state or patient_state,
        new_events=[event.model_dump(mode="json", by_alias=True) for event in engine_result.new_events],
        transcript_entry={
            "turnId": parsed.turn_id,
            "rawInput": parsed.raw_input,
            "parsedTurn": parsed.model_dump(mode="json", by_alias=True),
        },
    )

    if engine_result.updated_patient_state:
        notify_session_update(session_id, engine_result.updated_patient_state)

    voice_request = BuildVoicePlanRequest(
        engineResult=engine_result,
        audioMode=request.get("audioMode", "local_tts"),
        allowInterruptions=True,
    )
    voice_plan = voice_service.build_voice_plan(voice_request)

    return {
        "parsedTurn": parsed,
        "engineResult": engine_result,
        "voicePlan": voice_plan,
    }
