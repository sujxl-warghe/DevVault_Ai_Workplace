"""Admin user management (create, activate/deactivate, reset password,
delete) — the only place in this app that touches the Supabase
service-role key.

Why a service-role key is needed here at all: a normal authenticated
session (even an admin's) can only manage its OWN Supabase Auth account
via the client SDK — creating a brand new auth user, forcing another
user's password, or deleting another user's auth record all require the
Auth Admin API, which only the service-role key can call. Everything else
in this app (reading/writing projects, hackathons, requests, and even
activating/deactivating a profile's `status` column) goes through the
normal anon-key client + RLS instead, precisely to keep the service-role
key's surface area as small as possible.

SECURITY: this key is read from a server-side environment variable
(SUPABASE_SERVICE_ROLE_KEY) and used only inside this module. It is never
stored in st.session_state, never displayed in any UI, never logged, and
never sent to the browser — Streamlit scripts execute entirely on the
server, so nothing here reaches the client beyond the ordinary rendered
result of each operation (e.g. "User created."). A fresh client is built
per call rather than cached, so there's no long-lived handle to leak.
"""
from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from typing import Any

from supabase import Client, create_client

from services.auth_service import username_to_email, validate_username
from services.config import Settings


class AdminAPINotConfiguredError(Exception):
    pass


class UsernameTakenError(Exception):
    pass


def _service_client(settings: Settings) -> Client:
    if not settings.admin_api_configured:
        raise AdminAPINotConfiguredError(
            "User management requires SUPABASE_SERVICE_ROLE_KEY to be set as a "
            "server-side environment variable. This is separate from the anon key "
            "and must never be entered in the app UI."
        )
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def generate_temp_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


@dataclass
class NewUserResult:
    user_id: str
    username: str
    temporary_password: str | None


def create_user(
    settings: Settings, username: str, password: str, role: str = "user"
) -> NewUserResult:
    """Creates a new Supabase Auth user + matching profile row. If the
    profile insert fails after the auth user was created, the auth user is
    deleted again so we never leave an orphaned account with no profile
    (which would otherwise be unreachable — RLS requires a profile row for
    almost everything)."""
    normalized = validate_username(username)
    if role not in ("admin", "user"):
        raise ValueError("role must be 'admin' or 'user'")

    admin_client = _service_client(settings)
    email = username_to_email(normalized)

    try:
        created = admin_client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": True,  # synthetic address; nothing to confirm
            }
        )
    except Exception as exc:  # noqa: BLE001
        message = str(exc).lower()
        if "already" in message or "duplicate" in message or "exists" in message:
            raise UsernameTakenError(f"Username '{normalized}' is already taken.") from exc
        raise

    user_id = created.user.id

    try:
        admin_client.table("profiles").insert(
            {"id": user_id, "username": normalized, "role": role, "status": "active"}
        ).execute()
    except Exception:
        # Compensating cleanup: don't leave an orphaned auth account with no
        # profile row behind.
        try:
            admin_client.auth.admin.delete_user(user_id)
        except Exception:
            pass
        raise

    return NewUserResult(user_id=user_id, username=normalized, temporary_password=password)


def reset_password(settings: Settings, user_id: str, new_password: str) -> None:
    admin_client = _service_client(settings)
    admin_client.auth.admin.update_user_by_id(user_id, {"password": new_password})


def delete_user(settings: Settings, user_id: str) -> None:
    """Deletes the Supabase Auth account. The profiles row is removed
    automatically (ON DELETE CASCADE from profiles.id -> auth.users.id)."""
    admin_client = _service_client(settings)
    admin_client.auth.admin.delete_user(user_id)


def set_user_status(anon_client: Client, user_id: str, status: str) -> None:
    """Activate/deactivate — this does NOT need the service-role client:
    the calling admin's own authenticated session can update profiles.status
    directly, since RLS's profiles_update_admin_only policy already allows
    it (see 0009_profiles_rls.sql). Kept in this module for discoverability
    alongside the other user-management operations."""
    if status not in ("active", "inactive"):
        raise ValueError("status must be 'active' or 'inactive'")
    anon_client.table("profiles").update({"status": status}).eq("id", user_id).execute()


def list_all_profiles(anon_client: Client) -> list[dict[str, Any]]:
    response = (
        anon_client.table("profiles")
        .select("id, username, role, status, created_at")
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []
