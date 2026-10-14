"""Business logic for sticker requests, payment settings, admins and auditing.

Status transitions are enforced here with conditional UPDATEs inside
``BEGIN IMMEDIATE`` transactions, so concurrent requests can never move a
request through an invalid transition or approve it twice.
"""
from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from . import security
from .config import Settings
from .db import Database, ts, ts_plus, utcnow
from .i18n import tr

PENDING, REPORTED, APPROVED, REJECTED, EXPIRED = (
    "PENDING_PAYMENT", "PAYMENT_REPORTED", "APPROVED", "REJECTED", "EXPIRED")

STATUS_MESSAGES = {
    PENDING: "Please complete your bank transfer.",
    REPORTED: "Your payment is awaiting verification.",
    APPROVED: "Your sticker generator is now available.",
    REJECTED: "Your payment could not be verified. Please contact the administrator.",
    EXPIRED: "This request has expired.",
}

# Allowed transitions: (from, to) -> who may perform it.
TRANSITIONS = {
    (PENDING, REPORTED): "user",
    (PENDING, EXPIRED): "system",
    (REPORTED, APPROVED): "admin",
    (REPORTED, REJECTED): "admin",
}

# MNT officially has 2 minor units, but tugrug amounts are never written with decimals.
CURRENCY_EXPONENTS = {"JPY": 0, "KRW": 0, "VND": 0, "CLP": 0, "ISK": 0, "MNT": 0,
                      "BHD": 3, "KWD": 3, "OMR": 3, "JOD": 3, "TND": 3}

NAME_MAX_LEN = 40
EMAIL_RE = re.compile(r"^[^@\s<>\"']{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}$")


ADMIN_SELECT = ("SELECT r.*, a.username AS approved_by_name, rj.username AS rejected_by_name "
                "FROM sticker_requests r LEFT JOIN admins a ON a.id = r.approved_by "
                "LEFT JOIN admins rj ON rj.id = r.rejected_by")


class ServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# --- Validation --------------------------------------------------------------------
def normalize_name(raw: str) -> str:
    name = unicodedata.normalize("NFC", raw or "")
    name = " ".join(name.split())  # trim + collapse internal whitespace
    if not name:
        raise ServiceError("Please enter your name.", 422)
    if len(name) > NAME_MAX_LEN:
        raise ServiceError(f"Name must be at most {NAME_MAX_LEN} characters.", 422)
    for ch in name:
        cat = unicodedata.category(ch)
        if cat in ("Cc", "Cs", "Co", "Cn") or (cat == "Cf" and ch not in "‌‍᠎ "):
            raise ServiceError("Name contains unsupported characters.", 422)
    if not any(unicodedata.category(c)[0] in "LN" for c in name):
        raise ServiceError("Name must contain at least one letter or number.", 422)
    return name


def normalize_email(raw: str | None) -> str | None:
    if raw is None:
        return None
    email = raw.strip()
    if not email:
        return None
    if len(email) > 254 or not EMAIL_RE.match(email):
        raise ServiceError("Please enter a valid email address or leave it empty.", 422)
    return email


def currency_exponent(currency: str) -> int:
    return CURRENCY_EXPONENTS.get(currency, 2)


def parse_amount(amount: str, currency: str) -> int:
    """Convert a decimal string to integer minor units, exactly."""
    try:
        value = Decimal(str(amount).strip())
    except (InvalidOperation, ValueError):
        raise ServiceError("Amount must be a number.", 422)
    exp = currency_exponent(currency)
    minor = value * (Decimal(10) ** exp)
    if not value.is_finite() or minor != minor.to_integral_value():
        raise ServiceError(f"{currency} amounts allow at most {exp} decimal places.", 422)
    minor = int(minor)
    if minor <= 0 or minor > 10**12:
        raise ServiceError("Amount must be positive and reasonable.", 422)
    return minor


def format_amount(minor: int, currency: str) -> str:
    exp = currency_exponent(currency)
    value = Decimal(minor) / (Decimal(10) ** exp)
    return f"{value:,.{exp}f} {currency}"


