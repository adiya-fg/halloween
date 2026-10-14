# 🎃 Halloween 2026 — Personalized Sticker Generator

A small web app where people request a personalized Halloween 2026 name sticker,
pay by **manual bank transfer**, and can generate and download their sticker
only **after an administrator has verified the payment by hand**.

- **Backend:** FastAPI + SQLite (stdlib `sqlite3`, parameterized SQL)
- **Frontend:** HTML, CSS, vanilla JS (ES modules), no external CDNs
- **Artwork:** deterministic vector SVG rendered by the server and rasterized in the browser to a 3000 × 3000 PNG. No paid AI APIs.

> The app **never connects to a bank** and never claims to verify payments
> automatically. Verification is always done manually by an administrator.

## How it works

1. **Request:** the user enters a name (and optionally an email and a favorite design) on `/`.
   The server creates a request such as `HW26-A7K9Q2` with status `PENDING_PAYMENT`
   and returns a private tracking token.
2. **Pay:** the private status page `/track#<token>` shows the bank details,
   the amount and the request ID to put in the transfer description. The user clicks
   **"I Have Transferred the Money"**, which sets `PAYMENT_REPORTED`. This does not approve anything.
3. **Verify:** the admin checks the real bank account, then approves the request
   (with an optional transaction reference) or rejects it with a reason at `/admin`.
4. **Generate:** once the backend reports `APPROVED`, the user picks a design,
   previews the sticker and downloads a high-resolution PNG (or vector SVG).

Statuses: `PENDING_PAYMENT → PAYMENT_REPORTED → APPROVED | REJECTED`, and
`PENDING_PAYMENT → EXPIRED` once the configured expiration time passes.
Every other transition is refused with HTTP 409.

## Languages

The site is shown in **Mongolian (Cyrillic)** only; there is no language switch. The English
strings are kept in the dictionary as a fallback for missing keys.

- UI text lives in [app/static/js/i18n.js](app/static/js/i18n.js) (`data-i18n` keys in the HTML).
- API status and error messages are translated on the server from the request's `Accept-Language`
  header ([app/i18n.py](app/i18n.py)).
- Payment instructions are free text, so the admin sets an English **and** a Mongolian version in
  **Payment settings**.

## Character quiz — "Which Halloween Character Matches You in 2026?"

A free, just-for-fun quiz at `/quiz` (linked from the homepage). It has six multiple-choice questions,
shown one at a time with a progress bar and Back/Next buttons. It is not a psychological assessment.

**Scoring** is in [app/quiz.py](app/quiz.py), the single source of truth:

| Answer | Q1 night | Q2 strength | Q3 colour | Q4 ghost | Q5 power | Q6 phrase |
|---|---|---|---|---|---|---|
| A | Wizard | Wizard | Vampire (purple) | Wizard | Wizard | Wizard |
| B | Vampire | Vampire | Friendly Ghost (orange) | Vampire | Vampire | Vampire |
| C | Friendly Ghost | Friendly Ghost | Wizard (green) | Friendly Ghost | Friendly Ghost | Friendly Ghost |
| D | Black Cat | Black Cat | Black Cat (black) | Black Cat | Black Cat | Black Cat |

- Each answer gives one point to its character, and the highest total wins.
- **Tie-break:** among the tied characters, the one picked in the *latest* question wins
  (scan from Q6 back to Q1). This always resolves, and the same answers always give the same result.
- The browser sends the answers to `POST /api/quiz/result`, and the server returns the character.
- Answers and the result are kept in `sessionStorage`, so Back/Next and page reloads never lose or
  change them. **Try Again** clears them.

**Character stickers:**
- "Create My Personalized Sticker" builds a sticker with the character in place of each design's
  central figure, "YOUR CHARACTER: …", the user's name, "HALLOWEEN 2026" and (optionally) the three traits.
- Previews are free but small and watermarked (`POST /api/quiz/preview`, `GET /api/requests/{token}/preview`).
- Requesting the sticker creates a normal request with `quiz_answers`, or adds the character to the
  visitor's existing request. The server computes the character and stores only the result
  (the `character` column); raw answers are never stored.
- The clean 3000 px download still requires `APPROVED`, checked on every download. The payment
  workflow is unchanged.

**Sharing** uses the Web Share API when the browser has it, then the clipboard, then a text box to copy
from manually. Nothing is posted automatically.

