""""Which Halloween Character Matches You in 2026?" — quiz content and scoring.

This module is the single source of truth for the quiz: questions, the
answer -> character mapping, scoring, tie-breaking and character texts (EN/MN).
The browser receives the content from ``GET /api/quiz`` and the result from
``POST /api/quiz/result``; it never decides the character itself.

Scoring rules
-------------
* Six questions, answers ``A``-``D``. Each answer gives exactly one point to
  the character in ``ANSWER_MAP[question][answer]``.
* The character with the most points wins.
* **Tie-break:** among the tied characters, the one chosen in the *latest*
  question wins (scan from question 6 back to question 1). A tied character
  always has >= 1 point, so this always resolves. ``CHARACTER_ORDER`` is a
  final fallback that is never needed for valid input.

It is an entertainment feature, not a psychological assessment.
"""
from __future__ import annotations

from dataclasses import dataclass

WIZARD, VAMPIRE, GHOST, CAT = "WIZARD", "VAMPIRE", "FRIENDLY_GHOST", "BLACK_CAT"
CHARACTER_ORDER = (WIZARD, VAMPIRE, GHOST, CAT)
LETTERS = ("A", "B", "C", "D")

# question index (0-based) -> answer letter -> character
ANSWER_MAP: tuple[dict[str, str], ...] = (
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},   # Q1 Halloween night
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},   # Q2 greatest strength
    {"A": VAMPIRE, "B": GHOST, "C": WIZARD, "D": CAT},   # Q3 colour: purple, orange, green, black
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},   # Q4 meeting a ghost
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},   # Q5 magical power
    {"A": WIZARD, "B": VAMPIRE, "C": GHOST, "D": CAT},   # Q6 phrase
)
NUM_QUESTIONS = len(ANSWER_MAP)


class QuizError(ValueError):
    pass


def validate_answers(answers) -> list[str]:
    if not isinstance(answers, (list, tuple)) or len(answers) != NUM_QUESTIONS:
        raise QuizError(f"Please answer all {NUM_QUESTIONS} questions.")
    clean = []
    for a in answers:
        if not isinstance(a, str) or a.upper() not in LETTERS:
            raise QuizError("Invalid quiz answer.")
        clean.append(a.upper())
    return clean


def score(answers) -> tuple[str, dict[str, int]]:
    """Return (character, points per character). Deterministic for given answers."""
    answers = validate_answers(answers)
    picks = [ANSWER_MAP[i][a] for i, a in enumerate(answers)]
    points = {c: picks.count(c) for c in CHARACTER_ORDER}
    best = max(points.values())
    tied = [c for c in CHARACTER_ORDER if points[c] == best]
    if len(tied) == 1:
        return tied[0], points
    for pick in reversed(picks):  # latest answer among the tied characters wins
        if pick in tied:
            return pick, points
    return tied[0], points  # pragma: no cover - unreachable for valid input


# --- Content -------------------------------------------------------------------------
QUESTIONS = {
    "en": [
        ("How would you spend Halloween night?", [
            "Exploring a mysterious haunted house.",
            "Hosting a fun party with friends.",
            "Staying home with snacks and scary movies.",
            "Exploring the night and discovering hidden secrets."]),
        ("What is your greatest strength?", [
            "Intelligence and strategy.", "Courage and leadership.",
            "Kindness and creativity.", "Mystery and intuition."]),
        ("Choose your favorite Halloween color.", ["Purple.", "Orange.", "Green.", "Black."]),
        ("What would you do if you encountered a ghost?", [
            "Investigate how ghosts work.", "Challenge it without fear.",
            "Offer it a friendly conversation.", "Disappear into the shadows."]),
        ("Choose your ideal magical power.", [
            "Read ancient secrets and cast powerful spells.",
            "Control fire and protect your friends.",
            "Become invisible and play harmless tricks.",
            "Travel through shadows and see the future."]),
        ("Which phrase describes you best?", [
            "“Knowledge is my superpower.”",
            "“Fearless, energetic, and unstoppable.”",
            "“Kind-hearted, playful, and imaginative.”",
            "“Quiet, mysterious, and independent.”"]),
    ],
    "mn": [
        ("Хэллоуины шөнийг та хэрхэн өнгөрөөх вэ?", [
            "Нууцлаг сүнстэй байшинг судлах.",
            "Найзуудтайгаа хөгжилтэй үдэшлэг зохион байгуулах.",
            "Гэртээ зууш идэж, аймшгийн кино үзэх.",
            "Шөнийг тэнүүчилж, нуугдмал нууцуудыг нээх."]),
        ("Таны хамгийн том давуу тал юу вэ?", [
            "Ухаан ба стратеги.", "Зориг ба манлайлал.",
            "Сайхан сэтгэл ба бүтээлч байдал.", "Нууцлаг байдал ба зөн совин."]),
        ("Хэллоуины дуртай өнгөө сонгоно уу.", ["Нил ягаан.", "Улбар шар.", "Ногоон.", "Хар."]),
        ("Сүнстэй тааралдвал та юу хийх вэ?", [
            "Сүнс хэрхэн ажилладгийг судлах.", "Айдасгүйгээр түүнтэй тулалдах.",
            "Түүнтэй найрсгаар ярилцах.", "Сүүдэрт уусан алга болох."]),
        ("Хүсэж буй ид шидийн чадвараа сонгоно уу.", [
            "Эртний нууцыг уншиж, хүчтэй шившлэг хийх.",
            "Галыг удирдаж, найзуудаа хамгаалах.",
            "Үл үзэгдэх болж, хор хөнөөлгүй тоглоом тоглох.",
            "Сүүдрээр аялж, ирээдүйг харах."]),
        ("Аль хэллэг таныг хамгийн сайн илэрхийлэх вэ?", [
            "“Мэдлэг бол миний супер хүч.”",
            "“Айдасгүй, эрч хүчтэй, зогсошгүй.”",
            "“Сайхан сэтгэлтэй, хөгжилтэй, төсөөлөл баян.”",
            "“Нам гүм, нууцлаг, бие даасан.”"]),
    ],
}


