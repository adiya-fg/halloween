"""Halloween character quiz: scoring, API, sticker integration and payment gating."""
import itertools
import xml.etree.ElementTree as ET

import pytest

from app.quiz import (ANSWER_MAP, CAT, CHARACTER_ORDER, GHOST, QUESTIONS, VAMPIRE, WIZARD,
                      QuizError, quiz_content, score)
from app.stickers import TEMPLATES, render_sticker

from conftest import approve, new_request, request_id

# --- Scoring --------------------------------------------------------------------------
EXPECTED_MAP = [
    # Q1 night,  Q2 strength,  Q3 colour (purple, orange, green, black),  Q4 ghost,  Q5 power,  Q6 phrase
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},
    {"A": VAMPIRE, "B": GHOST, "C": WIZARD, "D": CAT},
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},
]


def test_every_answer_maps_to_expected_character():
    assert len(ANSWER_MAP) == 6
    for q, (actual, expected) in enumerate(zip(ANSWER_MAP, EXPECTED_MAP)):
        assert actual == expected, f"question {q + 1}"
        assert sorted(actual.values()) == sorted(CHARACTER_ORDER)  # each answer -> one distinct character


@pytest.mark.parametrize("answers,expected", [
    (["A", "A", "C", "A", "A", "A"], WIZARD),
    (["B", "B", "A", "B", "B", "B"], VAMPIRE),
    (["C", "C", "B", "C", "C", "C"], GHOST),
    (["D", "D", "D", "D", "D", "D"], CAT),
])
def test_all_four_characters_can_be_produced(answers, expected):
    character, points = score(answers)
    assert character == expected and points[expected] == 6


def test_tie_break_latest_answer_wins():
    # 3 Wizard vs 3 Black Cat; Q6 picked Black Cat -> Black Cat.
    assert score(["A", "A", "C", "D", "D", "D"])[0] == CAT
    # Same tie, reversed order; Q6 picked Wizard -> Wizard.
    assert score(["D", "D", "D", "A", "A", "A"])[0] == WIZARD
    # 2-2-2 tie (Vampire, Ghost, Cat); Q6 picked Ghost.
    assert score(["B", "B", "B", "C", "D", "C"])[0] == GHOST
    # Q6/Q5 point to non-tied characters: walk back to the latest tied pick.
    # Wizard 2, Vampire 2, Cat 1, Ghost 1 -> Q4 picked Vampire.
    assert score(["A", "B", "C", "B", "D", "C"])[0] == VAMPIRE
    # Vampire 2, Wizard 2, Cat 1, Ghost 1 -> Q4 picked Wizard.
    assert score(["B", "A", "A", "A", "D", "C"])[0] == WIZARD


def test_scoring_is_deterministic_and_consistent_for_all_combinations():
    for combo in itertools.product("ABCD", repeat=6):
        character, points = score(list(combo))
        assert score(list(combo)) == (character, points)  # same input, same output
        assert sum(points.values()) == 6
        assert points[character] == max(points.values())  # winner always has the top score
        tied = [c for c in CHARACTER_ORDER if points[c] == points[character]]
        if len(tied) > 1:  # documented rule: latest answer among tied characters
            picks = [ANSWER_MAP[i][a] for i, a in enumerate(combo)]
            assert character == next(p for p in reversed(picks) if p in tied)


@pytest.mark.parametrize("bad", [None, [], ["A"] * 5, ["A"] * 7, ["A"] * 5 + ["E"], ["A"] * 5 + [1]])
def test_invalid_answers_rejected(bad):
    with pytest.raises(QuizError):
        score(bad)


def test_lowercase_answers_accepted():
    assert score(["d"] * 6)[0] == CAT


def test_quiz_content_both_languages():
    for lang in ("en", "mn"):
        content = quiz_content(lang)
        assert len(content["questions"]) == 6
        assert all(len(q["options"]) == 4 for q in content["questions"])
        assert set(content["characters"]) == set(CHARACTER_ORDER)
        for c in content["characters"].values():
            assert c["name"] and c["description"] and c["tagline"] and len(c["traits"]) == 3
    assert QUESTIONS["en"][0][0] == "How would you spend Halloween night?"
    assert quiz_content("en")["characters"][GHOST]["tagline"] == "Too cute to haunt, too fun to forget!"


