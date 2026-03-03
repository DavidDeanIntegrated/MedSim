"""SSE (Server-Sent Events) streaming for live vital signs.

GET /sessions/{session_id}/stream — pushes vital signs every 5 sim-seconds.
The monitor panel can subscribe to this instead of polling.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import StreamingResponse

from app.api.deps import get_session_service
from app.services.session_service import SessionService

router = APIRouter(prefix="/sessions/{session_id}", tags=["stream"])

# Track active SSE connections per session
_active_streams: dict[str, list[asyncio.Queue]] = {}


def notify_session_update(session_id: str, patient_state: dict) -> None:
    """Called by turn processing to push updates to all connected SSE clients."""
    queues = _active_streams.get(session_id, [])
    hemo = patient_state.get("hemodynamics", {})
    resp = patient_state.get("respiratory", {})
    neuro = patient_state.get("neurologic", {})
    monitor = patient_state.get("monitor", {})
    scoring = patient_state.get("scoring", {})
    meds = patient_state.get("active_medications", [])
    meta = patient_state.get("case_metadata", {})

    event_data = {
        "type": "vitals",
        "simTimeSec": meta.get("time_elapsed_sec", 0),
        "vitals": {
            "sbp": hemo.get("sbp"),
            "dbp": hemo.get("dbp"),
            "map": hemo.get("map"),
            "hr": hemo.get("hr"),
            "rhythm": hemo.get("rhythm"),
            "spo2": resp.get("spo2"),
            "rr": resp.get("rr"),
        },
        "neuro": {
            "gcs": neuro.get("gcs"),
            "mentalStatus": neuro.get("mental_status"),
        },
        "alarms": monitor.get("waveform_flags", []),
        "activeInfusions": [
            {
                "medicationId": m.get("medication_id"),
                "rate": m.get("current_infusion_rate"),
                "active": m.get("active", False),
            }
            for m in meds
            if m.get("active")
        ],
        "score": scoring.get("final_score", 0),
        "status": meta.get("status", "running"),
    }

    for q in queues:
        try:
            q.put_nowait(event_data)
        except asyncio.QueueFull:
            pass  # drop if client is slow


async def _event_generator(
    session_id: str, request: Request, service: SessionService
) -> AsyncGenerator[str, None]:
    """Generate SSE events for a session."""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    # Register this connection
    if session_id not in _active_streams:
        _active_streams[session_id] = []
    _active_streams[session_id].append(queue)

    try:
        # Send initial state
        try:
            session = service.get_session(session_id)
            ps = session.get("patientState", {})
            if ps:
                notify_session_update(session_id, ps)
        except FileNotFoundError:
            yield f"event: error\ndata: {json.dumps({'error': 'Session not found'})}\n\n"
            return

        # Keep-alive and event loop
        last_keepalive = time.time()
        while True:
            if await request.is_disconnected():
                break

            try:
                event_data = await asyncio.wait_for(queue.get(), timeout=5.0)
                yield f"event: vitals\ndata: {json.dumps(event_data)}\n\n"
            except asyncio.TimeoutError:
                # Send keepalive every 15 seconds
                now = time.time()
                if now - last_keepalive >= 15:
                    yield f": keepalive\n\n"
                    last_keepalive = now
    finally:
        # Unregister on disconnect
        if session_id in _active_streams:
            try:
                _active_streams[session_id].remove(queue)
            except ValueError:
                pass
            if not _active_streams[session_id]:
                del _active_streams[session_id]


@router.get("/stream")
async def stream_vitals(session_id: str, request: Request) -> StreamingResponse:
    """SSE endpoint for live vital signs.

    Connect via EventSource:
        const es = new EventSource('/sessions/{id}/stream');
        es.addEventListener('vitals', e => updateMonitor(JSON.parse(e.data)));
    """
    service = get_session_service()
    try:
        service.get_session(session_id)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Session not found")

    return StreamingResponse(
        _event_generator(session_id, request, service),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
