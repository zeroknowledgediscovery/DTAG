"""Optional shared-password protection for the DTAG web application.

Enabled only when ``DTAG_PASSWORD`` is set; otherwise every request passes
(local use is unchanged).

When enabled:

* every route except ``/api/health`` and the login endpoints requires either a
  valid login cookie or ``Authorization: Bearer <password>`` (for scripts);
* browsers without a valid cookie are redirected to ``/login``; API calls get
  ``401`` JSON;
* the cookie is ``<expiry>.<HMAC-SHA256>``, signed with ``DTAG_SESSION_SECRET``
  (random per process if unset, so a restart logs everyone out) and bound to
  the password, so changing the password invalidates all cookies;
* failed logins are throttled per client address.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import os
import secrets
import threading
import time
from collections import deque
from typing import Deque, Dict, Optional
from urllib.parse import parse_qs, quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

COOKIE = "dtag_auth"
PUBLIC_PATHS = {"/api/health", "/login", "/api/login", "/api/logout"}


class PasswordAuth:
    def __init__(
        self,
        password: str,
        secret: Optional[str] = None,
        hours: float = 12.0,
        max_failures: int = 10,
        window_seconds: float = 900.0,
    ):
        if not password:
            raise ValueError("password must be non-empty")
        self._password = password.encode("utf-8")
        self._secret = (secret.encode("utf-8") if secret else secrets.token_bytes(32))
        self._pw_tag = hashlib.sha256(self._password).hexdigest()[:16]
        self.max_age = int(hours * 3600)
        self.max_failures = max_failures
        self.window = window_seconds
        self._fails: Dict[str, Deque[float]] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> Optional["PasswordAuth"]:
        pw = os.environ.get("DTAG_PASSWORD", "")
        if not pw:
            return None
        return cls(
            pw,
            secret=os.environ.get("DTAG_SESSION_SECRET") or None,
            hours=float(os.environ.get("DTAG_AUTH_HOURS", "12")),
        )

    # -- credentials ----------------------------------------------------------

    def check_password(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate.encode("utf-8"), self._password)

    def _sign(self, expiry: int) -> str:
        msg = f"{expiry}|{self._pw_tag}".encode()
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    def make_cookie(self) -> str:
        expiry = int(time.time()) + self.max_age
        return f"{expiry}.{self._sign(expiry)}"

    def cookie_valid(self, value: Optional[str]) -> bool:
        if not value or "." not in value:
            return False
        exp_s, sig = value.split(".", 1)
        try:
            expiry = int(exp_s)
        except ValueError:
            return False
        if expiry < time.time():
            return False
        return hmac.compare_digest(sig, self._sign(expiry))

    def authorized(self, request: Request) -> bool:
        if self.cookie_valid(request.cookies.get(COOKIE)):
            return True
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return self.check_password(auth[7:].strip())
        return False

    # -- throttling -------------------------------------------------------------

    @staticmethod
    def client_id(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _recent_failures(self, who: str) -> Deque[float]:
        q = self._fails.setdefault(who, deque())
        cutoff = time.time() - self.window
        while q and q[0] < cutoff:
            q.popleft()
        return q

    def blocked(self, who: str) -> bool:
        with self._lock:
            return len(self._recent_failures(who)) >= self.max_failures

    def record_failure(self, who: str) -> None:
        with self._lock:
            self._recent_failures(who).append(time.time())

    def clear_failures(self, who: str) -> None:
        with self._lock:
            self._fails.pop(who, None)


def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def _safe_next(target: Optional[str]) -> str:
    # Only same-site relative paths (no scheme, no //host) to avoid open redirects.
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return "/"
    return target


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>DTAG sign in</title>
<style>
:root{{--bg:#f4f5f7;--panel:#fff;--border:#d9dde3;--text:#1c2330;--muted:#5b6573;--accent:#2f5d8a;--err:#a33a3a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12161c;--panel:#1a2029;--border:#2f3844;--text:#dde3ea;--muted:#9aa5b3;--accent:#7fb0e0;--err:#e58a8a}}}}
*{{box-sizing:border-box}}body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
background:var(--bg);color:var(--text);font:14px -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:16px}}
form{{background:var(--panel);border:1px solid var(--border);border-radius:8px;padding:24px;width:100%;max-width:340px}}
h1{{font-size:17px;margin:0 0 4px}}p{{color:var(--muted);margin:0 0 16px;font-size:13px}}
input{{width:100%;padding:8px 10px;border:1px solid var(--border);border-radius:5px;background:var(--bg);color:var(--text);font:inherit}}
button{{margin-top:12px;width:100%;padding:8px;border:0;border-radius:5px;background:var(--accent);color:#fff;font:inherit;font-weight:600;cursor:pointer}}
.err{{color:var(--err);font-size:13px;margin-top:10px}}
</style></head><body>
<form method="post" action="/api/login">
<h1>DTAG</h1><p>Digital Twin Anchored Generation · sign in</p>
<input type="hidden" name="next" value="{next}">
<input type="password" name="password" placeholder="Password" autofocus required autocomplete="current-password">
<button type="submit">Sign in</button>
{error}
</form></body></html>"""


