from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import (
    get_engine_service,
    get_parser_service,
    get_session_service,
    get_voice_service,
)
from app.models.engine import ExecuteTurnRequest
from app.models.parser import ParseTurnRequest
from app.models.voice import BuildVoicePlanRequest
from app.services.engine_service import EngineService
from app.services.parser_service import ParserService
from app.services.session_service import SessionService
from app.services.voice_service import VoiceService

router = APIRouter(prefix="/sessions/{session_id}", tags=["turns"])


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

    parse_request = ParseTurnRequest(
        turnId=request["turnId"],
        timestampSimSec=request["timestampSimSec"],
        inputText=request["inputText"],
        parserMode=request["parserMode"],
        speaker=request.get("speaker", "resident"),
        activeInfusions=request.get("activeInfusions", []),
        contextHints=request.get("contextHints", {}),
    )
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
