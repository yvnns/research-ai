import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api import routes as routes_module


@pytest.fixture
def client(monkeypatch):
    async def fake_run(search_id, refresh=False):
        from app.database import db

        await db.update_search(search_id, status="completed", stage="Finalizado", progress=100, message="ok", summary="resumo teste", result_json=None)
    monkeypatch.setattr(routes_module, "run_search", fake_run)
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_create_search_and_status(client):
    r = client.post("/api/search", json={"query": "teste pesquisa", "deep": False})
    assert r.status_code == 200
    sid = r.json()["id"]
    # allow background task
    import time
    time.sleep(0.5)
    st = client.get(f"/api/search/{sid}/status")
    assert st.status_code == 200
    assert st.json()["status"] in ("queued", "running", "completed")


def test_history(client):
    client.post("/api/search", json={"query": "outra pesquisa", "deep": False})
    import time
    time.sleep(0.5)
    r = client.get("/api/history")
    assert r.status_code == 200
    assert isinstance(r.json(), list)