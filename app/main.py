"""FastAPI application: public API, admin API, static pages, security middleware."""
from __future__ import annotations

import hmac
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from . import security
from .config import Settings
from .i18n import parse_lang, tr
from .quiz import (CHARACTER_ORDER, NUM_QUESTIONS, STICKER_LABEL, QuizError, character_info,
                   quiz_content, score)
from .services import (App, ServiceError, STATUS_MESSAGES, admin_view, normalize_name, public_view)
from .stickers import DEFAULT_TEMPLATE, TEMPLATES, character_svg, render_sticker

STATIC_DIR = Path(__file__).parent / "static"
SESSION_COOKIE = "hw_admin_session"

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; "
       "form-action 'self'; frame-ancestors 'none'")


# --- Request models (extra fields are rejected, so clients cannot inject
# --- status/amount/approval fields) --------------------------------------------
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


Answers = list[Literal["A", "B", "C", "D"]]
ANSWERS_FIELD = dict(min_length=NUM_QUESTIONS, max_length=NUM_QUESTIONS)


class CreateRequestIn(Strict):
    name: str = Field(max_length=200)
    email: Optional[str] = Field(default=None, max_length=254)
    template_id: Optional[str] = Field(default=None, max_length=40)
    client_key: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_-]{16,64}$")
    website: Optional[str] = Field(default=None, max_length=200)  # honeypot: must stay empty
    # Raw quiz answers: the server computes the character and stores only the result.
    quiz_answers: Optional[Answers] = Field(default=None, **ANSWERS_FIELD)


class GenerateIn(Strict):
    template_id: str = Field(max_length=40)
    transparent: bool = True
    with_character: bool = True
    show_traits: bool = True


class QuizAnswersIn(Strict):
    answers: Answers = Field(**ANSWERS_FIELD)


class QuizPreviewIn(Strict):
    answers: Answers = Field(**ANSWERS_FIELD)
    name: str = Field(max_length=200)
    template_id: str = Field(max_length=40)
    transparent: bool = True
    show_traits: bool = True


class EventIn(Strict):
    event: Literal["quiz_started"]  # the only event the browser may report


class LoginIn(Strict):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


class ApproveIn(Strict):
    confirm: Literal[True]
    transaction_reference: Optional[str] = Field(default=None, max_length=120)


class RejectIn(Strict):
    reason: str = Field(max_length=500)


class NoteIn(Strict):
    note: str = Field(max_length=1000)


class SettingsIn(Strict):
    bank_name: Optional[str] = Field(default=None, max_length=120)
    account_holder: Optional[str] = Field(default=None, max_length=120)
    account_number: Optional[str] = Field(default=None, max_length=80)
    amount: Optional[str] = Field(default=None, max_length=20)
    currency: Optional[str] = Field(default=None, max_length=3)
    payment_instructions: Optional[str] = Field(default=None, max_length=2000)
    payment_instructions_mn: Optional[str] = Field(default=None, max_length=2000)
    request_expiration_hours: Optional[int] = Field(default=None, ge=1, le=1440)


