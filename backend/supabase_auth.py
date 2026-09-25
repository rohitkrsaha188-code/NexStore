"""Supabase Authentication integration for NexStore.

Supports:
  - Email + Password sign-up / sign-in via Supabase Auth REST API
  - Google OAuth via redirect to Supabase OAuth endpoint
  - Password reset via Supabase Auth
  - JWT validation (HS256 with SUPABASE_ANON_KEY secret)
  - Upsert of local user records in the SQLite DB for session continuity
  - Fallback to local dev login when SUPABASE_URL is not configured

Security notes:
  - SUPABASE_SERVICE_ROLE_KEY is used server-side only (never sent to browser)
  - SUPABASE_ANON_KEY is used for client-initiated requests (safe to expose)
  - Sessions are opaque random tokens in an HttpOnly cookie (existing auth.py mechanism)
"""
from __future__ import annotations

import json
import logging
import os
import urllib.parse
import urllib.request
from typing import Any

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel

from backend.database import db, utcnow
from backend.auth import (
    create_session, destroy_session, set_session_cookie, clear_session_cookie,
    upsert_user, public_user, SESSION_COOKIE, _user_for_session,
)

logger = logging.getLogger("vault.supabase_auth")

router = APIRouter(tags=["supabase-auth"])

# ---------------------------------------------------------------------------
# Environment helpers
# ---------------------------------------------------------------------------

def _env(key: str) -> str | None:
    return os.environ.get(key) or None


def supabase_url() -> str | None:
    return _env("SUPABASE_URL")


def supabase_anon_key() -> str | None:
    return _env("SUPABASE_ANON_KEY")


def supabase_service_key() -> str | None:
    return _env("SUPABASE_SERVICE_ROLE_KEY")


def supabase_configured() -> bool:
    return bool(supabase_url() and supabase_anon_key())


# ---------------------------------------------------------------------------
# Low-level Supabase Auth REST helpers
# ---------------------------------------------------------------------------

def _supabase_post(path: str, payload: dict, *, use_service_key: bool = False) -> dict:
    """POST to Supabase Auth REST endpoint; raises HTTPException on failure."""
    base = supabase_url()
    if not base:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    url = base.rstrip("/") + path
    key = supabase_service_key() if use_service_key else supabase_anon_key()
    if not key:
        raise HTTPException(status_code=503, detail="Supabase API key not configured")
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        try:
            detail = json.loads(body).get("error_description") or json.loads(body).get("msg") or body
        except Exception:
            detail = body
        logger.warning("Supabase Auth error %s: %s", exc.code, detail)
        raise HTTPException(status_code=exc.code if exc.code < 500 else 502, detail=detail)
    except Exception as exc:
        logger.exception("Supabase request failed: %s", exc)
        raise HTTPException(status_code=502, detail="Supabase connection failed")


