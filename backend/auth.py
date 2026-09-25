"""Authentication: Google OAuth + signed-cookie sessions + local dev login.

Google sign-in uses OAuth 2.0 (authorization-code flow) against
accounts.google.com. When GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not
configured, the app falls back to a local demo login so the product is fully
usable offline; both paths create the same user records and sessions.

Sessions are opaque random tokens stored server-side (sessions table) and
carried in an HttpOnly cookie. No third-party dependencies are added.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import secrets
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from fastapi import APIRouter, Cookie, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

from backend.config import settings
from backend.database import db, utcnow

logger = logging.getLogger("vault.auth")

router = APIRouter(tags=["auth"])

SESSION_COOKIE = "nexstore_session"
SESSION_TTL_DAYS = 7

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Created at startup so the demo login works without any configuration.
DEMO_EMAIL = "demo@nexstore.local"
DEMO_PASSWORD_HASH = hashlib.sha256(b"nexstore").hexdigest()  # demo / nexstore


def _hash_password(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()


# -- database schema (users, oauth_states, sessions) ----------------------------
AUTH_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id TEXT PRIMARY KEY,
    email TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    picture TEXT,
    provider TEXT NOT NULL DEFAULT 'local',
    provider_sub TEXT,
    password_salt TEXT,
    password_hash TEXT,
    created_at TEXT NOT NULL,
    last_login TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_states (
    state TEXT PRIMARY KEY,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def init_auth_schema() -> None:
    with db.write() as conn:
        conn.executescript(AUTH_SCHEMA)
        now = utcnow()
        existing = conn.execute(
            "SELECT user_id FROM users WHERE email=?", (DEMO_EMAIL,)
        ).fetchone()
        if not existing:
            salt = secrets.token_hex(16)
            conn.execute(
                "INSERT INTO users(user_id, email, name, picture, provider, provider_sub, "
                "password_salt, password_hash, created_at, last_login) "
                "VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f"user_{secrets.token_hex(10)}", DEMO_EMAIL, "Demo User", None,
                 "local", None, salt, _hash_password("nexstore", salt), now, now),
            )


def _expiry(days: int = SESSION_TTL_DAYS) -> str:
    from datetime import timedelta

    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


# -- session helpers -------------------------------------------------------------
def create_session(user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    with db.write() as conn:
        conn.execute(
            "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES(?,?,?,?)",
            (token, user_id, utcnow(), _expiry()),
        )
    return token


def _user_for_session(token: str | None) -> dict | None:
    if not token:
        return None
    row = db.query_one(
        "SELECT u.* FROM sessions s JOIN users u ON u.user_id=s.user_id "
        "WHERE s.token=? AND s.expires_at > ?",
        (token, utcnow()),
    )
    return row


def destroy_session(token: str | None) -> None:
    if token:
        with db.write() as conn:
            conn.execute("DELETE FROM sessions WHERE token=?", (token,))


def set_session_cookie(response: JSONResponse | RedirectResponse, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_TTL_DAYS * 86400,
        httponly=True, samesite="lax", path="/",
    )


def clear_session_cookie(response: JSONResponse | RedirectResponse) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# -- user upsert -------------------------------------------------------------------
def upsert_user(*, email: str, name: str, picture: str | None,
                provider: str, provider_sub: str | None) -> dict:
    existing = db.query_one("SELECT * FROM users WHERE email=?", (email,))
    now = utcnow()
    if existing:
        with db.write() as conn:
            conn.execute(
                "UPDATE users SET name=?, picture=?, last_login=? WHERE user_id=?",
                (name or existing["name"], picture or existing["picture"], now, existing["user_id"]),
            )
        return db.query_one("SELECT * FROM users WHERE email=?", (email,))
    user_id = f"user_{secrets.token_hex(10)}"
    with db.write() as conn:
        conn.execute(
            "INSERT INTO users(user_id, email, name, picture, provider, provider_sub, "
            "created_at, last_login) VALUES(?,?,?,?,?,?,?,?)",
            (user_id, email, name or email.split("@")[0], picture, provider, provider_sub, now, now),
        )
    return db.query_one("SELECT * FROM users WHERE user_id=?", (user_id,))


def public_user(user: dict) -> dict:
    return {
        "user_id": user["user_id"],
        "email": user["email"],
        "name": user["name"],
        "picture": user["picture"],
        "provider": user["provider"],
        "created_at": user["created_at"],
        "last_login": user["last_login"],
    }


# -- Google OAuth helpers ------------------------------------------------------------
def google_configured() -> bool:
    return bool(os_env("GOOGLE_CLIENT_ID") and os_env("GOOGLE_CLIENT_SECRET"))


def os_env(key: str) -> str | None:
    import os

    return os.environ.get(key) or None


def redirect_uri(request: Request) -> str:
    configured = os_env("GOOGLE_REDIRECT_URI")
    if configured:
        return configured
    return f"{request.url.scheme}://{request.url.netloc}/auth/google/callback"


# -- endpoints ---------------------------------------------------------------------
@router.get("/api/auth/me")
def me(nexstore_session: str | None = Cookie(default=None)) -> dict:
    user = _user_for_session(nexstore_session)
    import os
    supabase_enabled = bool(os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_ANON_KEY"))
    return {
        "authenticated": user is not None,
        "user": public_user(user) if user else None,
        "google_enabled": google_configured(),
        "supabase_enabled": supabase_enabled,
    }


@router.get("/auth/google/login")
def google_login(request: Request):
    if not google_configured():
        raise HTTPException(status_code=501, detail="Google OAuth not configured")
    state = secrets.token_urlsafe(24)
    with db.write() as conn:
        conn.execute("INSERT INTO oauth_states(state, created_at) VALUES(?,?)", (state, utcnow()))
    params = urllib.parse.urlencode({
        "client_id": os_env("GOOGLE_CLIENT_ID"),
        "redirect_uri": redirect_uri(request),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    })
    return RedirectResponse(f"{GOOGLE_AUTH_URL}?{params}")


@router.get("/auth/google/callback")
def google_callback(request: Request, code: str | None = None, state: str | None = None,
                    error: str | None = None):
    if error:
        return RedirectResponse("/?auth_error=" + urllib.parse.quote(error))
    if not code or not state:
        return RedirectResponse("/?auth_error=missing_code")
    row = db.query_one("SELECT state FROM oauth_states WHERE state=?", (state,))
    if not row:
        return RedirectResponse("/?auth_error=bad_state")
    with db.write() as conn:
        conn.execute("DELETE FROM oauth_states WHERE state=?", (state,))

    try:
        token_resp = _google_token(code, request)
        access_token = token_resp["access_token"]
        userinfo = _google_userinfo(access_token)
    except Exception as exc:  # noqa: BLE001 — surface a friendly redirect
        logger.warning("Google OAuth failed: %s", exc)
        return RedirectResponse("/?auth_error=oauth_failed")

    user = upsert_user(
        email=userinfo["email"], name=userinfo.get("name") or userinfo["email"],
        picture=userinfo.get("picture"), provider="google",
        provider_sub=userinfo.get("sub"),
    )
    token = create_session(user["user_id"])
    resp = RedirectResponse("/")
    set_session_cookie(resp, token)
    return resp


def _google_token(code: str, request: Request) -> dict:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": os_env("GOOGLE_CLIENT_ID"),
        "client_secret": os_env("GOOGLE_CLIENT_SECRET"),
        "redirect_uri": redirect_uri(request),
        "grant_type": "authorization_code",
    }).encode()
    req = urllib.request.Request(GOOGLE_TOKEN_URL, data=data, method="POST")
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json

        return json.loads(resp.read().decode())


def _google_userinfo(access_token: str) -> dict:
    req = urllib.request.Request(
        GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {access_token}"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json

        return json.loads(resp.read().decode())


@router.post("/api/auth/dev-login")
def dev_login(payload: dict):
    """Local demo login (email + password) — always available as fallback."""
    email = (payload.get("email") or "").strip().lower()
    password = payload.get("password") or ""
    row = db.query_one("SELECT * FROM users WHERE email=?", (email,))
    if not row or not row.get("password_hash") or row["password_hash"] != _hash_password(password, row["password_salt"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")
    with db.write() as conn:
        conn.execute("UPDATE users SET last_login=? WHERE user_id=?", (utcnow(), row["user_id"]))
    token = create_session(row["user_id"])
    resp = JSONResponse({"authenticated": True, "user": public_user(row)})
    set_session_cookie(resp, token)
    return resp


@router.post("/api/auth/logout")
def logout(nexstore_session: str | None = Cookie(default=None)):
    destroy_session(nexstore_session)
    resp = JSONResponse({"ok": True})
    clear_session_cookie(resp)
    return resp