def normalize_currency(raw: str) -> str:
    cur = (raw or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", cur):
        raise ServiceError("Currency must be a 3-letter ISO code (e.g. JPY, USD, MNT).", 422)
    return cur


# --- Audit -----------------------------------------------------------------------------
def audit(conn: sqlite3.Connection, action: str, *, actor_type: str, actor_id: int | None = None,
          target: str | None = None, details: dict | None = None, ip_hash: str | None = None) -> None:
    conn.execute(
        "INSERT INTO audit_logs (created_at, actor_type, actor_id, action, target, details, ip_hash) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (ts(), actor_type, actor_id, action, target,
         json.dumps(details, ensure_ascii=False) if details else None, ip_hash),
    )


# --- Payment settings ------------------------------------------------------------
SETTING_KEYS = ("bank_name", "account_holder", "account_number", "amount_minor", "currency",
                "payment_instructions", "payment_instructions_mn", "request_expiration_hours")


@dataclass
class PaymentSettings:
    bank_name: str
    account_holder: str
    account_number: str
    amount_minor: int
    currency: str
    payment_instructions: str
    payment_instructions_mn: str
    request_expiration_hours: int

    @property
    def amount_display(self) -> str:
        return format_amount(self.amount_minor, self.currency)

    def as_dict(self) -> dict:
        exp = currency_exponent(self.currency)
        return {
            "bank_name": self.bank_name,
            "account_holder": self.account_holder,
            "account_number": self.account_number,
            "amount": f"{Decimal(self.amount_minor) / (Decimal(10) ** exp):.{exp}f}",
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "amount_display": self.amount_display,
            "payment_instructions": self.payment_instructions,
            "payment_instructions_mn": self.payment_instructions_mn,
            "request_expiration_hours": self.request_expiration_hours,
        }


