"""English / Mongolian localization of API messages."""
from app.i18n import MN, parse_lang, tr
from app.services import STATUS_MESSAGES

from conftest import new_request, reject, request_id

MN_HDR = {"Accept-Language": "mn"}


def test_parse_lang():
    assert parse_lang("mn") == "mn"
    assert parse_lang("mn-MN,en;q=0.8") == "mn"
    assert parse_lang("en-US,mn;q=0.5") == "en"
    assert parse_lang(None) == "en"


def test_all_status_messages_translated():
    for msg in STATUS_MESSAGES.values():
        assert msg in MN


def test_status_and_instructions_in_mongolian(client):
    res = new_request(client)
    token = res["tracking_token"]
    en = client.get(f"/api/requests/{token}").json()
    mn = client.get(f"/api/requests/{token}", headers=MN_HDR).json()
    assert en["status_message"] == "Please complete your bank transfer."
    assert mn["status_message"] == "Банкны шилжүүлгээ хийнэ үү."
    assert en["payment"]["instructions"] != mn["payment"]["instructions"]
    assert "хүсэлтийн дугаараа" in mn["payment"]["instructions"]

    r = client.post(f"/api/requests/{token}/report-payment", headers=MN_HDR).json()
    assert r["message"].startswith("Таны төлбөрийн мэдэгдлийг хүлээн авлаа")


def test_errors_in_mongolian(client):
    r = client.post("/api/requests", json={"name": "  "}, headers=MN_HDR)
    assert r.status_code == 422 and r.json()["detail"] == "Нэрээ оруулна уу."
    r = client.post("/api/requests", json={"name": "a" * 41}, headers=MN_HDR)
    assert r.json()["detail"] == "Нэр хамгийн ихдээ 40 тэмдэгт байх ёстой."
    r = client.get("/api/requests/" + "A" * 43, headers=MN_HDR)
    assert r.status_code == 404 and r.json()["detail"] == "Хүсэлт олдсонгүй."
    res = new_request(client)
    r = client.post(f"/api/requests/{res['tracking_token']}/generate",
                    json={"template_id": "black-cat"}, headers=MN_HDR)
    assert r.status_code == 403 and "баталгаажих хүртэл" in r.json()["detail"]


def test_rejection_next_steps_translated(app, client, admin_client):
    res = new_request(client)
    client.post(f"/api/requests/{res['tracking_token']}/report-payment")
    reject(admin_client, request_id(app, res["request_code"]))
    mn = client.get(f"/api/requests/{res['tracking_token']}", headers=MN_HDR).json()
    assert res["request_code"] in mn["next_steps"] and "зохион байгуулагч" in mn["next_steps"]


def test_mongolian_instructions_editable(admin_client):
    r = admin_client.patch("/api/admin/settings", json={"payment_instructions_mn": "Шинэ заавар"},
                           headers={"X-CSRF-Token": admin_client.csrf})
    assert r.status_code == 200 and r.json()["payment_instructions_mn"] == "Шинэ заавар"


def test_pattern_translation_fallback():
    assert tr("Something untranslated", "mn") == "Something untranslated"
    assert tr("Bank name must be 1–120 characters.", "mn") == "Банкны нэр 1–120 тэмдэгт байх ёстой."
    assert tr("Please enter your name.", "en") == "Please enter your name."
