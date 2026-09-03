"""Shared helpers every page uses: load settings, get/require an
authenticated + active Supabase session (with the signed-in user's
profile), manage the user's own Gemini API key (session-only, never
written to Supabase), and cache projects/hackathons for the duration of
the Streamlit session so switching between pages doesn't refetch on every
rerun.
"""
from __future__ import annotations

from typing import Any

import streamlit as st

from services.auth_service import (
    AccountInactiveError,
    Profile,
    get_current_profile,
    sign_in_username,
)
from services.auth_service import sign_out as _auth_sign_out
from services.config import Settings, load_settings
from services.hackathons_service import list_active_hackathons
from services.projects_service import list_projects
from services.supabase_client import get_client, is_authenticated

DATA_TTL_SECONDS = 30
GEMINI_KEY_SESSION_KEY = "devvault_gemini_api_key"
PROFILE_SESSION_KEY = "devvault_profile"


def get_settings() -> Settings:
    """Loads env-based settings, then layers the user's own session-only
    Gemini key on top (see save_gemini_key / clear_gemini_key below). The
    Gemini key never comes from .env or Supabase — only from what the user
    typed into Settings for this browser session."""
    settings = load_settings()
    session_key = st.session_state.get(GEMINI_KEY_SESSION_KEY)
    overrides = st.session_state.get("settings_overrides") or {}

    return Settings(
        supabase_url=overrides.get("supabase_url") or settings.supabase_url,
        supabase_anon_key=overrides.get("supabase_anon_key") or settings.supabase_anon_key,
        supabase_service_role_key=settings.supabase_service_role_key,
        gemini_api_key=session_key or None,
        gemini_model=overrides.get("gemini_model") or settings.gemini_model,
    )


# --- Gemini key management (session-state only, never persisted to Supabase) ---


def save_gemini_key(api_key: str) -> None:
    st.session_state[GEMINI_KEY_SESSION_KEY] = api_key.strip()
    st.session_state.pop("gemini_client_cache_token", None)


def clear_gemini_key() -> None:
    st.session_state.pop(GEMINI_KEY_SESSION_KEY, None)


def is_gemini_key_set() -> bool:
    return bool(st.session_state.get(GEMINI_KEY_SESSION_KEY))


# --- Auth ------------------------------------------------------------------


def require_auth() -> tuple[Settings, Any, Profile] | None:
    """Renders the username/password login form and stops page execution
    until the user is signed in with an ACTIVE profile. Returns
    (settings, supabase_client, profile) once authenticated. There is no
    sign-up path anywhere in this app — only an admin creates accounts
    (see Settings -> User Management / services/admin_service.py)."""
    settings = get_settings()

    if not settings.supabase_configured:
        st.error(
            "Supabase isn't configured. Set SUPABASE_URL and SUPABASE_ANON_KEY as "
            "environment variables before running the app (see .env.example)."
        )
        st.stop()

    client = get_client(settings)

    if not is_authenticated(client):
        st.session_state.pop(PROFILE_SESSION_KEY, None)
        _render_login(client)
        st.stop()

    profile = st.session_state.get(PROFILE_SESSION_KEY)
    if profile is None:
        profile = get_current_profile(client)
        if profile is None or not profile.is_active:
            # A valid Supabase session but no visible/active profile —
            # treat exactly like a deactivated account (RLS already
            # enforces this for every real read/write; this just gives a
            # clear message instead of a confusing half-working UI).
            from services.supabase_client import sign_out as _raw_sign_out

            _raw_sign_out(client)
            st.session_state.pop(PROFILE_SESSION_KEY, None)
            st.error("This account is deactivated or no longer exists. Contact your DevVault administrator.")
            st.stop()
        st.session_state[PROFILE_SESSION_KEY] = profile

    return settings, client, profile


def get_current_user_id(client: Any) -> str:
    user = client.auth.get_user()
    if not user or not user.user:
        raise RuntimeError("Not authenticated")
    return user.user.id


def sign_out_current_user(client: Any) -> None:
    _auth_sign_out(client)
    st.session_state.pop(PROFILE_SESSION_KEY, None)


def _render_login(client: Any) -> None:
    st.markdown("# DevVault")
    st.caption("Sign in to continue. Accounts are created by your administrator only.")

    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Login", width="stretch")

        if submitted:
            if not username.strip() or not password:
                st.error("Enter both a username and password.")
            else:
                try:
                    profile = sign_in_username(client, username, password)
                    st.session_state[PROFILE_SESSION_KEY] = profile
                    st.rerun()
                except AccountInactiveError as exc:
                    st.error(str(exc))
                except Exception:  # noqa: BLE001
                    # Never surface raw Supabase Auth error text (it can
                    # reveal whether a username exists) — one generic
                    # message for any bad-credentials case.
                    st.error("Invalid username or password.")


# --- Cached data reads ----------------------------------------------------


@st.cache_data(ttl=DATA_TTL_SECONDS, show_spinner=False)
def _cached_projects(_client: Any, cache_key: str) -> list[dict[str, Any]]:
    return list_projects(_client)


@st.cache_data(ttl=DATA_TTL_SECONDS, show_spinner=False)
def _cached_hackathons(_client: Any, cache_key: str) -> list[dict[str, Any]]:
    return list_active_hackathons(_client)


def get_projects(client: Any, force_refresh: bool = False) -> list[dict[str, Any]]:
    # Projects are global/shared now (same rows for every active user), so
    # a single cache key is enough.
    if force_refresh:
        _cached_projects.clear()
    return _cached_projects(client, "global")


def get_active_hackathons(client: Any, force_refresh: bool = False) -> list[dict[str, Any]]:
    if force_refresh:
        _cached_hackathons.clear()
    return _cached_hackathons(client, "global")
