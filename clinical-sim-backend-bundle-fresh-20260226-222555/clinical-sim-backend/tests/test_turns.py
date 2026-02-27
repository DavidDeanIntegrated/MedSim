from fastapi.testclient import TestClient

from app.main import app


def test_create_session_start_case_and_process_turn() -> None:
    client = TestClient(app)

    session_resp = client.post(
        "/sessions",
        json={"userId": "tester", "deviceMode": "local_demo", "metadata": {}},
    )
    assert session_resp.status_code == 201
    session_id = session_resp.json()["sessionId"]

    start_resp = client.post(
        f"/sessions/{session_id}/start-case",
        json={"caseId": "htn_enceph_001", "difficulty": "moderate"},
    )
    assert start_resp.status_code == 200

    turn_resp = client.post(
        f"/sessions/{session_id}/turns",
        json={
            "turnId": "turn_1",
            "timestampSimSec": 0,
            "inputText": "Start nicardipine at 5 milligrams per hour and order a head CT",
            "parserMode": "text_to_actions",
            "speaker": "resident",
            "advanceTimeSec": 5,
            "includeFullState": True,
            "audioMode": "silent_subtitles_only",
        },
    )
    assert turn_resp.status_code == 200
    body = turn_resp.json()
    assert "parsedTurn" in body
    assert "engineResult" in body
    assert "voicePlan" in body
