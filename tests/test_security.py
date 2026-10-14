"""Authorization, CSRF, tampering, rate limiting and concurrency (spec cases 9, 10, 15)."""
import threading

from fastapi.testclient import TestClient

from conftest import ADMIN_PASS, ADMIN_USER, approve, make_settings, new_request, request_id
from app.main import create_app
from app.security import hash_password, verify_password


# 9
def test_unauthenticated_cannot_use_admin_api(app, client):
    res = new_request(client)
    client.post(f"/api/requests/{res['tracking_token']}/report-payment")
    rid = request_id(app, res["request_code"])
    checks = [
        client.get("/api/admin/requests"),
        client.get("/api/admin/settings"),
        client.get("/api/admin/audit"),
        client.get("/api/admin/me"),
        client.post(f"/api/admin/requests/{rid}/approve", json={"confirm": True}),
        client.post(f"/api/admin/requests/{rid}/reject", json={"reason": "nope nope"}),
        client.post(f"/api/admin/requests/{rid}/notes", json={"note": "hi"}),
        client.patch("/api/admin/settings", json={"amount": "1"}),
        client.post("/api/admin/logout"),
    ]
    assert all(r.status_code == 401 for r in checks), [r.status_code for r in checks]
    # A forged session cookie does not help either.
    client.cookies.set("hw_admin_session", "A" * 43)
    assert client.get("/api/admin/requests").status_code == 401
    assert client.get(f"/api/requests/{res['tracking_token']}").json()["status"] == "PAYMENT_REPORTED"


def test_csrf_required_for_admin_writes(app, client, admin_client):
    res = new_request(client)
    client.post(f"/api/requests/{res['tracking_token']}/report-payment")
    rid = request_id(app, res["request_code"])
    no_csrf = admin_client.post(f"/api/admin/requests/{rid}/approve", json={"confirm": True})
    bad_csrf = admin_client.post(f"/api/admin/requests/{rid}/approve", json={"confirm": True},
                                 headers={"X-CSRF-Token": "wrong"})
    assert no_csrf.status_code == 403 and bad_csrf.status_code == 403
    assert approve(admin_client, rid).status_code == 200


def test_approval_requires_explicit_confirmation(app, client, admin_client):
    res = new_request(client)
    client.post(f"/api/requests/{res['tracking_token']}/report-payment")
    rid = request_id(app, res["request_code"])
    h = {"X-CSRF-Token": admin_client.csrf}
    assert admin_client.post(f"/api/admin/requests/{rid}/approve", json={}, headers=h).status_code == 422
    assert admin_client.post(f"/api/admin/requests/{rid}/approve", json={"confirm": False},
                             headers=h).status_code == 422


# 10
def test_user_cannot_self_approve_by_tampering(app, client):
    # Extra fields in the create payload (status, amount, approval) are rejected outright.
    for extra in ({"status": "APPROVED"}, {"amount": 1}, {"currency": "XXX"}, {"approved": True}):
        r = client.post("/api/requests", json={"name": "Sneaky", **extra})
        assert r.status_code == 422, extra

    res = new_request(client)
    token = res["tracking_token"]
    client.post(f"/api/requests/{token}/report-payment")
    rid = request_id(app, res["request_code"])

    # Guessing user-side approve URLs or calling admin endpoints with the token.
    assert client.post(f"/api/requests/{token}/approve").status_code in (404, 405)
    assert client.patch(f"/api/requests/{token}", json={"status": "APPROVED"}).status_code == 405
    assert client.post(f"/api/admin/requests/{rid}/approve", json={"confirm": True},
                       headers={"X-CSRF-Token": token}).status_code == 401
    # Spoofed status in the generate payload is rejected and ignored.
    r = client.post(f"/api/requests/{token}/generate",
                    json={"template_id": "pumpkin-king", "status": "APPROVED"})
    assert r.status_code == 422
    assert client.get(f"/api/requests/{token}/download?status=APPROVED").status_code == 403
    assert client.get(f"/api/requests/{token}").json()["status"] == "PAYMENT_REPORTED"