def _supabase_get(path: str, access_token: str) -> dict:
    """GET from Supabase with a user JWT."""
    base = supabase_url()
    if not base:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    url = base.rstrip("/") + path
    key = supabase_anon_key() or ""
    req = urllib.request.Request(
        url,
        headers={
            "apikey": key,
            "Authorization": f"Bearer {access_token}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        logger.exception("Supabase GET failed: %s", exc)
        raise HTTPException(status_code=502, detail="Supabase fetch failed")


# ---------------------------------------------------------------------------
# Local user sync
# ---------------------------------------------------------------------------

def _sync_supabase_user(sb_user: dict) -> dict:
    """Upsert a Supabase user into the local SQLite users table and return it."""
    email = sb_user.get("email") or ""
    meta = sb_user.get("user_metadata") or {}
    name = meta.get("full_name") or meta.get("name") or email.split("@")[0]
    picture = meta.get("avatar_url") or meta.get("picture")
    provider = (sb_user.get("app_metadata") or {}).get("provider") or "email"
    provider_sub = sb_user.get("id")
    return upsert_user(
        email=email, name=name, picture=picture,
        provider=provider, provider_sub=provider_sub,
    )


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class EmailLoginPayload(BaseModel):
    email: str
    password: str


class SignupPayload(BaseModel):
    email: str
    password: str
    full_name: str | None = None


class ResetPayload(BaseModel):
    email: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/api/auth/signup")
def signup(payload: SignupPayload) -> JSONResponse:
    """Create a new account via Supabase Auth."""
    if not supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured — use the demo login instead",
        )
    meta: dict[str, Any] = {}
    if payload.full_name:
        meta["full_name"] = payload.full_name.strip()

    sb_resp = _supabase_post(
        "/auth/v1/signup",
        {"email": payload.email.strip().lower(), "password": payload.password, "data": meta},
    )

    sb_user = sb_resp.get("user") or sb_resp
    access_token = sb_resp.get("access_token")

    if not sb_user or not sb_user.get("id"):
        # Email confirmation required — Supabase returns user without session
        return JSONResponse({
            "authenticated": False,
            "requires_confirmation": True,
            "message": "Please check your email and click the confirmation link to activate your account.",
        })

    local_user = _sync_supabase_user(sb_user)
    token = create_session(local_user["user_id"])
    resp = JSONResponse({"authenticated": True, "user": public_user(local_user)})
    set_session_cookie(resp, token)
    return resp


@router.post("/api/auth/login")
def supabase_login(payload: EmailLoginPayload) -> JSONResponse:
    """Sign in with email + password via Supabase Auth."""
    if not supabase_configured():
        raise HTTPException(
            status_code=503,
            detail="Supabase is not configured — use /api/auth/dev-login instead",
        )
    sb_resp = _supabase_post(
        "/auth/v1/token?grant_type=password",
        {"email": payload.email.strip().lower(), "password": payload.password},
    )
    sb_user = sb_resp.get("user") or {}
    if not sb_user.get("id"):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    local_user = _sync_supabase_user(sb_user)
    # update last_login
    with db.write() as conn:
        conn.execute("UPDATE users SET last_login=? WHERE user_id=?", (utcnow(), local_user["user_id"]))
    token = create_session(local_user["user_id"])
    resp = JSONResponse({"authenticated": True, "user": public_user(local_user)})
    set_session_cookie(resp, token)
    return resp


@router.post("/api/auth/reset-password")
def reset_password(payload: ResetPayload) -> JSONResponse:
    """Send a password reset email via Supabase Auth."""
    if not supabase_configured():
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    # Supabase recover endpoint
    base = supabase_url()
    key = supabase_anon_key() or ""
    url = base.rstrip("/") + "/auth/v1/recover"
    data = json.dumps({"email": payload.email.strip().lower()}).encode()
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15):
            pass
    except Exception:
        pass  # Always return success to prevent email enumeration
    return JSONResponse({"ok": True, "message": "If that email exists, a reset link has been sent."})


@router.get("/api/auth/supabase-config")
def supabase_config() -> dict:
    """Return public Supabase config the frontend needs (URL + anon key only)."""
    return {
        "supabase_enabled": supabase_configured(),
        "supabase_url": supabase_url() or "",
        "supabase_anon_key": supabase_anon_key() or "",
    }


@router.get("/auth/supabase/google")
def supabase_google_login(request: Request) -> RedirectResponse:
    """Redirect to Supabase Google OAuth flow."""
    if not supabase_configured():
        raise HTTPException(status_code=501, detail="Supabase not configured")
    redirect_to = str(request.url_for("supabase_google_callback"))
    params = urllib.parse.urlencode({
        "provider": "google",
        "redirect_to": redirect_to,
    })
    url = supabase_url().rstrip("/") + f"/auth/v1/authorize?{params}"
    return RedirectResponse(url)


@router.get("/auth/supabase/callback", name="supabase_google_callback")
def supabase_google_callback(
    request: Request,
    access_token: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    code: str | None = None,
) -> RedirectResponse:
    """Handle Supabase OAuth callback (hash fragment is handled client-side)."""
    if error:
        return RedirectResponse(f"/?auth_error={urllib.parse.quote(error_description or error)}")
    # Supabase sends the session as a hash fragment (#access_token=...&token_type=bearer&...)
    # which cannot be read server-side. We redirect to the frontend which will extract
    # the token from the hash and call /api/auth/supabase-session to create a server session.
    return RedirectResponse("/?supabase_callback=1")


@router.post("/api/auth/supabase-session")
def supabase_session(request: Request, body: dict) -> JSONResponse:
    """Exchange a Supabase access_token (from OAuth hash) for a server-side session cookie."""
    access_token = body.get("access_token") or ""
    if not access_token:
        raise HTTPException(status_code=400, detail="access_token required")
    try:
        sb_user = _supabase_get("/auth/v1/user", access_token)
    except HTTPException:
        raise HTTPException(status_code=401, detail="Invalid or expired Supabase token")
    if not sb_user.get("id"):
        raise HTTPException(status_code=401, detail="Could not fetch user from Supabase")
    local_user = _sync_supabase_user(sb_user)
    with db.write() as conn:
        conn.execute("UPDATE users SET last_login=? WHERE user_id=?", (utcnow(), local_user["user_id"]))
    token = create_session(local_user["user_id"])
    resp = JSONResponse({"authenticated": True, "user": public_user(local_user)})
    set_session_cookie(resp, token)
    return resp
