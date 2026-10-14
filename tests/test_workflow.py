"""End-to-end request lifecycle tests (spec cases 1–8, 11, 13, 14)."""
import xml.etree.ElementTree as ET

from conftest import approve, new_request, reject, request_id

GEN = {"template_id": "pumpkin-king", "transparent": True}


def report(client, token):
    return client.post(f"/api/requests/{token}/report-payment")


def assert_locked(client, token, expected=403):
    g = client.post(f"/api/requests/{token}/generate", json=GEN)
    d = client.get(f"/api/requests/{token}/download")
    assert g.status_code == expected, g.text
    assert d.status_code == expected, d.text
    assert "<svg" not in g.text and "<svg" not in d.text
    status = client.get(f"/api/requests/{token}").json()
    assert status["can_generate"] is False


# 1
def test_new_request_starts_pending(client):
    res = new_request(client)
    assert res["status"] == "PENDING_PAYMENT"
    assert res["request_code"].startswith("HW26-") and len(res["request_code"]) == 11
    data = client.get(f"/api/requests/{res['tracking_token']}").json()
    assert data["status"] == "PENDING_PAYMENT"
    assert data["status_message"] == "Please complete your bank transfer."
    assert data["amount_display"] == "500 JPY"
    assert data["payment"]["reference"] == res["request_code"]
    assert data["payment"]["bank_name"]
    assert "id" not in data and "admin_notes" not in data and "email" not in data


# 2
def test_report_payment_changes_status(client):
    res = new_request(client)
    r = report(client, res["tracking_token"])
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "PAYMENT_REPORTED"
    assert body["payment_reported_at"]
    assert "administrator verification" in body["message"]
    # Repeated reports are idempotent: same timestamp, no new state.
    again = report(client, res["tracking_token"]).json()
    assert again["status"] == "PAYMENT_REPORTED"
    assert again["payment_reported_at"] == body["payment_reported_at"]


# 3
def test_pending_cannot_generate_or_download(client):
    res = new_request(client)
    assert_locked(client, res["tracking_token"])


# 4
def test_reported_cannot_generate_or_download(client):
    res = new_request(client)
    report(client, res["tracking_token"])
    assert_locked(client, res["tracking_token"])


# 5 + 6
def test_admin_approves_then_user_generates_and_downloads(app, client, admin_client):
    res = new_request(client, name="Бат-Эрдэнэ")
    token = res["tracking_token"]
    report(client, token)
    rid = request_id(app, res["request_code"])

    r = approve(admin_client, rid, transaction_reference="TX-12345")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "APPROVED" and body["approved_at"]
    assert body["approved_by"] == "spooky_admin"
    assert body["transaction_reference"] == "TX-12345"

    status = client.get(f"/api/requests/{token}").json()
    assert status["status"] == "APPROVED" and status["can_generate"] is True
    assert "payment" not in status

    g = client.post(f"/api/requests/{token}/generate", json={"template_id": "black-cat", "transparent": False})
    assert g.status_code == 200
    svg = g.json()["svg"]
    ET.fromstring(svg)
    assert "Бат-Эрдэнэ" in svg

    d = client.get(f"/api/requests/{token}/download")  # uses the template saved by generate
    assert d.status_code == 200
    assert d.headers["content-type"].startswith("image/svg+xml")
    assert "attachment" in d.headers["content-disposition"] and "black-cat" in d.headers["content-disposition"]
    root = ET.fromstring(d.text)
    assert int(root.get("width")) >= 3000 and int(root.get("height")) >= 3000
    assert "Бат-Эрдэнэ" in d.text

    # Approval is recorded in the audit log.
    with app.state.svc.db.conn() as c:
        actions = [r[0] for r in c.execute("SELECT action FROM audit_logs")]
    assert "request.approved" in actions and "request.report_payment" in actions


# 7 + 8
def test_admin_rejects_and_user_stays_locked(app, client, admin_client):
    res = new_request(client)
    token = res["tracking_token"]
    report(client, token)
    rid = request_id(app, res["request_code"])

    assert reject(admin_client, rid, reason="").status_code == 422  # reason required
    r = reject(admin_client, rid)
    assert r.status_code == 200
    assert r.json()["status"] == "REJECTED" and r.json()["rejected_at"]

    status = client.get(f"/api/requests/{token}").json()
    assert status["status"] == "REJECTED"
    assert status["rejection_reason"] == "No matching transfer found"
    assert res["request_code"] in status["next_steps"]
    assert_locked(client, token)


