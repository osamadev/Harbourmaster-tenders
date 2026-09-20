"""Per-session Gemini API key resolution (context/thread-safe).

One process serves every Streamlit session, so a user-supplied (guest) key must never
be written to ``os.environ`` or ``config.GEMINI_API_KEY`` — that would leak across users.
Instead the UI sets a per-session override in a :class:`contextvars.ContextVar`, which the
LLM clients read at call time. Registered/env users leave the override unset and fall back
to the server's configured key.
"""

from __future__ import annotations

import contextvars

from openai import OpenAI

# None -> use the server/env key; a string -> a guest session's own key.
_session_key: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "session_gemini_key", default=None
)

# Cache OpenAI clients by (base_url, api_key) so we don't rebuild one per call.
_clients: dict[tuple[str, str], OpenAI] = {}


def set_session_gemini_key(key: str | None) -> None:
    """Set the current session's Gemini key override (or clear it with a falsy value)."""
    _session_key.set((key or "").strip() or None)


def reset_session_gemini_key() -> None:
    """Clear the override so resolution falls back to the env/config key."""
    _session_key.set(None)


def current_session_override() -> str | None:
    """Return the active per-session override, if any (None means 'use env key')."""
    return _session_key.get()


def resolve_gemini_key() -> str:
    """Return the API key for the current context: session override else env/config."""
    override = _session_key.get()
    if override:
        return override
    # Imported lazily to avoid an import cycle (config -> settings -> ...).
    from harbourmaster import config

    return str(getattr(config, "GEMINI_API_KEY", "") or "")


def client_for_key(base_url: str, api_key: str) -> OpenAI:
    """Return a cached OpenAI client for the given base_url + api_key pair."""
    cache_key = (base_url or "", api_key or "")
    client = _clients.get(cache_key)
    if client is None:
        client = OpenAI(base_url=base_url, api_key=api_key)
        _clients[cache_key] = client
    return client
