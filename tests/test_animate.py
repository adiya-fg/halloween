"""Animated story sticker: layer rendering and the approval gate on /animate."""
import xml.etree.ElementTree as ET

import pytest

from app.stickers import TEMPLATES, render_sticker
from conftest import approve, new_request, request_id

GEN = {"template_id": "bat-moon"}


def approved_token(app, client, admin_client, name="Adiya"):
    res = new_request(client, name=name)
    client.post(f"/api/requests/{res['tracking_token']}/report-payment")
    assert approve(admin_client, request_id(app, res["request_code"])).status_code == 200
    return res["tracking_token"]


def test_approved_request_gets_three_layers(app, client, admin_client):
    token = approved_token(app, client, admin_client, name="Сараа")
    r = client.post(f"/api/requests/{token}/animate", json=GEN)
    assert r.status_code == 200, r.text
    layers = r.json()["layers"]
    assert set(layers) == {"base", "hero", "front"}
    for svg in layers.values():
        ET.fromstring(svg)  # each layer is a well-formed standalone SVG
    # The name lives only on the front layer; the background never repeats it.
    assert "Сараа" in layers["front"] and 'class="sticker-name"' not in layers["base"]
    assert 'class="sticker-name"' not in layers["hero"]
    assert "SAMPLE" not in "".join(layers.values())


def test_animate_rejects_unknown_design_and_extra_fields(app, client, admin_client):
    token = approved_token(app, client, admin_client)
    assert client.post(f"/api/requests/{token}/animate", json={"template_id": "nope"}).status_code == 422
    assert client.post(f"/api/requests/{token}/animate",
                       json={**GEN, "layer": "all"}).status_code == 422


def test_animate_with_bad_token_is_404(client):
    assert client.post("/api/requests/" + "x" * 43 + "/animate", json=GEN).status_code == 404


@pytest.mark.parametrize("template_id", sorted(TEMPLATES))
def test_layers_split_the_full_sticker(template_id):
    full = render_sticker(template_id, "Bat-Erdene")
    base = render_sticker(template_id, "Bat-Erdene", layer="base")
    hero = render_sticker(template_id, "Bat-Erdene", layer="hero")
    front = render_sticker(template_id, "Bat-Erdene", layer="front")
    assert len(base) < len(full) and len(hero) < len(full) and len(front) < len(full)
    assert "HALLOWEEN 2026" in base and "HALLOWEEN 2026" not in front
    assert "Bat-Erdene" in front


def test_escaping_holds_in_every_layer():
    nasty = '<script>alert(1)</script>&"'
    for layer in ("base", "hero", "front"):
        svg = render_sticker("pumpkin-king", nasty, layer=layer)
        assert "<script>" not in svg
        ET.fromstring(svg)


def test_unknown_layer_is_refused():
    with pytest.raises(ValueError):
        render_sticker("pumpkin-king", "A", layer="everything")