@dataclass(frozen=True)
class Character:
    name: str
    description: str
    traits: tuple[str, str, str]
    tagline: str


CHARACTERS: dict[str, dict[str, Character]] = {
    "en": {
        WIZARD: Character(
            "Wizard",
            "You see magic where others only see mystery. Curious and clever, you would rather read the "
            "ancient spellbook than run from the haunted house — and you always have a plan.",
            ("Clever", "Curious", "Magical"),
            "Spells, smarts, and a pointy hat — what more do you need?"),
        VAMPIRE: Character(
            "Vampire",
            "You walk into every room like it is your castle. Bold, stylish and a natural leader, you turn "
            "any Halloween night into a legendary event — fangs optional.",
            ("Confident", "Elegant", "Ambitious"),
            "Born to rule the night!"),
        GHOST: Character(
            "Friendly Ghost",
            "You bring light and laughter wherever you go. Even in the spookiest places, your imagination "
            "and kindness make every adventure more fun.",
            ("Friendly", "Creative", "Playful"),
            "Too cute to haunt, too fun to forget!"),
        CAT: Character(
            "Black Cat",
            "You notice everything and reveal only what you choose. Independent and quick-witted, you glide "
            "through the night on your own terms — and always land on your feet.",
            ("Independent", "Observant", "Clever"),
            "Nine lives, zero worries."),
    },
    "mn": {
        WIZARD: Character(
            "Шидтэн",
            "Бусад зөвхөн нууцыг харах газар та ид шидийг олж хардаг. Сониуч, ухаалаг та сүнстэй байшингаас "
            "зугтахын оронд эртний шившлэгийн номыг уншихыг илүүд үздэг — бас үргэлж төлөвлөгөөтэй.",
            ("Ухаалаг", "Сониуч", "Ид шидтэй"),
            "Шившлэг, ухаан, шовгор малгай — өөр юу хэрэгтэй юм бэ?"),
        VAMPIRE: Character(
            "Цус сорогч",
            "Та аль ч өрөөнд өөрийн шилтгээнд орж буй мэт ордог. Зоригтой, ганган, төрөлхийн удирдагч та "
            "Хэллоуины шөнө бүрийг домогт үйл явдал болгодог — соёо заавал биш.",
            ("Өөртөө итгэлтэй", "Ганган", "Тэмүүлэлтэй"),
            "Шөнийг захирахаар төрсөн!"),
        GHOST: Character(
            "Найрсаг сүнс",
            "Та хаана ч очсон гэрэл гэгээ, инээд хөөрийг авчирдаг. Хамгийн аймшигтай газар ч таны төсөөлөл, "
            "сайхан сэтгэл адал явдал бүрийг илүү хөгжилтэй болгодог.",
            ("Найрсаг", "Бүтээлч", "Хөгжилтэй"),
            "Айлгахад хэтэрхий хөөрхөн, мартахад хэтэрхий хөгжилтэй!"),
        CAT: Character(
            "Хар муур",
            "Та бүхнийг анзаардаг ч зөвхөн хүссэнээ л илчилдэг. Бие даасан, сэргэлэн та шөнийг өөрийнхөөрөө "
            "гулсан өнгөрдөг — бас үргэлж хөл дээрээ буудаг.",
            ("Бие даасан", "Ажигч", "Сэргэлэн"),
            "Есөн амь, тэг санаа зоволт."),
    },
}

EMOJI = {WIZARD: "🧙", VAMPIRE: "🧛", GHOST: "👻", CAT: "🐈‍⬛"}
STICKER_LABEL = {"en": "YOUR CHARACTER: {name}", "mn": "ТАНЫ ДҮР: {name}"}


def character_info(character: str, lang: str = "en") -> dict:
    c = CHARACTERS.get(lang, CHARACTERS["en"])[character]
    return {"id": character, "name": c.name, "description": c.description,
            "traits": list(c.traits), "tagline": c.tagline, "emoji": EMOJI[character],
            "image": f"/api/characters/{character}.svg"}


def quiz_content(lang: str = "en") -> dict:
    lang = lang if lang in QUESTIONS else "en"
    return {
        "questions": [{"text": q, "options": [{"id": LETTERS[i], "text": t} for i, t in enumerate(opts)]}
                      for q, opts in QUESTIONS[lang]],
        "characters": {c: character_info(c, lang) for c in CHARACTER_ORDER},
    }
