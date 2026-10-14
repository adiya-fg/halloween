"""Deterministic Halloween 2026 sticker artwork rendered as SVG.

Artwork is pure vector (no paid AI APIs, no randomness), so a given
(template, name, options) always yields byte-identical output. The SVG is
rasterised to a >=3000x3000 PNG in the browser (see static/js/sticker.js).

The name is XML-escaped and laid out with a conservative width estimate so it
never overflows the banner; every name ``<text>`` also carries
``data-fit-max`` so the client can apply exact measured fitting.
"""
from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass
from xml.sax.saxutils import escape

VIEW = 1000
OUTPUT_PX = 3000

FONT_STACK = (
    "'Segoe UI Black','Arial Black','Noto Sans JP','Noto Sans','Hiragino Sans',"
    "'Yu Gothic','Meiryo','Noto Sans Mongolian','Mongolian Baiti',"
    "'Segoe UI','Helvetica Neue',Arial,sans-serif"
)

# Colours
ORANGE, DEEP_ORANGE, YELLOW = "#FF7A1A", "#E85D04", "#FFD23F"
NIGHT, PURPLE, VIOLET = "#1A0B2E", "#2B1240", "#5B2A86"
GHOST, MOON = "#F8F4FF", "#FFF3C4"


@dataclass(frozen=True)
class Template:
    id: str
    name: str
    description: str


TEMPLATES: dict[str, Template] = {t.id: t for t in (
    Template("pumpkin-king", "Pumpkin King", "A glowing jack-o'-lantern under the moon"),
    Template("friendly-ghost", "Friendly Ghost", "A cute ghost with candy corn"),
    Template("bat-moon", "Bat Moon", "Bats swarming a harvest moon"),
    Template("witch-hat", "Witch Hat", "A starry witch's hat"),
    Template("spider-web", "Spider Web", "A dangling spider and a cobweb"),
    Template("black-cat", "Black Cat", "A black cat silhouetted by the moon"),
)}
DEFAULT_TEMPLATE = "pumpkin-king"

# --- Name layout ---------------------------------------------------------------
BANNER = dict(x=90, y=690, w=820, h=160)
NAME_MAX_WIDTH = 740
NAME_CENTER_Y = BANNER["y"] + BANNER["h"] / 2
SINGLE_MAX_FS, DOUBLE_MAX_FS, MIN_FS = 120, 66, 34
LABEL_MAX_WIDTH, TRAITS_MAX_WIDTH = 640, 390

_XML_INVALID = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def char_em(ch: str) -> float:
    """Conservative (over-)estimate of an advance width in em for a heavy font."""
    if unicodedata.combining(ch) or unicodedata.category(ch) in ("Mn", "Me", "Cf"):
        return 0.0
    if ch.isspace():
        return 0.34
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 1.02
    if "᠀" <= ch <= "᢯":  # Mongolian script
        return 0.75
    if ch.isdigit():
        return 0.68
    if ch.isupper():
        return 0.82 if ord(ch) < 0x250 else 0.9
    if ch.isalpha():
        return 0.66 if ord(ch) < 0x250 else 0.72
    return 0.45


def text_em(text: str) -> float:
    return sum(char_em(c) for c in text)


@dataclass
class NameLayout:
    lines: list[str]
    font_size: float
    compress: bool  # True -> apply textLength to guarantee fit


def layout_name(name: str) -> NameLayout:
    name = " ".join(name.split()) or "?"
    em = max(text_em(name), 0.5)
    fs_single = min(SINGLE_MAX_FS, NAME_MAX_WIDTH / em)
    if fs_single >= 56 or " " not in name:
        if fs_single >= MIN_FS:
            return NameLayout([name], fs_single, False)
        return NameLayout([name], MIN_FS, True)

    # Split at the space that best balances the two lines.
    words = name.split(" ")
    best = None
    for i in range(1, len(words)):
        a, b = " ".join(words[:i]), " ".join(words[i:])
        widest = max(text_em(a), text_em(b))
        if best is None or widest < best[0]:
            best = (widest, a, b)
    widest, a, b = best
    fs_double = min(DOUBLE_MAX_FS, NAME_MAX_WIDTH / widest)
    if fs_double <= fs_single:
        return NameLayout([name], max(fs_single, MIN_FS), fs_single < MIN_FS)
    if fs_double >= MIN_FS:
        return NameLayout([a, b], fs_double, False)
    return NameLayout([a, b], MIN_FS, True)


