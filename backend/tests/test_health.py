from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_health_ok():
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert "request_id" in body
    assert isinstance(body["request_id"], str)
    assert body["request_id"]
    assert body["data"] == {"status": "ok"}
