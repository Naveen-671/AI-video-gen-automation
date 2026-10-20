"""Integration tests for FastAPI endpoints (/health, /pause, /jobs) and static dashboard mount."""

import pytest
from fastapi.testclient import TestClient
from pathlib import Path
from backend.app.api.main import app
from backend.app.config import DB_PATH
from backend.app.db.connection import init_db

@pytest.fixture(autouse=True)
def setup_test_db(tmp_path: Path, monkeypatch):
    test_db = tmp_path / "test_api.db"
    init_db(test_db)
    monkeypatch.setattr("backend.app.api.main.DB_PATH", test_db)
    monkeypatch.setattr("backend.app.db.repository.DB_PATH", test_db)
    return test_db

@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c

def test_health_endpoint(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ("HEALTHY", "DEGRADED")
    assert data["db_connected"] is True
    assert "resources" in data
    assert "available_ram_gib" in data["resources"]
    assert "free_disk_gb" in data["resources"]
    assert "enabled_cost_classes" in data
    assert "metered" not in data["enabled_cost_classes"]

def test_pause_endpoint_lifecycle(client: TestClient):
    # Verify initial state
    h1 = client.get("/health").json()
    assert h1["global_pause"] is False

    # Pause
    p_res = client.post("/pause", json={"paused": True})
    assert p_res.status_code == 200
    assert p_res.json()["global_pause"] is True

    # Verify health reports pause
    h2 = client.get("/health").json()
    assert h2["global_pause"] is True

    # Resume
    r_res = client.post("/pause", json={"paused": False})
    assert r_res.status_code == 200
    assert r_res.json()["global_pause"] is False

def test_jobs_endpoint(client: TestClient):
    # Submit job
    payload = {
        "stage": "MOCK_SCRIPT",
        "payload": {"topic": "Mars Exploration"},
        "idempotency_key": "mars_001",
        "max_attempts": 3
    }
    create_res = client.post("/jobs", json=payload)
    assert create_res.status_code == 201
    assert "job_id" in create_res.json()

    # List jobs
    list_res = client.get("/jobs")
    assert list_res.status_code == 200
    jobs = list_res.json()
    assert len(jobs) >= 1
    assert any(j["idempotency_key"] == "mars_001" for j in jobs)

def test_static_dashboard_served(client: TestClient):
    # Root endpoint should serve the exported Next.js HTML page
    res = client.get("/")
    assert res.status_code == 200
    assert "AI Shorts" in res.text or "Mission Control" in res.text or "<!DOCTYPE html>" in res.text