StatusFilter = Literal["ALL", "PENDING_PAYMENT", "PAYMENT_REPORTED", "APPROVED", "REJECTED", "EXPIRED"]


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    svc = App(settings)
    limiter = security.RateLimiter(settings.rate_limit_enabled)

    app = FastAPI(title="Halloween 2026 Stickers", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.svc = svc
    app.state.limiter = limiter
    app.state.settings = settings

    # ---------------------------------------------------------------- helpers
    def client_ip(request: Request) -> str:
        if settings.trust_proxy:
            fwd = request.headers.get("x-forwarded-for")
            if fwd:
                return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def lang_of(request: Request) -> str:
        return parse_lang(request.headers.get("accept-language"))

    def character_of(answers) -> str:
        try:
            return score(answers)[0]
        except QuizError as e:
            raise ServiceError(str(e), 422)

    def build_sticker(template_id: str, name: str, character: str | None, lang: str, *,
                      transparent: bool, with_character: bool = True, show_traits: bool = True,
                      **kwargs) -> str:
        if template_id not in TEMPLATES:
            raise ServiceError("Unknown design.", 422)
        if character and with_character:
            info = character_info(character, lang)
            return render_sticker(
                template_id, name, transparent=transparent, character=character,
                character_label=STICKER_LABEL[lang].format(name=info["name"].upper()),
                traits=info["traits"] if show_traits else None, **kwargs)
        return render_sticker(template_id, name, transparent=transparent, **kwargs)

    def ip_hash(request: Request) -> str:
        return security.keyed_hash(settings.secret_key, client_ip(request))

    def rate_limit(request: Request, bucket: str, limit: int, window: float) -> None:
        if not limiter.hit(f"{bucket}:{client_ip(request)}", limit, window):
            raise ServiceError("Too many requests. Please slow down and try again shortly.", 429)

    def require_admin(request: Request) -> dict:
        sess = svc.session(request.cookies.get(SESSION_COOKIE))
        if sess is None:
            raise ServiceError("Authentication required.", 401)
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            sent = request.headers.get("x-csrf-token", "")
            if not sent or not hmac.compare_digest(sent, sess["csrf_token"]):
                raise ServiceError("Invalid or missing CSRF token.", 403)
        return dict(sess)

    # ------------------------------------------------------------ middleware
    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", CSP)
        h["X-Content-Type-Options"] = "nosniff"
        h["X-Frame-Options"] = "DENY"
        h["Referrer-Policy"] = "no-referrer"
        h["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        h["Cross-Origin-Opener-Policy"] = "same-origin"
        if settings.cookie_secure:
            h["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith("/api/") and "cache-control" not in h:
            h["Cache-Control"] = "no-store"
        elif request.url.path.startswith("/static/") and "cache-control" not in h:
            # Revalidate via ETag so edited JS/CSS (e.g. translations) show up on the next load.
            h["Cache-Control"] = "no-cache"
        return response

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, exc: ServiceError):
        return JSONResponse({"detail": tr(exc.message, lang_of(request))}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        errors = [{"field": ".".join(str(p) for p in e["loc"][1:]), "message": e["msg"]} for e in exc.errors()]
        return JSONResponse({"detail": tr("Invalid input.", lang_of(request)), "errors": errors}, status_code=422)

    # ---------------------------------------------------------------- pages
    def page(name: str):
        def handler():
            return FileResponse(STATIC_DIR / name, headers={"Cache-Control": "no-cache"})
        return handler

    app.get("/", include_in_schema=False)(page("index.html"))
    app.get("/track", include_in_schema=False)(page("track.html"))
    app.get("/admin", include_in_schema=False)(page("admin.html"))
    app.get("/quiz", include_in_schema=False)(page("quiz.html"))
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ------------------------------------------------------------ public API
    @app.get("/api/config")
    def public_config():
        pay = svc.get_payment_settings()
        return {
            "amount_display": pay.amount_display,
            "currency": pay.currency,
            "request_expiration_hours": pay.request_expiration_hours,
            "templates": [{"id": t.id, "name": t.name, "description": t.description}
                          for t in TEMPLATES.values()],
            "name_max_length": 40,
        }

    @app.get("/api/templates/{template_id}/preview.svg")
    def template_preview(template_id: str, request: Request, lang: Literal["en", "mn"] = "en"):
        rate_limit(request, "preview", 300, 60)
        if template_id not in TEMPLATES:
            raise ServiceError("Unknown design.", 404)
        sample = "Таны нэр" if lang == "mn" else "Your Name"
        svg = render_sticker(template_id, sample, watermark=True, size_px=480)
        return Response(svg, media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600"})

    @app.post("/api/requests", status_code=201)
    def create_request(body: CreateRequestIn, request: Request, response: Response):
        rate_limit(request, "create", 10, 600)
        if body.website:  # honeypot tripped -> bot
            raise ServiceError("Invalid submission.", 400)
        character = character_of(body.quiz_answers) if body.quiz_answers else None
        result = svc.create_request(name=body.name, email=body.email, template_id=body.template_id,
                                    idempotency_key=body.client_key, ip_hash=ip_hash(request),
                                    character=character)
        if result["duplicate"]:
            response.status_code = 200
        return result

    @app.get("/api/requests/{token}")
    def get_request(token: str, request: Request):
        rate_limit(request, "status", 120, 60)
        row = svc.get_by_token(token)
        return public_view(row, svc.get_payment_settings(), lang_of(request))

    @app.post("/api/requests/{token}/report-payment")
    def report_payment(token: str, request: Request):
        rate_limit(request, "report", 20, 600)
        row = svc.report_payment(token, ip_hash(request))
        data = public_view(row, svc.get_payment_settings(), lang_of(request))
        data["message"] = tr("Your payment report has been received. Your sticker will become "
                             "available after administrator verification.", lang_of(request))
        return data

    @app.post("/api/requests/{token}/generate")
    def generate(token: str, body: GenerateIn, request: Request):
        rate_limit(request, "generate", 60, 60)
        row = svc.require_approved(token)  # server-side approval gate
        if body.template_id not in TEMPLATES:
            raise ServiceError("Unknown design.", 422)
        svg = build_sticker(body.template_id, row["name"], row["character"], lang_of(request),
                            transparent=body.transparent, with_character=body.with_character,
                            show_traits=body.show_traits, size_px=1000)
        svc.set_template(row["id"], body.template_id)
        return {"template_id": body.template_id, "svg": svg, "request_code": row["request_code"]}

    @app.get("/api/requests/{token}/download")
    def download(token: str, request: Request,
                 template_id: Optional[str] = Query(default=None, max_length=40),
                 transparent: bool = True, with_character: bool = True, show_traits: bool = True):
        rate_limit(request, "download", 30, 60)
        row = svc.require_approved(token)  # server-side approval gate, re-checked on every download
        tpl = template_id or row["template_id"] or DEFAULT_TEMPLATE
        svg = build_sticker(tpl, row["name"], row["character"], lang_of(request), transparent=transparent,
                            with_character=with_character, show_traits=show_traits)
        svc.count_event("approved_download")
        filename = f"halloween-2026-{row['request_code']}-{tpl}.svg"
        return Response(svg, media_type="image/svg+xml", headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        })

    @app.get("/api/requests/{token}/preview")
    def request_preview(token: str, request: Request,
                        template_id: Optional[str] = Query(default=None, max_length=40),
                        transparent: bool = True, with_character: bool = True, show_traits: bool = True):
        """Free, small, watermarked preview — available before approval."""
        rate_limit(request, "preview-req", 60, 60)
        row = svc.require_previewable(token)
        tpl = template_id or row["template_id"] or DEFAULT_TEMPLATE
        svg = build_sticker(tpl, row["name"], row["character"], lang_of(request), transparent=transparent,
                            with_character=with_character, show_traits=show_traits,
                            watermark="PREVIEW", size_px=480)
        return {"template_id": tpl, "svg": svg, "status": row["status"]}

    @app.post("/api/requests/{token}/character")
    def request_character(token: str, body: QuizAnswersIn, request: Request):
        rate_limit(request, "character", 20, 600)
        row = svc.set_character(token, character_of(body.answers), ip_hash(request))
        return public_view(row, svc.get_payment_settings(), lang_of(request))

    # ------------------------------------------------------------------ quiz
    @app.get("/api/quiz")
    def quiz(request: Request):
        return quiz_content(lang_of(request))

    @app.post("/api/quiz/result")
    def quiz_result(body: QuizAnswersIn, request: Request):
        rate_limit(request, "quiz", 60, 600)
        character, points = score(body.answers)
        svc.count_event("quiz_completed", f"character:{character}")
        return {**character_info(character, lang_of(request)), "scores": points}

    @app.post("/api/quiz/preview")
    def quiz_preview(body: QuizPreviewIn, request: Request):
        """Watermarked character sticker preview for anonymous quiz takers (nothing stored)."""
        rate_limit(request, "quiz-preview", 30, 60)
        name = normalize_name(body.name)
        svg = build_sticker(body.template_id, name, character_of(body.answers), lang_of(request),
                            transparent=body.transparent, show_traits=body.show_traits,
                            watermark="PREVIEW", size_px=480)
        return {"svg": svg}

    @app.post("/api/events")
    def track_event(body: EventIn, request: Request):
        rate_limit(request, "events", 30, 600)
        svc.count_event(body.event)
        return {"ok": True}

    @app.get("/api/characters/{character}.svg")
    def character_image(character: str):
        if character not in CHARACTER_ORDER:
            raise ServiceError("Unknown character.", 404)
        return Response(character_svg(character), media_type="image/svg+xml",
                        headers={"Cache-Control": "public, max-age=3600"})

    # ------------------------------------------------------------- admin API
    @app.post("/api/admin/login")
    def admin_login(body: LoginIn, request: Request, response: Response):
        ip = client_ip(request)
        user_key = f"login-user:{body.username.strip().lower()[:40]}"
        if not limiter.hit(f"login-ip:{ip}", 10, 900) or limiter.is_limited(user_key, 5, 900):
            raise ServiceError("Too many login attempts. Try again in 15 minutes.", 429)
        result = svc.authenticate(body.username.strip(), body.password, ip_hash(request))
        if result is None:
            limiter.record(user_key)
            raise ServiceError("Invalid username or password.", 401)
        token, csrf, admin = result
        response.set_cookie(SESSION_COOKIE, token, max_age=settings.session_hours * 3600,
                            httponly=True, secure=settings.cookie_secure, samesite="strict", path="/")
        return {"username": admin["username"], "csrf_token": csrf}

    @app.post("/api/admin/logout")
    def admin_logout(request: Request, response: Response, admin: dict = Depends(require_admin)):
        svc.logout(admin["session_id"], admin["admin_id"], ip_hash(request))
        response.delete_cookie(SESSION_COOKIE, path="/", secure=settings.cookie_secure,
                               httponly=True, samesite="strict")
        return {"ok": True}

    @app.get("/api/admin/me")
    def admin_me(admin: dict = Depends(require_admin)):
        return {"username": admin["username"], "csrf_token": admin["csrf_token"]}

    @app.get("/api/admin/requests")
    def admin_requests(status: StatusFilter = "ALL", admin: dict = Depends(require_admin)):
        items = svc.list_requests(None if status == "ALL" else status)
        return {"items": items, "status_messages": STATUS_MESSAGES}

    @app.post("/api/admin/requests/{request_id}/approve")
    def admin_approve(request_id: int, body: ApproveIn, request: Request,
                      admin: dict = Depends(require_admin)):
        row = svc.approve(request_id, admin["admin_id"], body.transaction_reference, ip_hash(request))
        return admin_view(row)

    @app.post("/api/admin/requests/{request_id}/reject")
    def admin_reject(request_id: int, body: RejectIn, request: Request,
                     admin: dict = Depends(require_admin)):
        row = svc.reject(request_id, admin["admin_id"], body.reason, ip_hash(request))
        return admin_view(row)

    @app.post("/api/admin/requests/{request_id}/notes")
    def admin_note(request_id: int, body: NoteIn, request: Request,
                   admin: dict = Depends(require_admin)):
        row = svc.add_note(request_id, admin["admin_id"], admin["username"], body.note, ip_hash(request))
        return admin_view(row)

    @app.get("/api/admin/settings")
    def admin_get_settings(admin: dict = Depends(require_admin)):
        return svc.get_payment_settings().as_dict()

    @app.patch("/api/admin/settings")
    def admin_update_settings(body: SettingsIn, request: Request, admin: dict = Depends(require_admin)):
        pay = svc.update_payment_settings(admin["admin_id"], body.model_dump(exclude_none=True),
                                          ip_hash(request))
        return pay.as_dict()

    @app.get("/api/admin/stats")
    def admin_stats(admin: dict = Depends(require_admin)):
        return svc.analytics_summary()

    @app.get("/api/admin/audit")
    def admin_audit(limit: int = Query(default=100, ge=1, le=500), admin: dict = Depends(require_admin)):
        return {"items": svc.recent_audit(limit)}

    return app


def get_app() -> FastAPI:  # uvicorn factory: uvicorn app.main:get_app --factory
    return create_app()
