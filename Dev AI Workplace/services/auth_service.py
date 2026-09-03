"""Username-based login on top of Supabase Auth.

Supabase Auth's built-in flows are email/password. To give users a plain
username + password login screen with zero public registration, each
account's real Supabase Auth email is a synthetic, reserved address the
user never sees or types: `{username}@devvault.internal`. The `profiles`
table (see supabase/migrations/0008_profiles_and_roles.sql) carries the
actual username, role, and active/inactive status.

This module never handles raw passwords beyond passing them straight
through to Supabase Auth's own sign-in call — passwords are bcrypt-hashed
by GoTrue and stored only in the protected `auth.users` table, never
touched or duplicated here.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import streamlit as st
from supabase import Client

from services.supabase_client import sign_in as _raw_sign_in

DEVVAULT_EMAIL_DOMAIN = "devvault.internal"
USERNAME_RE = re.compile(r"^[a-z0-9_.-]{3,32}$")


class InvalidUsernameError(Exception):
    pass


class AccountInactiveError(Exception):
    """Raised when the credentials are valid but the account has been
    deactivated by an admin."""


@dataclass
class Profile:
    id: str
    username: str
    role: str
    status: str

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_active(self) -> bool:
        return self.status == "active"


def normalize_username(username: str) -> str:
    return username.strip().lower()


def validate_username(username: str) -> str:
    normalized = normalize_username(username)
    if not USERNAME_RE.match(normalized):
        raise InvalidUsernameError(
            "Usernames must be 3-32 characters: lowercase letters, numbers, '.', '_', or '-' only."
        )
    return normalized


def username_to_email(username: str) -> str:
    """Deterministic, reserved synthetic address — never emailed, never
    shown to the user, exists only so Supabase Auth (which requires an
    email-shaped identifier) has something to key on."""
    return f"{normalize_username(username)}@{DEVVAULT_EMAIL_DOMAIN}"


def sign_in_username(client: Client, username: str, password: str) -> Profile:
    """Signs in with username+password and enforces that the account is
    active. Raises AccountInactiveError (and immediately signs back out)
    if the credentials are valid but the account was deactivated — RLS
    would block nearly everything for such a user anyway, but we also want
    a clear, specific message here rather than a confusing empty app."""
    email = username_to_email(username)
    _raw_sign_in(client, email, password)

    profile = get_current_profile(client)
    if profile is None or not profile.is_active:
        sign_out(client)
        raise AccountInactiveError(
            "This account is deactivated. Contact your DevVault administrator."
        )
    return profile


def sign_out(client: Client) -> None:
    from services.supabase_client import sign_out as _raw_sign_out

    _raw_sign_out(client)
    st.session_state.pop("devvault_profile_cache", None)


def get_current_profile(client: Client) -> Profile | None:
    """Fetches the signed-in user's own profile row. Returns None if
    unauthenticated, or if RLS finds no visible row (which happens for a
    deactivated account, since profiles_select_active requires
    is_active_user() — see 0009_profiles_rls.sql)."""
    try:
        user = client.auth.get_user()
        if not user or not user.user:
            return None
        uid = user.user.id
    except Exception:
        return None

    try:
        response = (
            client.table("profiles")
            .select("id, username, role, status")
            .eq("id", uid)
            .maybe_single()
            .execute()
        )
    except Exception:
        return None

    if not response or not response.data:
        return None

    row: dict[str, Any] = response.data
    return Profile(id=row["id"], username=row["username"], role=row["role"], status=row["status"])