# 11
def test_invalid_status_transitions_rejected(app, client, admin_client):
    # Approving/rejecting a request that was never reported.
    res = new_request(client)
    rid = request_id(app, res["request_code"])
    assert approve(admin_client, rid).status_code == 409
    assert reject(admin_client, rid).status_code == 409

    # Approving twice / rejecting after approval / reporting after approval.
    report(client, res["tracking_token"])
    assert approve(admin_client, rid).status_code == 200
    assert approve(admin_client, rid).status_code == 409
    assert reject(admin_client, rid).status_code == 409
    assert report(client, res["tracking_token"]).status_code == 409

    # Rejected requests cannot be approved later.
    res2 = new_request(client, name="Second")
    rid2 = request_id(app, res2["request_code"])
    report(client, res2["tracking_token"])
    assert reject(admin_client, rid2).status_code == 200
    assert approve(admin_client, rid2).status_code == 409
    assert report(client, res2["tracking_token"]).status_code == 409

    assert approve(admin_client, 999999).status_code == 404


# 13
def test_repeated_submissions_do_not_duplicate(app, client):
    payload = {"name": "Dup Tester", "client_key": "k" * 32}
    first = client.post("/api/requests", json=payload)
    second = client.post("/api/requests", json=payload)
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json()["duplicate"] is True
    assert second.json()["request_code"] == first.json()["request_code"]
    assert "tracking_token" not in second.json()
    with app.state.svc.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM sticker_requests").fetchone()[0] == 1

    token = first.json()["tracking_token"]
    for _ in range(3):
        assert report(client, token).status_code == 200
    with app.state.svc.db.conn() as c:
        n = c.execute("SELECT COUNT(*) FROM audit_logs WHERE action = 'request.report_payment'").fetchone()[0]
    assert n == 1


# 14
def test_invalid_and_expired_tokens_rejected(app, client):
    for bad in ["nope", "A" * 43, "../../etc/passwd", "x" * 200]:
        for method, suffix in (("get", ""), ("post", "/report-payment"), ("get", "/download")):
            r = getattr(client, method)(f"/api/requests/{bad}{suffix}")
            assert r.status_code in (404, 405), (bad, suffix, r.status_code)
        assert client.post(f"/api/requests/{bad}/generate", json=GEN).status_code == 404

    res = new_request(client)
    with app.state.svc.db.conn() as c:
        c.execute("UPDATE sticker_requests SET expires_at = '2000-01-01T00:00:00.000000Z'")
    token = res["tracking_token"]
    status = client.get(f"/api/requests/{token}").json()
    assert status["status"] == "EXPIRED"
    assert status["status_message"] == "This request has expired."
    assert "payment" not in status
    assert report(client, token).status_code == 410
    assert_locked(client, token, expected=410)


def test_amount_is_locked_in_at_creation(app, client, admin_client):
    res = new_request(client)
    r = admin_client.patch("/api/admin/settings", json={"amount": "12.50", "currency": "usd"},
                           headers={"X-CSRF-Token": admin_client.csrf})
    assert r.status_code == 200, r.text
    assert r.json()["amount_minor"] == 1250 and r.json()["currency"] == "USD"
    old = client.get(f"/api/requests/{res['tracking_token']}").json()
    assert old["amount_display"] == "500 JPY"
    new = new_request(client, name="Newer")
    assert client.get(f"/api/requests/{new['tracking_token']}").json()["amount_display"] == "12.50 USD"
    bad = admin_client.patch("/api/admin/settings", json={"amount": "1.234"},
                             headers={"X-CSRF-Token": admin_client.csrf})
    assert bad.status_code == 422


def test_name_validation(client):
    assert client.post("/api/requests", json={"name": "   "}).status_code == 422
    assert client.post("/api/requests", json={"name": "a" * 41}).status_code == 422
    assert client.post("/api/requests", json={"name": "bad\x00name"}).status_code == 422
    assert client.post("/api/requests", json={"name": "ok", "email": "not-an-email"}).status_code == 422
    assert client.post("/api/requests", json={"name": "ok", "template_id": "nope"}).status_code == 422
    r = new_request(client, name="   Spaced    Out   ")
    assert client.get(f"/api/requests/{r['tracking_token']}").json()["name"] == "Spaced Out"


def test_honeypot_blocks_bots(client):
    r = client.post("/api/requests", json={"name": "Bot", "website": "http://spam"})
    assert r.status_code == 400


def test_mnt_amounts_have_no_decimals():
    from app.services import format_amount, parse_amount
    assert parse_amount("1000", "MNT") == 1000
    assert format_amount(1000, "MNT") == "1,000 MNT"