class App:
    """Service facade bound to one database and configuration."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database(settings.database_path)
        self.db.init_schema()
        self._seed_settings()

    # -- settings --
    def _seed_settings(self) -> None:
        s = self.settings
        currency = normalize_currency(s.payment_currency)
        defaults = {
            "bank_name": s.bank_name,
            "account_holder": s.account_holder,
            "account_number": s.account_number,
            "amount_minor": str(parse_amount(s.payment_amount, currency)),
            "currency": currency,
            "payment_instructions": s.payment_instructions,
            "payment_instructions_mn": s.payment_instructions_mn,
            "request_expiration_hours": str(s.request_expiration_hours),
        }
        with self.db.transaction() as c:
            for k, v in defaults.items():
                c.execute("INSERT OR IGNORE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                          (k, v, ts()))

    def get_payment_settings(self, conn: sqlite3.Connection | None = None) -> PaymentSettings:
        def load(c):
            rows = dict(c.execute("SELECT key, value FROM app_settings").fetchall())
            return PaymentSettings(
                bank_name=rows["bank_name"], account_holder=rows["account_holder"],
                account_number=rows["account_number"], amount_minor=int(rows["amount_minor"]),
                currency=rows["currency"], payment_instructions=rows["payment_instructions"],
                payment_instructions_mn=rows["payment_instructions_mn"],
                request_expiration_hours=int(rows["request_expiration_hours"]),
            )
        if conn is not None:
            return load(conn)
        with self.db.conn() as c:
            return load(c)

    def update_payment_settings(self, admin_id: int, changes: dict, ip_hash: str | None = None) -> PaymentSettings:
        with self.db.transaction() as c:
            current = self.get_payment_settings(c)
            new = dict(
                bank_name=current.bank_name, account_holder=current.account_holder,
                account_number=current.account_number, currency=current.currency,
                payment_instructions=current.payment_instructions,
                payment_instructions_mn=current.payment_instructions_mn,
                request_expiration_hours=current.request_expiration_hours,
            )
            for key, limit in (("bank_name", 120), ("account_holder", 120), ("account_number", 80),
                               ("payment_instructions", 2000), ("payment_instructions_mn", 2000)):
                if changes.get(key) is not None:
                    value = str(changes[key]).strip()
                    if not value or len(value) > limit:
                        raise ServiceError(f"{key.replace('_', ' ').capitalize()} must be 1–{limit} characters.", 422)
                    new[key] = value
            if changes.get("currency") is not None:
                new["currency"] = normalize_currency(changes["currency"])
            if changes.get("amount") is not None:
                new["amount_minor"] = parse_amount(changes["amount"], new["currency"])
            elif new["currency"] != current.currency:
                raise ServiceError("When changing currency, also provide the amount.", 422)
            else:
                new["amount_minor"] = current.amount_minor
            if changes.get("request_expiration_hours") is not None:
                hours = int(changes["request_expiration_hours"])
                if not 1 <= hours <= 24 * 60:
                    raise ServiceError("Expiration must be between 1 and 1440 hours.", 422)
                new["request_expiration_hours"] = hours

            diff = {}
            before = current.__dict__
            for k in SETTING_KEYS:
                if str(new[k]) != str(before[k]):
                    diff[k] = {"from": _mask(k, before[k]), "to": _mask(k, new[k])}
                    c.execute("UPDATE app_settings SET value = ?, updated_at = ? WHERE key = ?",
                              (str(new[k]), ts(), k))
            if diff:
                audit(c, "settings.update", actor_type="admin", actor_id=admin_id,
                      target="payment_settings", details=diff, ip_hash=ip_hash)
            return self.get_payment_settings(c)

    # -- requests --
    def expire_stale(self) -> int:
        with self.db.transaction() as c:
            rows = c.execute("SELECT request_code FROM sticker_requests WHERE status = ? AND expires_at < ?",
                             (PENDING, ts())).fetchall()
            if not rows:
                return 0
            now = ts()
            cur = c.execute("UPDATE sticker_requests SET status = ?, updated_at = ? "
                            "WHERE status = ? AND expires_at < ?", (EXPIRED, now, PENDING, now))
            audit(c, "request.expire", actor_type="system",
                  details={"codes": [r["request_code"] for r in rows][:100], "count": cur.rowcount})
            return cur.rowcount

    def create_request(self, *, name: str, email: str | None, template_id: str | None,
                       idempotency_key: str | None, ip_hash: str | None,
                       character: str | None = None) -> dict:
        from .stickers import TEMPLATES

        name = normalize_name(name)
        email = normalize_email(email)
        if template_id in ("", None):
            template_id = None
        elif template_id not in TEMPLATES:
            raise ServiceError("Unknown sticker design.", 422)
        idem_hash = security.token_hash("idem:" + idempotency_key) if idempotency_key else None

        token = security.new_token()
        with self.db.transaction() as c:
            if idem_hash:
                existing = c.execute("SELECT request_code, status FROM sticker_requests "
                                     "WHERE idempotency_key_hash = ?", (idem_hash,)).fetchone()
                if existing:
                    return {"duplicate": True, "request_code": existing["request_code"],
                            "status": existing["status"]}
            if ip_hash and self.settings.max_open_requests_per_ip > 0:
                open_count = c.execute(
                    "SELECT COUNT(*) FROM sticker_requests WHERE client_ip_hash = ? AND status = ? "
                    "AND created_at > ?", (ip_hash, PENDING, ts_plus(hours=-24))).fetchone()[0]
                if open_count >= self.settings.max_open_requests_per_ip:
                    raise ServiceError("Too many unpaid requests from your network. "
                                       "Please complete or wait for existing ones to expire.", 429)

            pay = self.get_payment_settings(c)
            now = ts()
            for _ in range(10):
                code = security.new_request_code()
                if not c.execute("SELECT 1 FROM sticker_requests WHERE request_code = ?", (code,)).fetchone():
                    break
            else:  # pragma: no cover - astronomically unlikely
                raise ServiceError("Could not allocate a request ID, please retry.", 503)
            c.execute(
                "INSERT INTO sticker_requests (request_code, tracking_token_hash, idempotency_key_hash, "
                "client_ip_hash, name, email, template_id, character, amount, currency, status, expires_at, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (code, security.token_hash(token), idem_hash, ip_hash, name, email, template_id, character,
                 pay.amount_minor, pay.currency, PENDING,
                 ts_plus(hours=pay.request_expiration_hours), now, now),
            )
            audit(c, "request.create", actor_type="user", target=code, ip_hash=ip_hash)
            self._count(c, "sticker_request_created")
        return {"duplicate": False, "request_code": code, "tracking_token": token, "status": PENDING}

    def _find_by_token(self, c: sqlite3.Connection, token: str) -> sqlite3.Row:
        if not token or not security.TOKEN_RE.match(token):
            raise ServiceError("Request not found.", 404)
        row = c.execute("SELECT * FROM sticker_requests WHERE tracking_token_hash = ?",
                        (security.token_hash(token),)).fetchone()
        if row is None:
            raise ServiceError("Request not found.", 404)
        return row

    def get_by_token(self, token: str) -> sqlite3.Row:
        self.expire_stale()
        with self.db.conn() as c:
            return self._find_by_token(c, token)

    def report_payment(self, token: str, ip_hash: str | None = None) -> sqlite3.Row:
        self.expire_stale()
        with self.db.transaction() as c:
            row = self._find_by_token(c, token)
            if row["status"] == REPORTED:
                return row  # idempotent: repeated clicks change nothing
            if row["status"] != PENDING:
                raise ServiceError(_status_conflict(row["status"]), 409 if row["status"] != EXPIRED else 410)
            now = ts()
            cur = c.execute("UPDATE sticker_requests SET status = ?, payment_reported_at = ?, updated_at = ? "
                            "WHERE id = ? AND status = ?", (REPORTED, now, now, row["id"], PENDING))
            if cur.rowcount != 1:  # pragma: no cover - guarded by the write lock
                raise ServiceError("Request status changed, please refresh.", 409)
            audit(c, "request.report_payment", actor_type="user", target=row["request_code"],
                  details={"from": PENDING, "to": REPORTED}, ip_hash=ip_hash)
            return c.execute("SELECT * FROM sticker_requests WHERE id = ?", (row["id"],)).fetchone()

    def require_approved(self, token: str) -> sqlite3.Row:
        """Authoritative server-side gate for generation and download."""
        row = self.get_by_token(token)
        if row["status"] == EXPIRED:
            raise ServiceError("This request has expired.", 410)
        if row["status"] != APPROVED:
            raise ServiceError("Your sticker is not available until the payment is approved.", 403)
        return row

    def set_character(self, token: str, character: str, ip_hash: str | None = None) -> sqlite3.Row:
        """Attach a (server-computed) quiz character to the requester's own request."""
        self.expire_stale()
        with self.db.transaction() as c:
            row = self._find_by_token(c, token)
            if row["status"] not in (PENDING, REPORTED, APPROVED):
                raise ServiceError(_status_conflict(row["status"]), 410 if row["status"] == EXPIRED else 409)
            c.execute("UPDATE sticker_requests SET character = ?, updated_at = ? WHERE id = ?",
                      (character, ts(), row["id"]))
            audit(c, "request.character", actor_type="user", target=row["request_code"],
                  details={"character": character}, ip_hash=ip_hash)
            return c.execute("SELECT * FROM sticker_requests WHERE id = ?", (row["id"],)).fetchone()

    def require_previewable(self, token: str) -> sqlite3.Row:
        """Watermarked previews are free for any live request (not expired/rejected)."""
        row = self.get_by_token(token)
        if row["status"] == EXPIRED:
            raise ServiceError("This request has expired.", 410)
        if row["status"] == REJECTED:
            raise ServiceError(_status_conflict(REJECTED), 409)
        return row

    # -- analytics (aggregate daily counters, no personal data) --
    ANALYTICS_EVENTS = ("quiz_started", "quiz_completed", "sticker_request_created", "approved_download")

    @staticmethod
    def _count(c: sqlite3.Connection, event: str) -> None:
        c.execute("INSERT INTO analytics_counters (event, day, count) VALUES (?, ?, 1) "
                  "ON CONFLICT(event, day) DO UPDATE SET count = count + 1", (event, ts()[:10]))

    def count_event(self, *events: str) -> None:
        with self.db.transaction() as c:
            for event in events:
                self._count(c, event)

    def analytics_summary(self) -> dict:
        with self.db.conn() as c:
            totals = {r["event"]: r["total"] for r in c.execute(
                "SELECT event, SUM(count) AS total FROM analytics_counters GROUP BY event")}
            today = {r["event"]: r["count"] for r in c.execute(
                "SELECT event, count FROM analytics_counters WHERE day = ?", (ts()[:10],))}
        return {"totals": totals, "today": today}

    def set_template(self, request_id: int, template_id: str) -> None:
        with self.db.transaction() as c:
            c.execute("UPDATE sticker_requests SET template_id = ?, updated_at = ? WHERE id = ? AND status = ?",
                      (template_id, ts(), request_id, APPROVED))

    # -- admin decisions --
    def _transition(self, request_id: int, to_status: str, admin_id: int, fields: dict,
                    audit_details: dict, ip_hash: str | None) -> sqlite3.Row:
        allowed_from = [f for (f, t), who in TRANSITIONS.items() if t == to_status and who == "admin"]
        with self.db.transaction() as c:
            row = c.execute("SELECT * FROM sticker_requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise ServiceError("Request not found.", 404)
            if row["status"] not in allowed_from:
                raise ServiceError(
                    f"Cannot change a request from {row['status']} to {to_status}.", 409)
            now = ts()
            sets = ", ".join(f"{k} = ?" for k in fields)
            cur = c.execute(
                f"UPDATE sticker_requests SET status = ?, {sets}, updated_at = ? WHERE id = ? AND status = ?",
                (to_status, *fields.values(), now, request_id, row["status"]),
            )
            if cur.rowcount != 1:  # pragma: no cover - guarded by the write lock
                raise ServiceError("Request was modified concurrently; refresh and retry.", 409)
            audit(c, f"request.{to_status.lower()}", actor_type="admin", actor_id=admin_id,
                  target=row["request_code"], details={"from": row["status"], "to": to_status, **audit_details},
                  ip_hash=ip_hash)
            return c.execute(ADMIN_SELECT + " WHERE r.id = ?", (request_id,)).fetchone()

    def approve(self, request_id: int, admin_id: int, transaction_reference: str | None,
                ip_hash: str | None = None) -> sqlite3.Row:
        ref = (transaction_reference or "").strip()[:120] or None
        return self._transition(request_id, APPROVED, admin_id,
                                {"approved_at": ts(), "approved_by": admin_id, "transaction_reference": ref},
                                {"transaction_reference": ref}, ip_hash)

    def reject(self, request_id: int, admin_id: int, reason: str, ip_hash: str | None = None) -> sqlite3.Row:
        reason = " ".join((reason or "").split())
        if len(reason) < 3:
            raise ServiceError("A rejection reason is required.", 422)
        if len(reason) > 500:
            raise ServiceError("Rejection reason must be at most 500 characters.", 422)
        return self._transition(request_id, REJECTED, admin_id,
                                {"rejected_at": ts(), "rejected_by": admin_id, "rejection_reason": reason},
                                {"reason": reason}, ip_hash)

    def add_note(self, request_id: int, admin_id: int, username: str, note: str,
                 ip_hash: str | None = None) -> sqlite3.Row:
        note = (note or "").strip()
        if not note or len(note) > 1000:
            raise ServiceError("Note must be 1–1000 characters.", 422)
        with self.db.transaction() as c:
            row = c.execute("SELECT * FROM sticker_requests WHERE id = ?", (request_id,)).fetchone()
            if row is None:
                raise ServiceError("Request not found.", 404)
            entry = f"[{ts()[:16].replace('T', ' ')} UTC] {username}: {note}"
            notes = f"{row['admin_notes']}\n{entry}" if row["admin_notes"] else entry
            c.execute("UPDATE sticker_requests SET admin_notes = ?, updated_at = ? WHERE id = ?",
                      (notes[-10000:], ts(), request_id))
            audit(c, "request.note", actor_type="admin", actor_id=admin_id, target=row["request_code"],
                  ip_hash=ip_hash)
            return c.execute(ADMIN_SELECT + " WHERE r.id = ?", (request_id,)).fetchone()

    def list_requests(self, status: str | None) -> list[dict]:
        self.expire_stale()
        sql = ADMIN_SELECT
        params: tuple = ()
        if status:
            sql += " WHERE r.status = ?"
            params = (status,)
        sql += " ORDER BY CASE r.status WHEN 'PAYMENT_REPORTED' THEN 0 ELSE 1 END, r.created_at DESC LIMIT 500"
        with self.db.conn() as c:
            return [admin_view(r) for r in c.execute(sql, params).fetchall()]

    def recent_audit(self, limit: int = 100) -> list[dict]:
        with self.db.conn() as c:
            rows = c.execute(
                "SELECT l.*, a.username FROM audit_logs l LEFT JOIN admins a "
                "ON l.actor_type = 'admin' AND a.id = l.actor_id ORDER BY l.id DESC LIMIT ?",
                (max(1, min(limit, 500)),)).fetchall()
        return [{"created_at": r["created_at"], "actor": r["username"] or r["actor_type"],
                 "action": r["action"], "target": r["target"],
                 "details": json.loads(r["details"]) if r["details"] else None} for r in rows]

    # -- admins & sessions --
    def create_admin(self, username: str, password: str) -> int:
        username = (username or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,40}", username):
            raise ServiceError("Username must be 3–40 characters: letters, digits, _ . -", 422)
        try:
            security.validate_new_password(password)
        except ValueError as e:
            raise ServiceError(str(e), 422)
        with self.db.transaction() as c:
            try:
                cur = c.execute("INSERT INTO admins (username, password_hash, created_at) VALUES (?, ?, ?)",
                                (username, security.hash_password(password), ts()))
            except sqlite3.IntegrityError:
                raise ServiceError("That username already exists.", 409)
            audit(c, "admin.create", actor_type="system", target=username)
            return cur.lastrowid

    def authenticate(self, username: str, password: str, ip_hash: str | None) -> tuple[str, str, sqlite3.Row] | None:
        with self.db.conn() as c:
            admin = c.execute("SELECT * FROM admins WHERE username = ?", ((username or "")[:40],)).fetchone()
        ok = security.verify_password(password or "", admin["password_hash"] if admin
                                      else security.DUMMY_PASSWORD_HASH)
        with self.db.transaction() as c:
            if not (ok and admin):
                audit(c, "admin.login_failed", actor_type="anonymous",
                      target=(username or "")[:40], ip_hash=ip_hash)
                return None
            token, csrf = security.new_token(), security.new_token()
            now = utcnow()
            c.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (ts(now),))
            c.execute("INSERT INTO admin_sessions (token_hash, admin_id, csrf_token, created_at, expires_at) "
                      "VALUES (?, ?, ?, ?, ?)", (security.token_hash(token), admin["id"], csrf, ts(now),
                                                 ts_plus(hours=self.settings.session_hours)))
            c.execute("UPDATE admins SET last_login_at = ? WHERE id = ?", (ts(now), admin["id"]))
            audit(c, "admin.login", actor_type="admin", actor_id=admin["id"], ip_hash=ip_hash)
            return token, csrf, admin

    def session(self, token: str | None) -> sqlite3.Row | None:
        if not token or not security.TOKEN_RE.match(token):
            return None
        with self.db.conn() as c:
            return c.execute(
                "SELECT s.id AS session_id, s.csrf_token, a.id AS admin_id, a.username "
                "FROM admin_sessions s JOIN admins a ON a.id = s.admin_id "
                "WHERE s.token_hash = ? AND s.expires_at > ?", (security.token_hash(token), ts())).fetchone()

    def logout(self, session_id: int, admin_id: int, ip_hash: str | None) -> None:
        with self.db.transaction() as c:
            c.execute("DELETE FROM admin_sessions WHERE id = ?", (session_id,))
            audit(c, "admin.logout", actor_type="admin", actor_id=admin_id, ip_hash=ip_hash)

    # -- retention --
    def purge(self, days: int) -> dict:
        cutoff = ts_plus(days=-days)
        with self.db.transaction() as c:
            deleted = c.execute("DELETE FROM sticker_requests WHERE status IN (?, ?) AND updated_at < ?",
                                (EXPIRED, REJECTED, cutoff)).rowcount
            anonymized = c.execute(
                "UPDATE sticker_requests SET email = NULL, client_ip_hash = NULL, idempotency_key_hash = NULL "
                "WHERE updated_at < ? AND (email IS NOT NULL OR client_ip_hash IS NOT NULL)", (cutoff,)).rowcount
            c.execute("UPDATE sticker_requests SET client_ip_hash = NULL WHERE created_at < ?",
                      (ts_plus(days=-30),))
            c.execute("DELETE FROM admin_sessions WHERE expires_at < ?", (ts(),))
            c.execute("UPDATE audit_logs SET ip_hash = NULL WHERE created_at < ?", (cutoff,))
            audit(c, "retention.purge", actor_type="system",
                  details={"days": days, "deleted": deleted, "anonymized": anonymized})
        return {"deleted": deleted, "anonymized": anonymized}