def clean_text(text: str) -> str:
    return _XML_INVALID.sub("", unicodedata.normalize("NFC", text))


# --- Drawing helpers --------------------------------------------------------------
def _f(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


def g(content: str, x: float = 0, y: float = 0, s: float = 1, rot: float = 0) -> str:
    t = f"translate({_f(x)} {_f(y)})"
    if rot:
        t += f" rotate({_f(rot)})"
    if s != 1:
        t += f" scale({_f(s)})"
    return f'<g transform="{t}">{content}</g>'


def star(x, y, s=1.0, color="#FFE9A8"):
    return g(f'<path d="M0,-10 Q2,-2 10,0 Q2,2 0,10 Q-2,2 -10,0 Q-2,-2 0,-10 Z" fill="{color}"/>', x, y, s)


def stars(points):
    return "".join(star(x, y, s) for x, y, s in points)


def moon(x, y, r, fill="url(#moonGrad)"):
    craters = "".join(
        f'<circle cx="{_f(x + dx * r)}" cy="{_f(y + dy * r)}" r="{_f(cr * r)}" fill="#EBCB6B" opacity="0.45"/>'
        for dx, dy, cr in ((-0.35, -0.2, 0.16), (0.3, 0.25, 0.12), (0.05, 0.5, 0.08), (0.4, -0.35, 0.07))
    )
    return f'<circle cx="{x}" cy="{y}" r="{r}" fill="{fill}"/>{craters}'


BAT_PATH = (
    "M0,-6 C4,-16 8,-20 10,-26 L14,-14 C24,-24 40,-26 54,-16 C46,-12 42,-4 44,6 "
    "C36,0 28,2 24,10 C18,4 10,6 6,14 L0,20 L-6,14 C-10,6 -18,4 -24,10 "
    "C-28,2 -36,0 -44,6 C-42,-4 -46,-12 -54,-16 C-40,-26 -24,-24 -14,-14 "
    "L-10,-26 C-8,-20 -4,-16 0,-6 Z"
)


def bat(x, y, s=1.0, rot=0, color=NIGHT):
    eyes = '<circle cx="-4" cy="-6" r="2" fill="#FFB347"/><circle cx="4" cy="-6" r="2" fill="#FFB347"/>'
    return g(f'<path d="{BAT_PATH}" fill="{color}"/>{eyes}', x, y, s, rot)


def pumpkin(x, y, s=1.0, face=True):
    body = "".join(
        f'<ellipse cx="{cx}" cy="0" rx="{rx}" ry="{ry}" fill="url(#pumpkinGrad)" stroke="#A63C06" stroke-width="5"/>'
        for cx, rx, ry in ((-62, 62, 78), (62, 62, 78), (-30, 58, 84), (30, 58, 84), (0, 50, 87))
    )
    stem = (
        '<path d="M-10,-80 C-12,-100 -6,-118 8,-124 L18,-114 C6,-108 6,-94 10,-80 Z" '
        'fill="#5C7A2E" stroke="#34481A" stroke-width="4"/>'
        '<path d="M12,-98 C30,-122 58,-114 66,-96 C42,-102 30,-92 12,-98 Z" fill="#7FB241"/>'
    )
    out = body + stem
    if face:
        out += (
            f'<g fill="{YELLOW}" stroke="#7A2E00" stroke-width="4" stroke-linejoin="round">'
            '<path d="M-60,-20 L-24,-20 L-42,-52 Z"/><path d="M24,-20 L60,-20 L42,-52 Z"/>'
            '<path d="M-9,4 L9,4 L0,-12 Z"/>'
            '<path d="M-66,18 Q0,78 66,18 L50,28 L40,14 L26,32 L12,18 L0,36 L-12,18 '
            'L-26,32 L-40,14 L-50,28 Z"/></g>'
        )
    return g(out, x, y, s)


def ghost(x, y, s=1.0, rot=0):
    body = (
        '<path d="M-80,70 L-80,-20 C-80,-112 80,-112 80,-20 L80,70 Q66,52 53,70 '
        'Q40,88 27,70 Q13,52 0,70 Q-13,88 -27,70 Q-40,52 -53,70 Q-66,88 -80,70 Z" '
        f'fill="{GHOST}" stroke="{PURPLE}" stroke-width="6" stroke-linejoin="round"/>'
        f'<path d="M-80,4 C-104,0 -112,22 -92,30" fill="none" stroke="{PURPLE}" stroke-width="6" stroke-linecap="round"/>'
        f'<path d="M80,4 C104,0 112,22 92,30" fill="none" stroke="{PURPLE}" stroke-width="6" stroke-linecap="round"/>'
    )
    face = (
        f'<ellipse cx="-26" cy="-26" rx="10" ry="14" fill="{PURPLE}"/>'
        f'<ellipse cx="26" cy="-26" rx="10" ry="14" fill="{PURPLE}"/>'
        '<circle cx="-23" cy="-31" r="4" fill="#fff"/><circle cx="29" cy="-31" r="4" fill="#fff"/>'
        '<ellipse cx="-46" cy="-2" rx="12" ry="7" fill="#FF8FB1" opacity="0.75"/>'
        '<ellipse cx="46" cy="-2" rx="12" ry="7" fill="#FF8FB1" opacity="0.75"/>'
        f'<ellipse cx="0" cy="4" rx="9" ry="11" fill="{PURPLE}"/>'
    )
    return g(body + face, x, y, s, rot)


def candy_corn(x, y, s=1.0, rot=0):
    shape = (
        '<path d="M-20,10 L20,10 L30,40 Q0,52 -30,40 Z" fill="#FFC20E"/>'
        f'<path d="M-10,-20 L10,-20 L20,10 L-20,10 Z" fill="{ORANGE}"/>'
        '<path d="M0,-50 L10,-20 L-10,-20 Z" fill="#FFF5E1"/>'
        '<path d="M0,-50 L30,40 Q0,52 -30,40 Z" fill="none" stroke="#7A2E00" stroke-width="4" stroke-linejoin="round"/>'
    )
    return g(shape, x, y, s, rot)


def witch_hat(x, y, s=1.0):
    return g(
        '<ellipse cx="10" cy="46" rx="150" ry="30" fill="#24103A" stroke="#0F0618" stroke-width="5"/>'
        '<path d="M-44,42 C-22,-24 -2,-122 32,-152 C44,-162 66,-152 76,-134 C60,-140 48,-130 44,-110 '
        'C38,-60 48,0 64,42 Z" fill="#3A1760" stroke="#0F0618" stroke-width="5" stroke-linejoin="round"/>'
        f'<path d="M-36,22 C0,34 32,34 58,22 L64,42 C32,54 0,54 -44,42 Z" fill="{ORANGE}"/>'
        f'<rect x="2" y="24" width="28" height="24" rx="3" fill="none" stroke="{YELLOW}" stroke-width="6"/>'
        + star(-4, -40, 1.3, YELLOW) + star(30, -90, 0.9, YELLOW),
        x, y, s,
    )


def black_cat(x, y, s=1.0):
    return g(
        '<path d="M52,112 C116,112 128,36 98,14 C120,50 104,94 46,92 Z" fill="#120818"/>'
        '<path d="M-60,120 C-82,60 -72,0 -42,-30 C-52,-62 -52,-92 -42,-114 L-20,-82 '
        'C-6,-88 6,-88 20,-82 L42,-114 C52,-92 52,-62 42,-30 C72,0 82,60 60,120 Z" fill="#120818"/>'
        f'<ellipse cx="-18" cy="-56" rx="10" ry="12" fill="{YELLOW}"/>'
        f'<ellipse cx="18" cy="-56" rx="10" ry="12" fill="{YELLOW}"/>'
        '<ellipse cx="-18" cy="-56" rx="3" ry="9" fill="#120818"/>'
        '<ellipse cx="18" cy="-56" rx="3" ry="9" fill="#120818"/>'
        '<path d="M-5,-38 L5,-38 L0,-32 Z" fill="#FF8FB1"/>'
        f'<path d="M-50,30 C-20,44 20,44 50,30" fill="none" stroke="{ORANGE}" stroke-width="8"/>',
        x, y, s,
    )


def spider_web(cx, cy, r, spokes=9):
    angles = [2 * math.pi * i / spokes for i in range(spokes)]
    out = [f'<g fill="none" stroke="#E9DDF7" stroke-width="3" opacity="0.75" stroke-linecap="round">']
    for a in angles:
        out.append(f'<line x1="{cx}" y1="{cy}" x2="{_f(cx + r * math.cos(a))}" y2="{_f(cy + r * math.sin(a))}"/>')
    for k in (0.25, 0.45, 0.65, 0.85):
        rr = r * k
        d = ""
        for i, a in enumerate(angles + [angles[0]]):
            px, py = cx + rr * math.cos(a), cy + rr * math.sin(a)
            if i == 0:
                d = f"M{_f(px)},{_f(py)}"
            else:
                mid = (angles[i - 1] + (a if i < len(angles) else a + 2 * math.pi)) / 2
                qx, qy = cx + rr * 0.86 * math.cos(mid), cy + rr * 0.86 * math.sin(mid)
                d += f" Q{_f(qx)},{_f(qy)} {_f(px)},{_f(py)}"
        out.append(f'<path d="{d}"/>')
    out.append("</g>")
    return "".join(out)


def spider(x, y, s=1.0, thread_from=0):
    legs = "".join(
        f'<path d="M0,0 Q{sx * 40},{dy - 30} {sx * 62},{dy + 10}" fill="none" stroke="#120818" stroke-width="7" stroke-linecap="round"/>'
        for sx in (-1, 1) for dy in (-24, -6, 12, 30)
    )
    body = (
        '<ellipse cx="0" cy="12" rx="30" ry="36" fill="#120818"/><circle cx="0" cy="-26" r="20" fill="#120818"/>'
        '<circle cx="-8" cy="-30" r="6" fill="#fff"/><circle cx="8" cy="-30" r="6" fill="#fff"/>'
        '<circle cx="-7" cy="-29" r="3" fill="#120818"/><circle cx="9" cy="-29" r="3" fill="#120818"/>'
        f'<path d="M-14,10 L14,10 L0,34 Z" fill="{ORANGE}"/>'
    )
    thread = f'<line x1="{x}" y1="{thread_from}" x2="{x}" y2="{_f(y - 40 * s)}" stroke="#E9DDF7" stroke-width="3"/>'
    return thread + g(legs + body, x, y, s)


def haunted_house(x, y, s=1.0):
    return g(
        '<path d="M-110,0 L-110,-90 L-130,-90 L-60,-160 L-20,-120 L-20,-200 L-40,-200 L0,-260 L40,-200 '
        'L20,-200 L20,-120 L60,-160 L130,-90 L110,-90 L110,0 Z" fill="#120818"/>'
        f'<g fill="{YELLOW}"><rect x="-80" y="-80" width="26" height="30"/><rect x="54" y="-80" width="26" height="30"/>'
        '<rect x="-8" y="-180" width="16" height="22"/><path d="M-16,0 L-16,-40 Q0,-56 16,-40 L16,0 Z"/></g>',
        x, y, s,
    )


def hill(d, color="#140821"):
    return f'<path d="{d}" fill="{color}"/>'


# --- Templates ---------------------------------------------------------------------
STAR_FIELD = [(180, 330, 1.4), (300, 200, 1.0), (420, 160, 1.6), (820, 330, 1.2), (590, 150, 0.9),
              (860, 480, 1.0), (140, 470, 0.9), (640, 260, 1.1), (360, 300, 0.8)]


def _art(template_id: str) -> tuple[tuple[str, str], str, str]:
    """Return (background gradient stops, scenery, hero) for a template.

    The hero is the central figure; a quiz character replaces it on character stickers.
    """
    if template_id == "pumpkin-king":
        bg = (VIOLET, PURPLE)
        scenery = (stars(STAR_FIELD) + moon(700, 300, 85)
                   + bat(260, 240, 1.1, -12) + bat(370, 190, 0.7, 8) + bat(800, 430, 0.6, 15)
                   + hill("M0,640 Q250,560 500,620 T1000,600 L1000,1000 L0,1000 Z")
                   + pumpkin(250, 610, 0.55, face=False) + pumpkin(760, 615, 0.5))
        hero = pumpkin(500, 470, 1.3)
    elif template_id == "friendly-ghost":
        bg = ("#4A1F7A", "#1E0B33")
        scenery = (stars(STAR_FIELD) + moon(300, 300, 70)
                   + hill("M0,620 Q300,580 520,630 T1000,610 L1000,1000 L0,1000 Z")
                   + candy_corn(220, 560, 1.1, -18) + candy_corn(800, 570, 1.0, 20)
                   + pumpkin(330, 640, 0.45) + ghost(760, 340, 0.6, 12))
        hero = ghost(510, 430, 1.5)
    elif template_id == "bat-moon":
        bg = ("#C2501A", "#2B1240")
        scenery = (stars(STAR_FIELD[:5]) + moon(500, 420, 220, "url(#harvestGrad)")
                   + bat(330, 300, 1.1, -15) + bat(680, 290, 1.2, 14)
                   + bat(240, 450, 0.6, -20) + bat(770, 440, 0.65, 18)
                   + hill("M0,650 Q200,590 420,640 T1000,620 L1000,1000 L0,1000 Z", "#120818")
                   + haunted_house(760, 650, 0.6) + pumpkin(240, 650, 0.45))
        hero = bat(500, 380, 2.4) + bat(410, 520, 0.8, -8) + bat(620, 520, 0.7, 10)
    elif template_id == "witch-hat":
        bg = ("#5B2A86", "#23103A")
        scenery = (stars(STAR_FIELD + [(250, 560, 1.0), (750, 560, 1.2)]) + moon(740, 270, 60)
                   + bat(270, 260, 0.8, -10) + bat(760, 420, 0.6, 12)
                   + candy_corn(250, 600, 0.9, -24) + candy_corn(760, 610, 0.9, 24))
        hero = witch_hat(490, 500, 1.6)
    elif template_id == "spider-web":
        bg = ("#3D1C63", "#160A26")
        scenery = (stars(STAR_FIELD[3:]) + spider_web(170, 200, 360) + moon(760, 300, 70)
                   + hill("M0,650 Q260,600 500,640 T1000,620 L1000,1000 L0,1000 Z")
                   + ghost(760, 560, 0.55, -10))
        hero = pumpkin(420, 560, 0.85) + spider(640, 360, 1.15, thread_from=0)
    elif template_id == "black-cat":
        bg = ("#6B2FA0", "#1E0B33")
        scenery = (stars(STAR_FIELD) + moon(500, 400, 230)
                   + bat(290, 230, 0.9, -12) + bat(720, 220, 0.8, 14)
                   + hill("M0,640 Q260,600 500,630 T1000,610 L1000,1000 L0,1000 Z")
                   + pumpkin(780, 620, 0.5) + pumpkin(220, 630, 0.42, face=False))
        hero = black_cat(500, 500, 1.35)
    else:
        raise KeyError(template_id)
    return bg, scenery, hero


# --- Quiz characters ------------------------------------------------------------------
SKIN = "#F6D2B5"


def wizard(x, y, s=1.0):
    return g(
        f'<path d="M-95,130 L-55,-10 L55,-10 L95,130 Z" fill="{VIOLET}" stroke="{NIGHT}" stroke-width="6" stroke-linejoin="round"/>'
        + star(-40, 70, 1.2, YELLOW) + star(35, 100, 0.9, YELLOW) + star(10, 40, 0.7, YELLOW)
        + '<line x1="70" y1="40" x2="128" y2="-58" stroke="#8B5A2B" stroke-width="9" stroke-linecap="round"/>'
        + star(130, -66, 2.2, YELLOW)
        + f'<circle cx="70" cy="40" r="14" fill="{SKIN}" stroke="{NIGHT}" stroke-width="4"/>'
        + f'<circle cx="0" cy="-40" r="42" fill="{SKIN}" stroke="{NIGHT}" stroke-width="5"/>'
        '<path d="M-40,-32 Q-44,42 0,76 Q44,42 40,-32 Q22,-12 0,-14 Q-22,-12 -40,-32 Z" fill="#F4F1FF" stroke="#BDB0D8" stroke-width="4"/>'
        f'<circle cx="-14" cy="-48" r="5" fill="{NIGHT}"/><circle cx="14" cy="-48" r="5" fill="{NIGHT}"/>'
        '<ellipse cx="-25" cy="-34" rx="7" ry="4" fill="#FF8FB1" opacity="0.7"/>'
        '<ellipse cx="25" cy="-34" rx="7" ry="4" fill="#FF8FB1" opacity="0.7"/>'
        f'<path d="M-8,-14 Q0,-8 8,-14" fill="none" stroke="{NIGHT}" stroke-width="3" stroke-linecap="round"/>'
        '<path d="M-20,-20 Q-10,-28 0,-22 Q10,-28 20,-20 Q10,-16 0,-19 Q-10,-16 -20,-20 Z" fill="#F4F1FF" stroke="#BDB0D8" stroke-width="2"/>'
        f'<ellipse cx="0" cy="-80" rx="78" ry="15" fill="#3A1760" stroke="{NIGHT}" stroke-width="5"/>'
        '<path d="M-48,-84 C-30,-130 -6,-190 18,-212 C30,-222 48,-212 54,-198 C40,-202 32,-192 30,-176 '
        f'C28,-140 38,-108 48,-84 Z" fill="#3A1760" stroke="{NIGHT}" stroke-width="5" stroke-linejoin="round"/>'
        f'<path d="M-44,-96 C-10,-88 20,-88 46,-96 L48,-84 C20,-76 -10,-76 -48,-84 Z" fill="{ORANGE}"/>'
        + star(4, -140, 1.4, YELLOW),
        x, y, s,
    )


def vampire(x, y, s=1.0):
    return g(
        '<path d="M-125,130 L-80,-24 Q0,8 80,-24 L125,130 Z" fill="#120818" stroke="#000" stroke-width="4"/>'
        '<path d="M-84,130 L-52,-2 Q0,20 52,-2 L84,130 Z" fill="#B3122E"/>'
        f'<path d="M-42,-4 L42,-4 L52,130 L-52,130 Z" fill="{GHOST}" stroke="{NIGHT}" stroke-width="4"/>'
        '<path d="M-30,-4 L0,60 L30,-4 L52,130 L-52,130 Z" fill="#24103A"/>'
        '<path d="M-18,4 L0,14 L18,4 L18,22 L0,14 L-18,22 Z" fill="#B3122E"/>'
        '<path d="M-72,-26 L-104,-118 L-32,-66 Z" fill="#B3122E" stroke="#120818" stroke-width="5" stroke-linejoin="round"/>'
        '<path d="M72,-26 L104,-118 L32,-66 Z" fill="#B3122E" stroke="#120818" stroke-width="5" stroke-linejoin="round"/>'
        f'<ellipse cx="0" cy="-60" rx="42" ry="50" fill="#EDE6F5" stroke="{NIGHT}" stroke-width="5"/>'
        '<path d="M-44,-66 Q-44,-118 0,-116 Q44,-118 44,-66 Q34,-94 0,-80 Q-34,-94 -44,-66 Z" fill="#120818"/>'
        f'<ellipse cx="-15" cy="-62" rx="6" ry="8" fill="{NIGHT}"/><ellipse cx="15" cy="-62" rx="6" ry="8" fill="{NIGHT}"/>'
        '<circle cx="-13" cy="-65" r="2.5" fill="#FF4D6D"/><circle cx="17" cy="-65" r="2.5" fill="#FF4D6D"/>'
        f'<path d="M-18,-36 Q0,-24 18,-36" fill="none" stroke="{NIGHT}" stroke-width="4" stroke-linecap="round"/>'
        '<path d="M-11,-33 L-8,-23 L-4,-31 Z" fill="#fff"/><path d="M11,-33 L8,-23 L4,-31 Z" fill="#fff"/>',
        x, y, s,
    )


def character_figure(character: str, x: float = 0, y: float = 0, s: float = 1.0) -> str:
    """Quiz character illustration centred on (x, y), roughly 300 units tall at s=1."""
    if character == "WIZARD":
        return wizard(x, y, s)
    if character == "VAMPIRE":
        return vampire(x, y, s)
    if character == "FRIENDLY_GHOST":
        return ghost(x, y - 10, 1.55 * s)
    if character == "BLACK_CAT":
        return black_cat(x, y - 5, 1.2 * s)
    raise KeyError(character)


def character_svg(character: str, size_px: int = 400) -> str:
    """Standalone character portrait (used on the quiz result page)."""
    figure = character_figure(character, 200, 215, 0.95)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size_px}" height="{size_px}" viewBox="0 0 400 400" '
        f'role="img" aria-label="{escape(character.replace("_", " ").title())}">'
        '<defs><radialGradient id="cbg" cx="50%" cy="40%" r="60%"><stop offset="0" stop-color="#6B2FA0"/>'
        '<stop offset="1" stop-color="#24103A"/></radialGradient></defs>'
        '<circle cx="200" cy="200" r="196" fill="url(#cbg)" stroke="#FF7A1A" stroke-width="6"/>'
        + stars([(70, 110, 1.3), (330, 90, 1.0), (320, 250, 1.2), (80, 280, 0.9), (200, 40, 0.8)])
        + figure + "</svg>"
    )


