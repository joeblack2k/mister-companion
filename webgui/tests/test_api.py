import os
from pathlib import Path

test_state = Path(__file__).resolve().parent.parent / ".test-state"
os.environ.setdefault("APP_STATE_DIR", str(test_state))
os.environ.setdefault("APP_CONFIG_DIR", str(test_state / "config"))
os.environ.setdefault("APP_DATA_DIR", str(test_state / "data"))

from fastapi.testclient import TestClient

from backend.main import app


def test_health_is_available():
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert "connected" in data
    assert "state_dir" in data
    assert "config_dir" in data
    assert "data_dir" in data


def test_tabs_include_desktop_sections():
    client = TestClient(app)
    response = client.get("/api/tabs")
    assert response.status_code == 200
    names = {item["name"] for item in response.json()}
    assert "Flash SD" in names
    assert "MiSTer Settings" in names
    assert "SaveManager" in names


def test_profiles_crud_and_redaction():
    client = TestClient(app)
    created = client.post(
        "/api/profiles",
        json={"name": "Test MiSTer", "host": "192.0.2.10", "username": "root", "password": "secret"},
    )
    assert created.status_code == 200
    body = created.json()
    profile = next(item for item in body["profiles"] if item["host"] == "192.0.2.10")
    assert profile["has_password"] is True
    assert "password" not in profile

    active = client.put("/api/profiles/active", json={"id": profile["id"]})
    assert active.status_code == 200
    assert active.json()["active_profile_id"] == profile["id"]

    removed = client.delete(f"/api/profiles/{profile['id']}")
    assert removed.status_code == 200
    assert all(item["id"] != profile["id"] for item in removed.json()["profiles"])


def test_ini_schema_contains_friendly_metadata():
    client = TestClient(app)
    response = client.get("/api/ini/schema")
    assert response.status_code in {200, 404, 409}
    if response.status_code == 200:
        setting = response.json()["settings"][0]
        assert {"key", "label", "type", "what", "who", "value"}.issubset(setting)
