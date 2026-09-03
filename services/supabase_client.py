"""Supabase client management for the Streamlit app.

This app reuses the exact same Supabase project as the Chrome Extension —
no database logic is duplicated here. Authentication is username-based
(see services/auth_service.py, which maps a username to a synthetic,
never-emailed address before calling Supabase Auth's normal email/password
sign-in). There is no public sign-up anywhere in this app; only an admin,
via services/admin_service.py's service-role client, can create accounts.
Row Level Security then scopes reads/writes per table — some tables are
global (projects, hackathons: every active user reads, only admins write),
others are private-per-row (each user's own submission/deletion requests).
"""
from __future__ import annotations

import streamlit as st
from supabase import Client, create_client

from services.config import Settings

SESSION_KEY = "devvault_supabase_session"


def get_client(settings: Settings) -> Client:
    """Returns a cached Supabase client for this browser session, restoring
    a previously signed-in session (if any) from st.session_state."""
    if "supabase_client" in st.session_state:
        return st.session_state["supabase_client"]

    if not settings.supabase_configured:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY "
            "(see .env.example) or fill them in on the Settings page."
        )

    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    st.session_state["supabase_client"] = client

    stored = st.session_state.get(SESSION_KEY)
    if stored:
        try:
            client.auth.set_session(stored["access_token"], stored["refresh_token"])
        except Exception:
            st.session_state.pop(SESSION_KEY, None)

    return client


def sign_in(client: Client, email: str, password: str) -> None:
    result = client.auth.sign_in_with_password({"email": email, "password": password})
    if not result.session:
        raise RuntimeError("Sign in failed: no session returned")
    st.session_state[SESSION_KEY] = {
        "access_token": result.session.access_token,
        "refresh_token": result.session.refresh_token,
    }


def sign_out(client: Client) -> None:
    try:
        client.auth.sign_out()
    finally:
        st.session_state.pop(SESSION_KEY, None)
        st.session_state.pop("supabase_client", None)


def is_authenticated(client: Client) -> bool:
    try:
        user = client.auth.get_user()
        return user is not None and user.user is not None
    except Exception:
        return False


def current_user_email(client: Client) -> str | None:
    try:
        user = client.auth.get_user()
        return user.user.email if user and user.user else None
    except Exception:
        return None