# --- API --------------------------------------------------------------------------------
def test_quiz_api_and_result(client):
    content = client.get("/api/quiz").json()
    assert content["questions"][1]["options"][0]["text"] == "Intelligence and strategy."
    mn = client.get("/api/quiz", headers={"Accept-Language": "mn"}).json()
    assert mn["characters"][WIZARD]["name"] == "Шидтэн"

    r = client.post("/api/quiz/result", json={"answers": ["C", "C", "B", "C", "C", "C"]})
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == GHOST and body["name"] == "Friendly Ghost"
    assert body["traits"] == ["Friendly", "Creative", "Playful"]
    assert body["image"] == "/api/characters/FRIENDLY_GHOST.svg"

    assert client.post("/api/quiz/result", json={"answers": ["A"] * 5}).status_code == 422
    assert client.post("/api/quiz/result", json={"answers": ["Z"] * 6}).status_code == 422
    # A client-supplied result is never accepted.
    assert client.post("/api/quiz/result",
                       json={"answers": ["A"] * 6, "character": "VAMPIRE"}).status_code == 422


def test_character_images(client):
    for c in CHARACTER_ORDER:
        r = client.get(f"/api/characters/{c}.svg")
        assert r.status_code == 200 and r.headers["content-type"].startswith("image/svg+xml")
        ET.fromstring(r.text)
    assert client.get("/api/characters/DRAGON.svg").status_code == 404


def test_anonymous_quiz_preview_is_watermarked_and_stores_nothing(app, client):
    r = client.post("/api/quiz/preview", json={
        "answers": ["A", "A", "C", "A", "A", "A"], "name": "<b>Adiya</b>", "template_id": "black-cat"})
    assert r.status_code == 200
    svg = r.json()["svg"]
    root = ET.fromstring(svg)
    assert root.get("width") == "480"  # small preview only
    assert "PREVIEW" in svg and 'data-character="WIZARD"' in svg
    assert "&lt;b&gt;Adiya&lt;/b&gt;" in svg and "<b>" not in svg
    with app.state.svc.db.conn() as c:
        assert c.execute("SELECT COUNT(*) FROM sticker_requests").fetchone()[0] == 0
    assert client.post("/api/quiz/preview", json={
        "answers": ["A"] * 6, "name": " ", "template_id": "black-cat"}).status_code == 422


# --- Sticker integration -------------------------------------------------------------------
@pytest.mark.parametrize("template_id", list(TEMPLATES))
@pytest.mark.parametrize("character", list(CHARACTER_ORDER))
def test_personalized_sticker_uses_matching_illustration(template_id, character):
    svg = render_sticker(template_id, "Adiya", character=character,
                         character_label=f"YOUR CHARACTER: {character}", traits=["One", "Two", "Three"])
    ET.fromstring(svg)
    assert svg.count('data-character="') == 1
    assert f'data-character="{character}"' in svg
    assert f"YOUR CHARACTER: {character}" in svg and "One · Two · Three" in svg
    assert "HALLOWEEN 2026" in svg and "Adiya" in svg


def test_sticker_without_character_is_unchanged():
    assert "data-character" not in render_sticker("pumpkin-king", "Adiya")