**Analytics** are aggregate daily counters only (`analytics_counters`, shown in **Admin → Quiz stats**):
quiz started, quiz completed, results per character, sticker requests created and approved downloads.
No answers or personal data are stored.

## Docker

```bash
cp .env.example .env      # set SECRET_KEY (and APP_ENV=production)
docker compose up -d --build
docker compose exec web python -m app.cli create-admin --username organizer
```

The app is served at http://localhost:8000 (bound to localhost only). The data lives in the
`sticker-data` volume.

## Local setup

Requires Python 3.11+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # then edit .env (set SECRET_KEY)
python -c "import secrets; print(secrets.token_urlsafe(48))"   # → paste into SECRET_KEY

python -m app.cli init-db                       # create tables + seed placeholder payment settings
python -m app.cli create-admin --username organizer   # prompts for a password (min 12 chars)

uvicorn app.main:get_app --factory --reload --port 8000
```

Then open:
- http://localhost:8000/ for the public request page
- http://localhost:8000/admin for the admin dashboard

`init-db` is optional, because the schema is also created on startup. It is safe to run repeatedly.

### Admin accounts

There is **no default admin password**. Create admins with:

```bash
python -m app.cli create-admin --username alice
# non-interactive (e.g. in a deploy script, with the password from a secret store):
printf '%s\n' "$ADMIN_PASSWORD" | python -m app.cli create-admin --username alice --password-stdin
```

Passwords must be at least 12 characters long and mix character types. They are stored as salted **scrypt** hashes.

### Payment configuration

Bank name, account holder, account number, amount, currency, instructions and
request expiration are seeded from environment variables **on first start only**.
After that, edit them in **Admin → Payment settings**, and every change is audited.

Each request stores the amount and currency in effect **when it was created**
(as integer minor units). Changing the price never affects existing requests.
Never commit real bank details. Enter them through the dashboard in production.

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `APP_ENV` | `production` | `development` allows an ephemeral `SECRET_KEY`. Production refuses to start without one. |
| `SECRET_KEY` | — | ≥32 random characters. Used to pseudonymize client IPs for anti-spam. |
| `DATABASE_PATH` | `data/halloween.db` | SQLite file location. |
| `COOKIE_SECURE` | `true` | Admin cookie sent only over HTTPS. Set `false` only for plain-http localhost. |
| `SESSION_HOURS` | `8` | Admin session lifetime. |
| `TRUST_PROXY` | `false` | Use `X-Forwarded-For` for client IPs. Enable **only** behind a trusted reverse proxy. |
| `RATE_LIMIT_ENABLED` | `true` | In-memory rate limiting of public endpoints and login. |
| `MAX_OPEN_REQUESTS_PER_IP` | `5` | Max unpaid requests per client network per 24 h (`0` disables). |
| `RETENTION_DAYS` | `180` | Used by `python -m app.cli purge`. |
| `BANK_NAME`, `BANK_ACCOUNT_HOLDER`, `BANK_ACCOUNT_NUMBER` | placeholders | Initial bank details. |
| `PAYMENT_AMOUNT`, `PAYMENT_CURRENCY` | `1000`, `MNT` | Initial fee (a decimal string plus an ISO currency code). |
| `PAYMENT_INSTRUCTIONS` | placeholder | Initial transfer instructions (English). |
| `PAYMENT_INSTRUCTIONS_MN` | placeholder | Initial transfer instructions (Mongolian). |
| `REQUEST_EXPIRATION_HOURS` | `72` | Unpaid requests expire after this time. |

## API

Public endpoints. `{token}` is the private tracking token:

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/config` | Fee and design list |
| `GET` | `/api/templates/{id}/preview.svg` | Small watermarked sample |
| `POST` | `/api/requests` | `{name, email?, template_id?, client_key?}`. Unknown fields are rejected. |
| `GET` | `/api/requests/{token}` | Authoritative status. Bank details only while unpaid or reported. |
| `POST` | `/api/requests/{token}/report-payment` | Idempotent |
| `POST` | `/api/requests/{token}/generate` | **Requires `APPROVED`**. Returns the SVG preview. |
| `GET` | `/api/requests/{token}/download` | **Requires `APPROVED`**. Returns the 3000 px SVG as an attachment. |