def install(app: FastAPI, auth: Optional[PasswordAuth]) -> None:
    """Attach login routes and the access-control middleware (no-op if auth is None)."""
    app.state.auth = auth
    if auth is None:
        return

    @app.middleware("http")
    async def _require_login(request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or auth.authorized(request):
            return await call_next(request)
        if path.startswith("/api/") or path in ("/openapi.json",):
            return JSONResponse({"detail": "Authentication required"}, status_code=401,
                                headers={"WWW-Authenticate": "Bearer"})
        nxt = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        return RedirectResponse(f"/login?next={quote(nxt, safe='')}", status_code=303)

    @app.get("/login", include_in_schema=False)
    def login_page(next: str = "/", error: int = 0) -> HTMLResponse:
        msg = {1: "Incorrect password.", 2: "Too many attempts; try again later."}.get(error, "")
        body = LOGIN_PAGE.format(next=html.escape(_safe_next(next), quote=True),
                                 error=f'<div class="err">{msg}</div>' if msg else "")
        return HTMLResponse(body, headers={"Cache-Control": "no-store"})

    @app.post("/api/login", include_in_schema=False)
    async def login(request: Request) -> Response:
        who = auth.client_id(request)
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            data = await request.json()
            password, nxt, is_form = str(data.get("password", "")), "/", False
        else:
            # The login form posts application/x-www-form-urlencoded; parse it
            # with the standard library (no python-multipart dependency).
            raw = (await request.body())[:8192].decode("utf-8", "replace")
            form = {k: v[0] for k, v in parse_qs(raw, keep_blank_values=True).items()}
            password, nxt, is_form = form.get("password", ""), _safe_next(form.get("next", "/")), True
        if auth.blocked(who):
            if is_form:
                return RedirectResponse(f"/login?error=2&next={quote(nxt, safe='')}", status_code=303)
            return JSONResponse({"detail": "Too many failed attempts; try again later."}, status_code=429)
        if not auth.check_password(password):
            auth.record_failure(who)
            if is_form:
                return RedirectResponse(f"/login?error=1&next={quote(nxt, safe='')}", status_code=303)
            return JSONResponse({"detail": "Incorrect password."}, status_code=401)
        auth.clear_failures(who)
        resp: Response = RedirectResponse(nxt, status_code=303) if is_form else JSONResponse({"ok": True})
        resp.set_cookie(COOKIE, auth.make_cookie(), max_age=auth.max_age, httponly=True,
                        secure=_is_https(request), samesite="lax", path="/")
        return resp

    @app.api_route("/api/logout", methods=["GET", "POST"], include_in_schema=False)
    def logout() -> Response:
        resp = RedirectResponse("/login", status_code=303)
        resp.delete_cookie(COOKIE, path="/")
        return resp