def _create_with_quiz(client, answers, **extra):
    r = client.post("/api/requests", json={"name": "Adiya", "quiz_answers": answers, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_request_stores_server_computed_character_only(app, client):
    res = _create_with_quiz(client, ["A", "A", "C", "A", "A", "A"])
    status = client.get(f"/api/requests/{res['tracking_token']}").json()
    assert status["character"] == WIZARD
    with app.state.svc.db.conn() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(sticker_requests)")]
    assert "character" in cols and not any("answer" in col for col in cols)
    # The browser cannot dictate the character directly.
    r = client.post("/api/requests", json={"name": "X", "character": "VAMPIRE"})
    assert r.status_code == 422


def test_unapproved_users_get_only_watermarked_previews(app, client):
    res = _create_with_quiz(client, ["B", "B", "A", "B", "B", "B"])
    token = res["tracking_token"]
    for reported in (False, True):
        if reported:
            client.post(f"/api/requests/{token}/report-payment")
        pv = client.get(f"/api/requests/{token}/preview?template_id=bat-moon")
        assert pv.status_code == 200
        svg = pv.json()["svg"]
        assert "PREVIEW" in svg and 'data-character="VAMPIRE"' in svg
        assert ET.fromstring(svg).get("width") == "480"
        assert client.get(f"/api/requests/{token}/download").status_code == 403
        assert client.get(f"/api/requests/{token}/download?with_character=true").status_code == 403
        assert client.post(f"/api/requests/{token}/generate",
                           json={"template_id": "bat-moon"}).status_code == 403


def test_approved_user_downloads_character_sticker(app, client, admin_client):
    res = _create_with_quiz(client, ["D"] * 6)
    token = res["tracking_token"]
    client.post(f"/api/requests/{token}/report-payment")
    assert approve(admin_client, request_id(app, res["request_code"])).status_code == 200

    g = client.post(f"/api/requests/{token}/generate", json={"template_id": "witch-hat"})
    assert g.status_code == 200 and 'data-character="BLACK_CAT"' in g.json()["svg"]
    d = client.get(f"/api/requests/{token}/download")
    assert d.status_code == 200
    assert 'data-character="BLACK_CAT"' in d.text and "YOUR CHARACTER: BLACK CAT" in d.text
    assert "PREVIEW" not in d.text and "SAMPLE" not in d.text
    assert ET.fromstring(d.text).get("width") == "3000"
    assert "Independent · Observant · Clever" in d.text
    # Options: Mongolian label, no traits, or plain sticker without the character.
    mn = client.get(f"/api/requests/{token}/download?show_traits=false", headers={"Accept-Language": "mn"})
    assert "ТАНЫ ДҮР: ХАР МУУР" in mn.text and "Бие даасан" not in mn.text
    plain = client.get(f"/api/requests/{token}/download?with_character=false")
    assert "data-character" not in plain.text


def test_add_character_to_existing_request(app, client):
    res = new_request(client)
    token = res["tracking_token"]
    r = client.post(f"/api/requests/{token}/character", json={"answers": ["C", "C", "B", "C", "C", "C"]})
    assert r.status_code == 200 and r.json()["character"] == GHOST
    # Retaking the quiz replaces it.
    r = client.post(f"/api/requests/{token}/character", json={"answers": ["A", "A", "C", "A", "A", "A"]})
    assert r.json()["character"] == WIZARD
    assert client.post("/api/requests/" + "A" * 43 + "/character",
                       json={"answers": ["A"] * 6}).status_code == 404
    with app.state.svc.db.conn() as c:
        c.execute("UPDATE sticker_requests SET expires_at = '2000-01-01T00:00:00.000000Z'")
    assert client.post(f"/api/requests/{token}/character", json={"answers": ["A"] * 6}).status_code == 410


# --- Analytics -----------------------------------------------------------------------------
def test_aggregate_analytics(app, client, admin_client):
    assert client.post("/api/events", json={"event": "quiz_started"}).status_code == 200
    assert client.post("/api/events", json={"event": "approved_download"}).status_code == 422  # server-only
    client.post("/api/quiz/result", json={"answers": ["D"] * 6})
    res = _create_with_quiz(client, ["D"] * 6)
    client.post(f"/api/requests/{res['tracking_token']}/report-payment")
    approve(admin_client, request_id(app, res["request_code"]))
    client.get(f"/api/requests/{res['tracking_token']}/download")

    assert client.get("/api/admin/stats").status_code == 401  # admin only
    totals = admin_client.get("/api/admin/stats").json()["totals"]
    assert totals["quiz_started"] == 1 and totals["quiz_completed"] == 1
    assert totals["character:BLACK_CAT"] == 1
    assert totals["sticker_request_created"] == 1 and totals["approved_download"] == 1
    with app.state.svc.db.conn() as c:
        cols = [r["name"] for r in c.execute("PRAGMA table_info(analytics_counters)")]
    assert cols == ["event", "day", "count"]  # aggregate only, no personal data


def test_existing_database_is_migrated(tmp_path):
    import sqlite3
    from conftest import make_settings
    from app.main import create_app

    db = tmp_path / "test.db"
    old = sqlite3.connect(db)
    old.execute("CREATE TABLE sticker_requests (id INTEGER PRIMARY KEY, request_code TEXT, "
                "tracking_token_hash TEXT, idempotency_key_hash TEXT, client_ip_hash TEXT, name TEXT, "
                "email TEXT, template_id TEXT, amount INTEGER, currency TEXT, status TEXT, "
                "payment_reported_at TEXT, approved_at TEXT, rejected_at TEXT, rejection_reason TEXT, "
                "admin_notes TEXT, transaction_reference TEXT, approved_by INTEGER, rejected_by INTEGER, "
                "expires_at TEXT, created_at TEXT, updated_at TEXT)")
    old.commit()
    old.close()
    app = create_app(make_settings(tmp_path))
    with app.state.svc.db.conn() as c:
        assert "character" in [r["name"] for r in c.execute("PRAGMA table_info(sticker_requests)")]
