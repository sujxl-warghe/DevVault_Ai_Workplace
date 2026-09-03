"""Central place that reads configuration from environment variables.

Values can come from a real `.env` file (loaded via python-dotenv, for local
`streamlit run` usage) or from `st.secrets` / actual environment variables
when deployed (e.g. Streamlit Community Cloud). We check both so the same
code works in either setup, matching the Settings page's "read configuration
from environment variables" requirement while still letting the Settings
page display (and, for this session, temporarily override) the values.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DEFAULT_GEMINI_MODEL = "gemini-3.5-flash"


def _get(key: str, default: str | None = None) -> str | None:
    # Streamlit secrets (if running under `streamlit run` with a secrets.toml)
    # take precedence when present, then fall back to plain env vars.
    try:
        import streamlit as st  # imported lazily to keep this module usable outside Streamlit too

        if key in st.secrets:
            return str(st.secrets[key])
    except Exception:
        pass
    return os.environ.get(key, default)


@dataclass
class Settings:
    supabase_url: str | None
    supabase_anon_key: str | None
    # Server-side only. Read from the environment, never shown in any UI,
    # never sent to the browser (Streamlit scripts execute entirely on the
    # server; this value never appears in a websocket frame or HTML
    # response). Used exclusively by services/admin_service.py for the
    # handful of operations the anon key + RLS cannot do on someone else's
    # behalf: creating a user, resetting another user's password, and
    # deleting a user's auth record.
    supabase_service_role_key: str | None
    gemini_api_key: str | None
    gemini_model: str

    @property
    def supabase_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_anon_key)

    @property
    def admin_api_configured(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_role_key)

    @property
    def gemini_configured(self) -> bool:
        return bool(self.gemini_api_key)


def load_settings() -> Settings:
    return Settings(
        supabase_url=_get("SUPABASE_URL"),
        supabase_anon_key=_get("SUPABASE_ANON_KEY"),
        supabase_service_role_key=_get("SUPABASE_SERVICE_ROLE_KEY"),
        # Deliberately never read from the environment or st.secrets: the
        # Gemini key is user-entered, per-session, via the Settings page
        # only (see services/state.py). This keeps the architecture honest
        # even if a deployer sets GEMINI_API_KEY anyway.
        gemini_api_key=None,
        gemini_model=_get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL) or DEFAULT_GEMINI_MODEL,
    )