# 15
def test_concurrent_approvals_are_consistent(app, client, admin_client):
    res = new_request(client)
    client.post(f"/api/requests/{res['tracking_token']}/report-payment")
    rid = request_id(app, res["request_code"])

    svc = app.state.svc
    results = []
    barrier = threading.Barrier(8)

    def worker(i):
        barrier.wait()
        try:
            if i % 2:
                svc.approve(rid, 1, f"TX-{i}")
            else:
                svc.reject(rid, 1, f"reason {i}")
            results.append("ok")
        except Exception as e:  # ServiceError expected for losers
            results.append(getattr(e, "status_code", repr(e)))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results.count("ok") == 1, results
    assert all(r in ("ok", 409) for r in results), results
    with svc.db.conn() as c:
        row = c.execute("SELECT * FROM sticker_requests WHERE id = ?", (rid,)).fetchone()
        decisions = c.execute("SELECT COUNT(*) FROM audit_logs WHERE action IN "
                              "('request.approved', 'request.rejected')").fetchone()[0]
    assert decisions == 1
    if row["status"] == "APPROVED":
        assert row["approved_at"] and row["rejected_at"] is None and row["rejection_reason"] is None
    else:
        assert row["status"] == "REJECTED"
        assert row["rejected_at"] and row["approved_at"] is None and row["transaction_reference"] is None

    # Also through the HTTP API: the second approval loses.
    assert approve(admin_client, rid).status_code == 409


def test_login_rate_limited_and_audited(tmp_path):
    app = create_app(make_settings(tmp_path, rate_limit_enabled=True))
    app.state.svc.create_admin(ADMIN_USER, ADMIN_PASS)
    with TestClient(app) as c:
        codes = [c.post("/api/admin/login", json={"username": ADMIN_USER, "password": "wrong-password!"}).status_code
                 for _ in range(6)]
        assert codes[:5] == [401] * 5 and codes[5] == 429
        # Even the right password is blocked while the username is locked out.
        assert c.post("/api/admin/login", json={"username": ADMIN_USER, "password": ADMIN_PASS}).status_code == 429
    with app.state.svc.db.conn() as conn:
        n = conn.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'admin.login_failed'").fetchone()[0]
    assert n == 5


def test_public_create_rate_limited(tmp_path):
    app = create_app(make_settings(tmp_path, rate_limit_enabled=True))
    with TestClient(app) as c:
        codes = [c.post("/api/requests", json={"name": f"N{i}"}).status_code for i in range(11)]
    assert codes.count(201) == 10 and codes[-1] == 429


def test_open_requests_per_ip_capped(tmp_path):
    app = create_app(make_settings(tmp_path, max_open_requests_per_ip=2))
    with TestClient(app) as c:
        codes = [c.post("/api/requests", json={"name": f"N{i}"}).status_code for i in range(3)]
    assert codes == [201, 201, 429]


def test_passwords_hashed_and_tokens_not_stored(app, client):
    res = new_request(client)
    with app.state.svc.db.conn() as c:
        admin = c.execute("SELECT password_hash FROM admins").fetchone()[0]
        dump = "\n".join(str(tuple(r)) for r in c.execute("SELECT * FROM sticker_requests"))
    assert ADMIN_PASS not in admin and admin.startswith("scrypt$")
    assert verify_password(ADMIN_PASS, admin) and not verify_password("nope", admin)
    assert hash_password("x" * 12) != hash_password("x" * 12)  # salted
    assert res["tracking_token"] not in dump


def test_login_logout_and_session_cookie_flags(app):
    with TestClient(app) as c:
        r = c.post("/api/admin/login", json={"username": ADMIN_USER, "password": ADMIN_PASS})
        cookie = r.headers["set-cookie"].lower()
        assert "httponly" in cookie and "samesite=strict" in cookie
        csrf = r.json()["csrf_token"]
        assert c.get("/api/admin/me").status_code == 200
        assert c.post("/api/admin/logout", headers={"X-CSRF-Token": csrf}).status_code == 200
        assert c.get("/api/admin/me").status_code == 401


def test_security_headers_and_xss_safe_rendering(client):
    r = client.get("/")
    assert "script-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    res = new_request(client, name="<img src=x onerror=alert(1)>")
    # JSON API returns raw data (frontend uses textContent); SVG output must be escaped.
    token = res["tracking_token"]
    from app.stickers import render_sticker
    svg = render_sticker("friendly-ghost", "<img src=x onerror=alert(1)>")
    assert "<img" not in svg and "&lt;img src=x onerror=alert(1)&gt;" in svg
    assert client.get(f"/api/requests/{token}").headers["cache-control"] == "no-store"


def test_settings_change_is_audited(app, admin_client):
    r = admin_client.patch("/api/admin/settings", json={"account_number": "1234567890"},
                           headers={"X-CSRF-Token": admin_client.csrf})
    assert r.status_code == 200
    audit = admin_client.get("/api/admin/audit").json()["items"]
    entry = next(a for a in audit if a["action"] == "settings.update")
    assert entry["actor"] == ADMIN_USER
    assert entry["details"]["account_number"]["to"].endswith("7890")
    assert "1234567890" not in str(entry["details"])  # masked
