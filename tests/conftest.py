import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

ADMIN_USER = "spooky_admin"
ADMIN_PASS = "Correct-Horse-Battery-26"


def make_settings(tmp_path, **overrides) -> Settings:
    s = Settings(
        app_env="test",
        secret_key="t" * 48,
        database_path=str(tmp_path / "test.db"),
        cookie_secure=False,
        rate_limit_enabled=False,
        max_open_requests_per_ip=0,
        payment_amount="500",
        payment_currency="JPY",
    )
    for k, v in overrides.items():
        setattr(s, k, v)
    s.validate()
    return s


@pytest.fixture
def app(tmp_path):
    application = create_app(make_settings(tmp_path))
    application.state.svc.create_admin(ADMIN_USER, ADMIN_PASS)
    return application


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def admin_client(app):
    """A separate client (own cookie jar) logged in as admin; exposes .csrf."""
    with TestClient(app) as c:
        r = c.post("/api/admin/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        assert r.status_code == 200, r.text
        c.csrf = r.json()["csrf_token"]
        yield c


def new_request(client, name="Adiya", **extra):
    r = client.post("/api/requests", json={"name": name, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def request_id(app, code):
    with app.state.svc.db.conn() as c:
        return c.execute("SELECT id FROM sticker_requests WHERE request_code = ?", (code,)).fetchone()[0]


def approve(admin_client, rid, **body):
    return admin_client.post(f"/api/admin/requests/{rid}/approve",
                             json={"confirm": True, **body}, headers={"X-CSRF-Token": admin_client.csrf})


def reject(admin_client, rid, reason="No matching transfer found"):
    return admin_client.post(f"/api/admin/requests/{rid}/reject",
                             json={"reason": reason}, headers={"X-CSRF-Token": admin_client.csrf})
