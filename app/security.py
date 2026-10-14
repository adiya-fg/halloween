"""Security primitives: password hashing, tokens, rate limiting."""
from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
import string
import threading
import time
from collections import defaultdict, deque

# --- Password hashing (scrypt, stdlib) -------------------------------------
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**15, 8, 1
_SCRYPT_MAXMEM = 64 * 1024 * 1024


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R,
                        p=_SCRYPT_P, maxmem=_SCRYPT_MAXMEM, dklen=32)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${_b64(salt)}${_b64(dk)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algo, n, r, p, salt, expected = encoded.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=_unb64(salt), n=int(n), r=int(r),
                            p=int(p), maxmem=_SCRYPT_MAXMEM, dklen=len(_unb64(expected)))
        return hmac.compare_digest(dk, _unb64(expected))
    except (ValueError, TypeError):
        return False


# Used to equalise timing when a username does not exist.
DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(16))


def validate_new_password(password: str) -> None:
    if len(password) < 12:
        raise ValueError("Password must be at least 12 characters long.")
    classes = sum((
        any(c.islower() for c in password),
        any(c.isupper() for c in password),
        any(c.isdigit() for c in password),
        any(c in string.punctuation or c.isspace() for c in password),
    ))
    if classes < 2:
        raise ValueError("Use a mix of letters, numbers or symbols.")


# --- Tokens -----------------------------------------------------------------
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no I, O, 0, 1


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def token_hash(token: str) -> str:
    """Tracking/session tokens are high-entropy, so a fast hash is appropriate."""
    return hashlib.sha256(token.encode()).hexdigest()


def new_request_code() -> str:
    return "HW26-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))


def keyed_hash(secret_key: str, value: str) -> str:
    """Pseudonymous identifier (e.g. for IP addresses) — not reversible without the key."""
    return hmac.new(secret_key.encode(), value.encode(), hashlib.sha256).hexdigest()[:32]


# --- Rate limiting (in-memory sliding window) ---------------------------------
class RateLimiter:
    """Process-local sliding-window limiter.

    Adequate for a single-process deployment. For multiple workers, put a
    shared limiter (e.g. a reverse proxy or Redis) in front.
    """

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, window: float, now: float) -> deque:
        q = self._hits[key]
        while q and q[0] <= now - window:
            q.popleft()
        return q

    def hit(self, key: str, limit: int, window: float) -> bool:
        """Record an attempt; return False if the limit is exceeded."""
        if not self.enabled:
            return True
        now = time.monotonic()
        with self._lock:
            q = self._prune(key, window, now)
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def is_limited(self, key: str, limit: int, window: float) -> bool:
        if not self.enabled:
            return False
        with self._lock:
            return len(self._prune(key, window, time.monotonic())) >= limit

    def record(self, key: str) -> None:
        if self.enabled:
            with self._lock:
                self._hits[key].append(time.monotonic())

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
