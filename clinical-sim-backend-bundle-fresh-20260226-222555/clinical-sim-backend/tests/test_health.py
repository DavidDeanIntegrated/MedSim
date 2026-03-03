from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"


def test_root_serves_frontend_or_redirects() -> None:
    client = TestClient(app)
    response = client.get("/", follow_redirects=False)
    # Root serves frontend index.html (200) or redirects to docs (307)
    assert response.status_code in (200, 307)