def render_sticker(template_id: str, name: str, *, transparent: bool = True,
                   watermark: bool | str = False, size_px: int = OUTPUT_PX,
                   character: str | None = None, character_label: str | None = None,
                   traits: list[str] | None = None) -> str:
    """Render the sticker as a standalone SVG document string.

    With ``character`` the template's central figure is replaced by the quiz
    character, and ``character_label`` / ``traits`` are printed on the sticker.
    """
    if template_id not in TEMPLATES:
        raise KeyError(template_id)
    (bg_inner, bg_outer), scenery, hero = _art(template_id)
    if character:
        hero = (f'<g class="character" data-character="{escape(character)}">'
                + character_figure(character, 500, 440, 1.15) + "</g>")
    art = scenery + hero
    name = clean_text(name)
    lay = layout_name(name)

    defs = (
        "<defs>"
        f'<radialGradient id="bgGrad" cx="50%" cy="40%" r="65%"><stop offset="0" stop-color="{bg_inner}"/>'
        f'<stop offset="1" stop-color="{bg_outer}"/></radialGradient>'
        '<radialGradient id="pumpkinGrad" cx="40%" cy="35%" r="75%"><stop offset="0" stop-color="#FFA24C"/>'
        f'<stop offset="0.6" stop-color="{ORANGE}"/><stop offset="1" stop-color="{DEEP_ORANGE}"/></radialGradient>'
        f'<radialGradient id="moonGrad" cx="40%" cy="40%" r="70%"><stop offset="0" stop-color="#FFFBEA"/>'
        f'<stop offset="1" stop-color="#FFE08A"/></radialGradient>'
        '<radialGradient id="harvestGrad" cx="45%" cy="40%" r="70%"><stop offset="0" stop-color="#FFE5A0"/>'
        f'<stop offset="1" stop-color="#FF9F45"/></radialGradient>'
        f'<linearGradient id="bannerGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{VIOLET}"/>'
        f'<stop offset="1" stop-color="{PURPLE}"/></linearGradient>'
        f'<linearGradient id="nameGrad" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{YELLOW}"/>'
        f'<stop offset="1" stop-color="{ORANGE}"/></linearGradient>'
        '<clipPath id="disc"><circle cx="500" cy="500" r="466"/></clipPath>'
        '<path id="arcTop" d="M 118,500 A 382,382 0 0 1 882,500"/>'
        "</defs>"
    )

    b = BANNER
    parts = [defs]
    if not transparent:
        parts.append(f'<rect width="{VIEW}" height="{VIEW}" fill="{NIGHT}"/>')
    # Die-cut sticker outline: dark keyline, then white border, around disc + banner.
    parts.append(
        f'<g fill="{PURPLE}"><circle cx="500" cy="500" r="494"/>'
        f'<rect x="{b["x"] - 26}" y="{b["y"] - 26}" width="{b["w"] + 52}" height="{b["h"] + 52}" rx="52"/></g>'
        '<g fill="#FFFFFF"><circle cx="500" cy="500" r="486"/>'
        f'<rect x="{b["x"] - 18}" y="{b["y"] - 18}" width="{b["w"] + 36}" height="{b["h"] + 36}" rx="44"/></g>'
    )
    parts.append(f'<g clip-path="url(#disc)"><rect width="{VIEW}" height="{VIEW}" fill="url(#bgGrad)"/>{art}</g>')
    parts.append(
        f'<text font-family="{FONT_STACK}" font-weight="900" font-size="74" letter-spacing="6" '
        f'fill="{ORANGE}" stroke="{NIGHT}" stroke-width="12" stroke-linejoin="round" paint-order="stroke">'
        '<textPath href="#arcTop" startOffset="50%" text-anchor="middle">HALLOWEEN 2026</textPath></text>'
    )
    parts.append(
        f'<rect x="{b["x"]}" y="{b["y"]}" width="{b["w"]}" height="{b["h"]}" rx="30" '
        f'fill="url(#bannerGrad)" stroke="{ORANGE}" stroke-width="8"/>'
        + bat(b["x"] + 2, b["y"] + 4, 0.55, -20, ORANGE) + bat(b["x"] + b["w"] - 2, b["y"] + 4, 0.55, 20, ORANGE)
    )

    fs = lay.font_size
    n = len(lay.lines)
    line_gap = fs * 1.08
    first_y = NAME_CENTER_Y - line_gap * (n - 1) / 2
    for i, line in enumerate(lay.lines):
        y = first_y + i * line_gap
        fit = (f' textLength="{NAME_MAX_WIDTH}" lengthAdjust="spacingAndGlyphs"'
               if lay.compress else "")
        parts.append(
            f'<text class="sticker-name" data-fit-max="{NAME_MAX_WIDTH}" x="500" y="{_f(y)}" '
            f'text-anchor="middle" dominant-baseline="central" font-family="{FONT_STACK}" '
            f'font-weight="900" font-size="{_f(fs)}" fill="url(#nameGrad)" stroke="{NIGHT}" '
            f'stroke-width="{_f(max(4.0, fs * 0.12))}" stroke-linejoin="round" paint-order="stroke"{fit}>'
            f"{escape(line)}</text>"
        )

    if character and character_label:
        label = clean_text(character_label)
        fs_label = 36
        width = min(LABEL_MAX_WIDTH, text_em(label) * fs_label)
        fit = (f' textLength="{LABEL_MAX_WIDTH}" lengthAdjust="spacingAndGlyphs"'
               if text_em(label) * fs_label > LABEL_MAX_WIDTH else "")
        parts.append(
            f'<rect x="{_f(500 - width / 2 - 34)}" y="610" width="{_f(width + 68)}" height="60" rx="30" '
            f'fill="{NIGHT}" stroke="{YELLOW}" stroke-width="5"/>'
            f'<text class="sticker-character" data-fit-max="{LABEL_MAX_WIDTH}" x="500" y="641" '
            f'text-anchor="middle" dominant-baseline="central" font-family="{FONT_STACK}" font-weight="900" '
            f'font-size="{fs_label}" letter-spacing="1" fill="{YELLOW}"{fit}>{escape(label)}</text>'
        )
    if character and traits:
        line = clean_text(" · ".join(traits[:3]))
        fs_traits = 28
        fit = (f' textLength="{TRAITS_MAX_WIDTH}" lengthAdjust="spacingAndGlyphs"'
               if text_em(line) * fs_traits > TRAITS_MAX_WIDTH else "")
        parts.append(
            f'<text class="sticker-traits" data-fit-max="{TRAITS_MAX_WIDTH}" x="500" y="912" '
            f'text-anchor="middle" dominant-baseline="central" font-family="{FONT_STACK}" font-weight="800" '
            f'font-size="{fs_traits}" fill="#FBF6FF"{fit}>{escape(line)}</text>'
        )

    if watermark:
        mark = watermark if isinstance(watermark, str) else "SAMPLE"
        parts.append(
            '<text x="500" y="470" text-anchor="middle" dominant-baseline="central" '
            f'transform="rotate(-24 500 470)" font-family="{FONT_STACK}" font-weight="900" font-size="170" '
            'fill="#FFFFFF" fill-opacity="0.38" stroke="#1A0B2E" stroke-opacity="0.35" stroke-width="6" '
            f'letter-spacing="10">{escape(mark)}</text>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size_px}" height="{size_px}" '
        f'viewBox="0 0 {VIEW} {VIEW}" role="img" aria-label="Halloween 2026 sticker">'
        f'<title>Halloween 2026 — {escape(" ".join(lay.lines))}</title>'
        + "".join(parts) + "</svg>"
    )
