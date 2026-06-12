"""Authentication gate: local + Google login, registration, and guest key access.

A single ``require_auth()`` is called at the top of every page. It enforces access,
wires the per-session Gemini key (env key for registered users, the user's own key for
guests), and notifies the owner by email on registration/login.

Controlled by ``AUTH_ENABLED`` — when false (local dev default) the gate is a no-op so
``make ui`` and smoke tests keep working with the env key.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import streamlit as st
import streamlit_authenticator as stauth
import yaml

from harbourmaster.notify import notify_event
from harbourmaster.runtime_config import RUNTIME_CONFIG_PATH
from harbourmaster.runtime_keys import reset_session_gemini_key, set_session_gemini_key

CREDENTIALS_PATH = RUNTIME_CONFIG_PATH.parent / "auth_credentials.yaml"


# --------------------------------------------------------------------------- env helpers
def _flag(name: str, default: str = "false") -> bool:
    return str(os.getenv(name, default)).strip().lower() in {"1", "true", "yes", "on"}


def auth_enabled() -> bool:
    return _flag("AUTH_ENABLED", "false")


def allow_anonymous() -> bool:
    return _flag("ALLOW_ANONYMOUS", "true")


def _oauth2_config() -> dict[str, Any] | None:
    cid = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    redirect = os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip()
    if not (cid and secret and redirect):
        return None
    return {"google": {"client_id": cid, "client_secret": secret, "redirect_uri": redirect}}


# --------------------------------------------------------------------------- credential store
def _load_credentials() -> dict[str, Any]:
    if CREDENTIALS_PATH.exists():
        try:
            data = yaml.safe_load(CREDENTIALS_PATH.read_text(encoding="utf-8")) or {}
            creds = data.get("credentials") if isinstance(data, dict) else None
            if isinstance(creds, dict) and isinstance(creds.get("usernames"), dict):
                return creds
        except Exception:  # noqa: BLE001
            pass
    return {"usernames": {}}


def _persist_credentials(creds: dict[str, Any]) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CREDENTIALS_PATH.with_suffix(".yaml.tmp")
    tmp.write_text(yaml.safe_dump({"credentials": creds}, sort_keys=False), encoding="utf-8")
    tmp.replace(CREDENTIALS_PATH)


def _get_authenticator() -> tuple[stauth.Authenticate, dict[str, Any]]:
    """Build (once per session) the Authenticate object and credentials dict."""
    if "_authenticator" not in st.session_state:
        creds = _load_credentials()
        authenticator = stauth.Authenticate(
            creds,
            os.getenv("AUTH_COOKIE_NAME", "harbourmaster_auth"),
            os.getenv("AUTH_COOKIE_KEY", "harbourmaster-dev-cookie-key"),
            float(os.getenv("AUTH_COOKIE_EXPIRY_DAYS", "7") or 7),
        )
        st.session_state["_authenticator"] = authenticator
        st.session_state["_auth_creds"] = creds
    return st.session_state["_authenticator"], st.session_state["_auth_creds"]


# --------------------------------------------------------------------------- identity helpers
def _current_email(creds: dict[str, Any] | None = None) -> str:
    creds = creds if creds is not None else st.session_state.get("_auth_creds", {})
    username = st.session_state.get("username") or ""
    info = (creds.get("usernames", {}) if isinstance(creds, dict) else {}).get(username, {})
    return str(info.get("email", "") or st.session_state.get("email", "") or "")


def current_user() -> dict[str, Any]:
    if not auth_enabled():
        return {"authenticated": True, "guest": False, "name": "local", "email": "", "admin": True}
    if st.session_state.get("authentication_status") is True:
        return {
            "authenticated": True,
            "guest": False,
            "name": st.session_state.get("name", ""),
            "email": _current_email(),
            "admin": is_admin(),
        }
    if st.session_state.get("guest_gemini_key"):
        return {"authenticated": False, "guest": True, "name": "Guest", "email": "", "admin": False}
    return {"authenticated": False, "guest": False, "name": "", "email": "", "admin": False}


def is_admin() -> bool:
    if not auth_enabled():
        return True  # local dev: unrestricted
    email = _current_email().lower()
    admins = [e.strip().lower() for e in os.getenv("ADMIN_EMAILS", "").split(",") if e.strip()]
    return bool(email) and email in admins


# --------------------------------------------------------------------------- the gate
def _clear_auth_cookie(authenticator: stauth.Authenticate) -> None:
    """Remove a stale/invalid auth cookie and reset session auth keys.

    Triggered when ``login()`` raises ``LoginError('User not authorized')`` — i.e. a
    cookie token references a username that is no longer in the credentials store.
    """
    try:
        authenticator.cookie_controller.delete_cookie()
    except Exception:  # noqa: BLE001
        pass
    for key in ("authentication_status", "name", "username"):
        st.session_state[key] = None


def _on_authenticated(creds: dict[str, Any]) -> None:
    """Registered/logged-in users use the env key; notify owner once per session."""
    reset_session_gemini_key()
    st.session_state["_auth_cookie_reset"] = False  # allow future stale-cookie recovery
    if not st.session_state.get("_notified_login"):
        notify_event(
            "login",
            name=st.session_state.get("name", ""),
            email=_current_email(creds),
            method="account",
        )
        st.session_state["_notified_login"] = True
        # Persist any OAuth/guest user just added in-memory so the cookie stays
        # valid on future sessions (local registrations are already persisted).
        try:
            _persist_credentials(creds)
        except Exception:  # noqa: BLE001
            pass


def _inject_login_css() -> None:
    """Hide the sidebar/chrome and style the centered login card (login screen only)."""
    st.markdown(
        """
        <style>
        [data-testid="stSidebar"],
        [data-testid="stSidebarCollapsedControl"],
        [data-testid="collapsedControl"],
        [data-testid="stSidebarCollapseButton"],
        [data-testid="stToolbar"] { display: none !important; }
        .hm-hero { display: none !important; }
        .block-container { padding-top: 2.4rem; }
        .hm-login-brand { text-align: center; margin: 0.2rem 0 1.1rem 0; }
        .hm-login-anchor { font-size: 2.6rem; line-height: 1; }
        .hm-login-name { font-size: 1.95rem; font-weight: 800; color: #0F2742; letter-spacing: -0.02em; }
        .hm-login-tag { color: #64748B; font-size: 0.95rem; margin-top: 0.15rem; }
        .hm-login-or {
            display: flex; align-items: center; text-align: center; color: #94A3B8;
            font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.1em; margin: 0.9rem 0;
        }
        .hm-login-or::before, .hm-login-or::after {
            content: ""; flex: 1; height: 1px; background: #E2E8F0; margin: 0 0.6rem;
        }
        [data-testid="stVerticalBlockBorderWrapper"] {
            border-radius: 16px; box-shadow: 0 10px 30px rgba(15,39,66,.08); background: #FFFFFF;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_google_button(authenticator: stauth.Authenticate) -> None:
    st.markdown('<div class="hm-login-or">or</div>', unsafe_allow_html=True)
    oauth2 = _oauth2_config()
    if oauth2:
        try:
            authenticator.experimental_guest_login(
                "Continue with Google",
                provider="google",
                oauth2=oauth2,
                location="main",
                use_container_width=True,
            )
        except Exception as exc:  # noqa: BLE001
            st.warning(f"Google login unavailable: {exc}")
    else:
        st.button(
            "Continue with Google",
            disabled=True,
            use_container_width=True,
            help="Set GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET and "
            "GOOGLE_OAUTH_REDIRECT_URI to enable Google sign-in.",
        )
        st.caption("Google sign-in is not configured.")


def _render_gate(authenticator: stauth.Authenticate, creds: dict[str, Any]) -> None:
    _inject_login_css()
    st.markdown(
        '<div class="hm-login-brand">'
        '<div class="hm-login-anchor">⚓</div>'
        '<div class="hm-login-name">Harbourmaster</div>'
        '<div class="hm-login-tag">Governed multi-agent tender &amp; contract review</div>'
        "</div>",
        unsafe_allow_html=True,
    )

    _, mid, _ = st.columns([1, 1.6, 1])
    with mid:
        with st.container(border=True):
            tab_login, tab_register, tab_guest = st.tabs(["Sign in", "Register", "Guest access"])

            with tab_login:
                try:
                    authenticator.login(
                        location="main",
                        key="LoginForm",
                        fields={"Form name": "Welcome back", "Login": "Sign in"},
                    )
                except Exception:  # noqa: BLE001 — stale cookie ("User not authorized")
                    _clear_auth_cookie(authenticator)
                    st.warning("Your previous session expired. Please reload the page to sign in.")
                if st.session_state.get("authentication_status") is False:
                    st.error("Username or password is incorrect.")
                _render_google_button(authenticator)

            with tab_register:
                st.caption("Create an account to run reviews on the server key.")
                try:
                    email, username, name = authenticator.register_user(
                        location="main",
                        captcha=False,
                        merge_username_email=False,
                        fields={"Form name": "Create account", "Register": "Create account"},
                    )
                    if email:
                        _persist_credentials(creds)
                        notify_event("registered", name=name, email=email, method="local")
                        st.success("Registration successful — switch to **Sign in**.")
                except Exception as exc:  # noqa: BLE001 (RegisterError and validation messages)
                    st.error(str(exc))

            with tab_guest:
                if not allow_anonymous():
                    st.info("Guest access is disabled. Please sign in or register.")
                else:
                    st.caption(
                        "Use Harbourmaster with your own Gemini API key — kept only for "
                        "this browser session and never stored."
                    )
                    key = st.text_input("Gemini API key", type="password", key="guest_key_input")
                    if st.button("Continue as guest", type="primary", use_container_width=True):
                        if key.strip():
                            st.session_state["guest_gemini_key"] = key.strip()
                            st.session_state["guest_mode"] = True
                            st.rerun()
                        else:
                            st.error("A Gemini API key is required to continue as a guest.")


def require_auth() -> None:
    """Gate the current page. Call immediately after ``init_page(...)``."""
    if not auth_enabled():
        reset_session_gemini_key()
        return

    authenticator, creds = _get_authenticator()
    # Pre-authenticate from the session cookie without drawing a form. A stale or
    # foreign cookie raises LoginError('User not authorized') — clear it and retry
    # once so the gate can render a clean login form instead of crashing.
    try:
        authenticator.login(location="unrendered")
    except Exception:  # noqa: BLE001
        _clear_auth_cookie(authenticator)
        if not st.session_state.get("_auth_cookie_reset"):
            st.session_state["_auth_cookie_reset"] = True
            st.rerun()

    if st.session_state.get("authentication_status") is True:
        _on_authenticated(creds)
        return

    if st.session_state.get("guest_gemini_key"):
        set_session_gemini_key(st.session_state["guest_gemini_key"])
        return

    _render_gate(authenticator, creds)
    st.stop()


# --------------------------------------------------------------------------- sidebar widget
def render_user_chip() -> None:
    """Sidebar 'signed in as … / Logout' (or guest badge). No-op when auth disabled."""
    if not auth_enabled():
        return
    if st.session_state.get("authentication_status") is True:
        st.caption(f"Signed in as **{st.session_state.get('name', 'user')}**")
        try:
            authenticator, _ = _get_authenticator()
            authenticator.logout("Logout", location="sidebar", key="logout_sidebar")
        except Exception:  # noqa: BLE001
            pass
    elif st.session_state.get("guest_gemini_key"):
        st.caption("Guest — using your own Gemini key")
        if st.button("Exit guest session", key="exit_guest", use_container_width=True):
            st.session_state.pop("guest_gemini_key", None)
            st.session_state.pop("guest_mode", None)
            reset_session_gemini_key()
            st.rerun()
