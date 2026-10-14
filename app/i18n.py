"""Server-side translation of user-facing messages (English source -> Mongolian).

Messages are written in English throughout the code; ``tr`` maps them to the
requested language at the API boundary. Unknown messages fall back to English.
"""
from __future__ import annotations

import re

LANGS = ("en", "mn")

MN: dict[str, str] = {
    # Status messages
    "Please complete your bank transfer.": "Банкны шилжүүлгээ хийнэ үү.",
    "Your payment is awaiting verification.": "Таны төлбөр баталгаажуулалт хүлээж байна.",
    "Your sticker generator is now available.": "Таны стикер үүсгэгч одоо бэлэн боллоо.",
    "Your payment could not be verified. Please contact the administrator.":
        "Таны төлбөрийг баталгаажуулж чадсангүй. Зохион байгуулагчтай холбогдоно уу.",
    "This request has expired.": "Энэ хүсэлтийн хугацаа дууссан.",
    "Your payment report has been received. Your sticker will become available after administrator verification.":
        "Таны төлбөрийн мэдэгдлийг хүлээн авлаа. Зохион байгуулагч баталгаажуулсны дараа таны стикер бэлэн болно.",
    # Public errors
    "Please enter your name.": "Нэрээ оруулна уу.",
    "Name contains unsupported characters.": "Нэрэнд дэмжигдээгүй тэмдэгт байна.",
    "Name must contain at least one letter or number.": "Нэр дор хаяж нэг үсэг эсвэл тоо агуулсан байх ёстой.",
    "Please enter a valid email address or leave it empty.": "Зөв имэйл хаяг оруулах эсвэл хоосон орхино уу.",
    "Unknown sticker design.": "Ийм загвар байхгүй.",
    "Unknown design.": "Ийм загвар байхгүй.",
    "Too many unpaid requests from your network. Please complete or wait for existing ones to expire.":
        "Таны сүлжээнээс төлөгдөөгүй хүсэлт хэт олон байна. Өмнөх хүсэлтүүдээ төлөх эсвэл хугацаа нь дуусахыг хүлээнэ үү.",
    "Request not found.": "Хүсэлт олдсонгүй.",
    "This request is already approved.": "Энэ хүсэлт аль хэдийн баталгаажсан.",
    "This request was rejected. Please contact the administrator.":
        "Энэ хүсэлтээс татгалзсан. Зохион байгуулагчтай холбогдоно уу.",
    "This request has expired. Please create a new request.":
        "Энэ хүсэлтийн хугацаа дууссан. Шинэ хүсэлт үүсгэнэ үү.",
    "This action is not allowed in the current state.": "Одоогийн төлөвт энэ үйлдлийг хийх боломжгүй.",
    "Your sticker is not available until the payment is approved.":
        "Төлбөр баталгаажих хүртэл таны стикер нээгдэхгүй.",
    "Too many requests. Please slow down and try again shortly.":
        "Хэт олон хүсэлт ирлээ. Түр хүлээгээд дахин оролдоно уу.",
    "Invalid submission.": "Буруу илгээлт.",
    "Invalid input.": "Оруулсан мэдээлэл буруу байна.",
    "Could not allocate a request ID, please retry.": "Хүсэлтийн дугаар олгож чадсангүй, дахин оролдоно уу.",
    "Request status changed, please refresh.": "Хүсэлтийн төлөв өөрчлөгдсөн тул хуудсаа шинэчилнэ үү.",
    # Quiz
    "Please answer all 6 questions.": "6 асуултад бүгдэд нь хариулна уу.",
    "Invalid quiz answer.": "Тестийн хариулт буруу байна.",
    "Unknown character.": "Ийм дүр байхгүй.",
    # Admin errors
    "Authentication required.": "Нэвтрэх шаардлагатай.",
    "Invalid or missing CSRF token.": "CSRF токен буруу эсвэл байхгүй байна.",
    "Too many login attempts. Try again in 15 minutes.":
        "Нэвтрэх оролдлого хэт олон боллоо. 15 минутын дараа дахин оролдоно уу.",
    "Invalid username or password.": "Нэвтрэх нэр эсвэл нууц үг буруу байна.",
    "Request was modified concurrently; refresh and retry.":
        "Хүсэлтийг өөр хэн нэгэн зэрэг өөрчилсөн байна. Шинэчлээд дахин оролдоно уу.",
    "A rejection reason is required.": "Татгалзсан шалтгаанаа бичнэ үү.",
    "Rejection reason must be at most 500 characters.": "Татгалзсан шалтгаан хамгийн ихдээ 500 тэмдэгт байна.",
    "Note must be 1–1000 characters.": "Тэмдэглэл 1–1000 тэмдэгт байна.",
    "Currency must be a 3-letter ISO code (e.g. JPY, USD, MNT).":
        "Валют нь 3 үсэгтэй ISO код байна (ж.нь JPY, USD, MNT).",
    "When changing currency, also provide the amount.": "Валют өөрчлөхдөө дүнг мөн оруулна уу.",
    "Expiration must be between 1 and 1440 hours.": "Хүчинтэй хугацаа 1–1440 цагийн хооронд байна.",
    "Amount must be a number.": "Дүн тоо байх ёстой.",
    "Amount must be positive and reasonable.": "Дүн эерэг бөгөөд бодитой байх ёстой.",
}

_FIELDS_MN = {
    "Bank name": "Банкны нэр",
    "Account holder": "Данс эзэмшигч",
    "Account number": "Дансны дугаар",
    "Payment instructions": "Төлбөрийн заавар (англи)",
    "Payment instructions mn": "Төлбөрийн заавар (монгол)",
}

MN_PATTERNS: list[tuple[re.Pattern, callable]] = [
    (re.compile(r"^Name must be at most (\d+) characters\.$"),
     lambda m: f"Нэр хамгийн ихдээ {m[1]} тэмдэгт байх ёстой."),
    (re.compile(r"^If you believe this is a mistake, contact the administrator and quote your request ID (\S+)\.$"),
     lambda m: f"Хэрэв алдаа гарсан гэж үзвэл зохион байгуулагчтай холбогдож, хүсэлтийн дугаараа ({m[1]}) хэлнэ үү."),
    (re.compile(r"^Cannot change a request from (\w+) to (\w+)\.$"),
     lambda m: f"Хүсэлтийг {m[1]} төлвөөс {m[2]} төлөв рүү өөрчлөх боломжгүй."),
    (re.compile(r"^(\w{3}) amounts allow at most (\d+) decimal places\.$"),
     lambda m: f"{m[1]} дүнд хамгийн ихдээ {m[2]} аравтын орон зөвшөөрнө."),
    (re.compile(r"^(.+) must be 1–(\d+) characters\.$"),
     lambda m: f"{_FIELDS_MN.get(m[1], m[1])} 1–{m[2]} тэмдэгт байх ёстой."),
]


def tr(message: str | None, lang: str) -> str | None:
    if message is None or lang != "mn":
        return message
    if message in MN:
        return MN[message]
    for pattern, fmt in MN_PATTERNS:
        m = pattern.match(message)
        if m:
            return fmt(m)
    return message


def parse_lang(header: str | None) -> str:
    """Pick 'mn' if it is the first preferred language, else 'en'."""
    if not header:
        return "en"
    first = header.split(",")[0].split(";")[0].strip().lower()
    return "mn" if first.startswith("mn") else "en"