Admin endpoints require a session cookie, and every write also needs an `X-CSRF-Token` header:
`POST /api/admin/login`, `POST /api/admin/logout`, `GET /api/admin/me`,
`GET /api/admin/requests?status=ALL|PENDING_PAYMENT|…`,
`POST /api/admin/requests/{id}/approve` (`{"confirm": true, "transaction_reference": "…"}`),
`POST /api/admin/requests/{id}/reject` (`{"reason": "…"}`),
`POST /api/admin/requests/{id}/notes`, `GET|PATCH /api/admin/settings`, `GET /api/admin/audit`.

## Security notes

- **Server-side gating:** generation and download check the database status on every call.
  The browser's idea of the status is never trusted, and no high-resolution URL is exposed before approval.
- **Tracking tokens:** 256-bit random values. Only their SHA-256 hash is stored.
  The status page keeps the token in the URL **fragment** (`/track#…`), so it is never sent in
  `Referer` headers. API paths do contain it, so avoid logging full URLs in your reverse proxy if possible.
- **Admin auth:** scrypt password hashes, server-side sessions (hashed tokens),
  `HttpOnly; SameSite=Strict; Secure` cookies, CSRF tokens on all writes, timing-safe login,
  and login rate limiting by IP and username.
- **Integrity:** status changes are conditional `UPDATE … WHERE status = ?` statements inside
  `BEGIN IMMEDIATE` transactions, so concurrent approvals cannot double-approve or mix states.
  Approval requires an explicit `confirm: true` and records the admin ID, timestamp and transaction reference.
- **Audit log:** logins (success and failure), report, approve, reject, note, expiry, settings changes
  (with the account number masked) and retention runs.
- **XSS / injection:** parameterized SQL everywhere, XML-escaped names in SVG, `textContent`-only
  DOM rendering, and a strict CSP (`script-src 'self'`, no inline scripts or styles), plus `X-Frame-Options: DENY`.
- **Anti-spam:** honeypot field, per-IP rate limits, a cap on unpaid requests per network,
  and idempotency keys against double submits.
- **Privacy:** public responses never include email, notes or internal IDs. IPs are stored only as
  keyed hashes and cleared after 30 days. Run the retention job regularly:

  ```bash
  python -m app.cli purge            # deletes EXPIRED/REJECTED requests older than RETENTION_DAYS,
                                     # strips emails from old requests, drops expired sessions
  ```

## Testing

```bash
pytest                                  # backend: workflow, security, i18n, rendering, quiz
node --test tests/js/quiz-state.test.mjs   # quiz navigation state (Node 18+)
```

149 backend tests and 8 Node tests cover the full lifecycle, every required case (pending, reported, approved and rejected gating;
unauthenticated admin access; tampered payloads; invalid transitions; long and non-ASCII names;
duplicate submissions; invalid and expired tokens; concurrent approvals), CSRF, rate limiting,
password hashing, settings auditing and SVG escaping.

## Deployment guidance

1. Run behind HTTPS (e.g. Caddy or nginx as a reverse proxy) and set
   `APP_ENV=production`, a strong `SECRET_KEY`, `COOKIE_SECURE=true`, and `TRUST_PROXY=true`
   if the proxy sets `X-Forwarded-For`.
2. Run **a single worker process**:
   `uvicorn app.main:get_app --factory --host 127.0.0.1 --port 8000 --proxy-headers`.
   The rate limiter is in-memory and SQLite favors one writer. For several workers, move rate
   limiting to the proxy or Redis and consider PostgreSQL.
3. Put `DATABASE_PATH` on persistent storage and back it up (`sqlite3 halloween.db ".backup backup.db"`).
4. Create the first admin with `create-admin`, then enter the real bank details in the dashboard.
5. Schedule `python -m app.cli purge` (e.g. daily via cron or Task Scheduler).
6. Optionally restrict `/admin` and `/api/admin/*` by IP at the proxy.

## Limitations

- PNG rasterization happens **in the browser** (canvas), so no native imaging libraries are needed on
  the server. The server still enforces approval because it only delivers the sticker SVG to approved
  requests. Text uses the viewer's system fonts. Cyrillic (Mongolian) and Japanese render with standard
  OS fonts. Traditional Mongolian script is drawn horizontally and depends on an installed font such as
  *Mongolian Baiti* or *Noto Sans Mongolian*.
- Gallery previews are public, watermarked samples of the same artwork.
- Rate limits are per process and reset on restart.
- Email is stored for the organizer's manual contact only. No emails are sent.
- If a user loses their private link, an admin can find the request by request ID, but
  cannot re-issue the link. Only the token hash is stored.