def _mask(key: str, value) -> str:
    value = str(value)
    if key == "account_number" and len(value) > 4:
        return "•" * (len(value) - 4) + value[-4:]
    return value[:200]


def _status_conflict(status: str) -> str:
    return {
        APPROVED: "This request is already approved.",
        REJECTED: "This request was rejected. Please contact the administrator.",
        EXPIRED: "This request has expired. Please create a new request.",
    }.get(status, "This action is not allowed in the current state.")


def public_view(row: sqlite3.Row, pay: PaymentSettings, lang: str = "en") -> dict:
    """What the requester may see — never internal IDs, admin data or notes."""
    status = row["status"]
    data = {
        "request_code": row["request_code"],
        "name": row["name"],
        "status": status,
        "status_message": tr(STATUS_MESSAGES[status], lang),
        "amount_display": format_amount(row["amount"], row["currency"]),
        "created_at": row["created_at"],
        "expires_at": row["expires_at"] if status == PENDING else None,
        "payment_reported_at": row["payment_reported_at"],
        "approved_at": row["approved_at"],
        "template_id": row["template_id"],
        "character": row["character"],
        "can_generate": status == APPROVED,
    }
    if status in (PENDING, REPORTED):
        data["payment"] = {
            "bank_name": pay.bank_name,
            "account_holder": pay.account_holder,
            "account_number": pay.account_number,
            "amount_display": data["amount_display"],
            "instructions": pay.payment_instructions_mn if lang == "mn" else pay.payment_instructions,
            "reference": row["request_code"],
        }
    if status == REJECTED:
        data["rejection_reason"] = row["rejection_reason"]
        data["next_steps"] = tr("If you believe this is a mistake, contact the administrator "
                                f"and quote your request ID {row['request_code']}.", lang)
    return data


def admin_view(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "request_code": row["request_code"],
        "name": row["name"],
        "email": row["email"],
        "template_id": row["template_id"],
        "character": row["character"],
        "amount_display": format_amount(row["amount"], row["currency"]),
        "amount_minor": row["amount"],
        "currency": row["currency"],
        "status": row["status"],
        "created_at": row["created_at"],
        "payment_reported_at": row["payment_reported_at"],
        "approved_at": row["approved_at"],
        "approved_by": row["approved_by_name"],
        "rejected_at": row["rejected_at"],
        "rejected_by": row["rejected_by_name"],
        "rejection_reason": row["rejection_reason"],
        "transaction_reference": row["transaction_reference"],
        "admin_notes": row["admin_notes"],
        "expires_at": row["expires_at"],
    }
