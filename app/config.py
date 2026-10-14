"""Application configuration loaded from environment variables.

Secrets and deployment settings come exclusively from the environment (or a
local, git-ignored ``.env`` file during development). Nothing secret is
hard-coded here; bank defaults are obvious placeholders.
"""
from __future__ import annotations

import os
import secrets
import warnings
from dataclasses import dataclass
from pathlib import Path

try:  # optional convenience for local development
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


def _bool(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


@dataclass
class Settings:
    app_env: str = "production"
    secret_key: str = ""
    database_path: str = "data/halloween.db"
    cookie_secure: bool = True
    session_hours: int = 8
    trust_proxy: bool = False
    rate_limit_enabled: bool = True
    retention_days: int = 180
    max_open_requests_per_ip: int = 5

    # Initial payment configuration (seeded into the DB once; afterwards the
    # admin dashboard is the source of truth).
    bank_name: str = "Example Bank (PLACEHOLDER)"
    account_holder: str = "Placeholder Account Holder"
    account_number: str = "000-0000000 (PLACEHOLDER)"
    payment_amount: str = "1000"
    payment_currency: str = "MNT"
    payment_instructions: str = (
        "Transfer the exact amount and put your request ID in the transfer "
        "description. (Placeholder instructions — configure in the admin dashboard.)"
    )
    payment_instructions_mn: str = (
        "Яг заасан дүнгээр шилжүүлж, гүйлгээний утга дээр хүсэлтийн дугаараа бичнэ үү. "
        "(Түр заавар — админ самбараас тохируулна уу.)"
    )
    request_expiration_hours: int = 72

    @property
    def is_development(self) -> bool:
        return self.app_env.lower() in {"development", "dev", "test"}

    @classmethod
    def from_env(cls) -> "Settings":
        env = os.environ
        s = cls(
            app_env=env.get("APP_ENV", "production"),
            secret_key=env.get("SECRET_KEY", ""),
            database_path=env.get("DATABASE_PATH", "data/halloween.db"),
            cookie_secure=_bool(env.get("COOKIE_SECURE"), True),
            session_hours=_int(env.get("SESSION_HOURS"), 8),
            trust_proxy=_bool(env.get("TRUST_PROXY"), False),
            rate_limit_enabled=_bool(env.get("RATE_LIMIT_ENABLED"), True),
            retention_days=_int(env.get("RETENTION_DAYS"), 180),
            max_open_requests_per_ip=_int(env.get("MAX_OPEN_REQUESTS_PER_IP"), 5),
            bank_name=env.get("BANK_NAME", cls.bank_name),
            account_holder=env.get("BANK_ACCOUNT_HOLDER", cls.account_holder),
            account_number=env.get("BANK_ACCOUNT_NUMBER", cls.account_number),
            payment_amount=env.get("PAYMENT_AMOUNT", cls.payment_amount),
            payment_currency=env.get("PAYMENT_CURRENCY", cls.payment_currency),
            payment_instructions=env.get("PAYMENT_INSTRUCTIONS", cls.payment_instructions),
            payment_instructions_mn=env.get("PAYMENT_INSTRUCTIONS_MN", cls.payment_instructions_mn),
            request_expiration_hours=_int(env.get("REQUEST_EXPIRATION_HOURS"), 72),
        )
        s.validate()
        return s

    def validate(self) -> None:
        if not self.secret_key:
            if not self.is_development:
                raise RuntimeError(
                    "SECRET_KEY must be set in production. Generate one with: "
                    "python -c \"import secrets; print(secrets.token_urlsafe(48))\""
                )
            warnings.warn("SECRET_KEY not set; using an ephemeral development key.")
            self.secret_key = secrets.token_urlsafe(48)
        elif len(self.secret_key) < 32 and not self.is_development:
            raise RuntimeError("SECRET_KEY must be at least 32 characters long.")
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
