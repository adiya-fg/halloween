"""Sticker rendering: long names, international text, determinism (spec case 12)."""
import xml.etree.ElementTree as ET

import pytest

from app.stickers import (MIN_FS, NAME_MAX_WIDTH, TEMPLATES, layout_name, render_sticker, text_em)

SVG_NS = "{http://www.w3.org/2000/svg}"
NAMES = [
    "Adiya",
    "Бат-Эрдэнэ Ганболд",        # Mongolian Cyrillic
    "ᠮᠣᠩᠭᠣᠯ",                    # Traditional Mongolian script
    "山田 花子",                  # Japanese
    "やまだ・ハナコ",
    "José Ñúñez-Øster",
    "W" * 40,                     # widest Latin, max length
    "Maximilian Alexander Montgomery-Smythe",
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらり",  # 40 CJK
]


def name_texts(svg: str):
    root = ET.fromstring(svg)
    return [t for t in root.iter(f"{SVG_NS}text") if t.get("data-fit-max")]


@pytest.mark.parametrize("template_id", list(TEMPLATES))
@pytest.mark.parametrize("name", NAMES)
def test_renders_valid_svg_with_name(template_id, name):
    svg = render_sticker(template_id, name)
    root = ET.fromstring(svg)
    assert root.get("width") == "3000" and root.get("height") == "3000"
    texts = name_texts(svg)
    assert " ".join(t.text for t in texts) == " ".join(name.split())


@pytest.mark.parametrize("name", NAMES)
def test_name_never_exceeds_banner(name):
    lay = layout_name(name)
    assert lay.font_size >= MIN_FS
    widest = max(text_em(line) for line in lay.lines) * lay.font_size
    # Either the conservative estimate fits, or textLength forces it to fit.
    assert widest <= NAME_MAX_WIDTH + 0.01 or lay.compress
    svg = render_sticker("pumpkin-king", name)
    for t in name_texts(svg):
        if lay.compress:
            assert t.get("textLength") == str(NAME_MAX_WIDTH)
            assert t.get("lengthAdjust") == "spacingAndGlyphs"


def test_long_names_scale_down_and_wrap():
    short = layout_name("Bo")
    long = layout_name("Maximilian Alexander Montgomery-Smythe")
    assert short.font_size > long.font_size
    assert len(long.lines) == 2
    assert layout_name("W" * 40).compress is True


def test_rendering_is_deterministic_and_escaped():
    a = render_sticker("witch-hat", "A & B <c>")
    assert a == render_sticker("witch-hat", "A & B <c>")
    assert "A &amp; B &lt;c&gt;" in a
    ET.fromstring(a)


def test_transparent_option():
    transparent = render_sticker("bat-moon", "X", transparent=True)
    opaque = render_sticker("bat-moon", "X", transparent=False)
    assert '<rect width="1000" height="1000" fill="#1A0B2E"/>' in opaque
    assert '<rect width="1000" height="1000" fill="#1A0B2E"/>' not in transparent


def test_unknown_template():
    with pytest.raises(KeyError):
        render_sticker("nope", "x")


def test_public_previews_are_watermarked(client):
    r = client.get("/api/templates/pumpkin-king/preview.svg")
    assert r.status_code == 200 and "SAMPLE" in r.text
    assert ET.fromstring(r.text).get("width") == "480"
    assert client.get("/api/templates/nope/preview.svg").status_code == 404
