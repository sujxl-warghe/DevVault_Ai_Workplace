"""Read/write access to the `projects` table.

Projects are now global/shared: every active authenticated user can read
every row (RLS: projects_select_active), but only an admin can INSERT,
UPDATE, or DELETE directly (RLS: projects_*_admin_only — see
supabase/migrations/0010_projects_global_admin_rls.sql). Normal users add
projects via project_submission_requests instead; approving a request
calls create_project() below as the admin, which RLS already permits.

The Chrome Extension also writes to this same table (with its own
title/problem_solved/description/tags/github_url/demo_url/devpost_url
shape) when the browser is signed into an admin account — see the schema
migration's comments for why that's the deliberate consequence of "normal
users cannot directly insert projects." The minimal Streamlit form only
surfaces Title/Details/Repo Link/Live Link (mapped to
title/description/github_url/demo_url respectively); extension-only
columns like tags/problem_solved/devpost_url are left alone, not shown or
edited here, but never dropped from the schema.
"""
from __future__ import annotations

from typing import Any

from postgrest.exceptions import APIError as PostgrestAPIError
from supabase import Client

PROJECT_COLUMNS = (
    "id, title, problem_solved, description, tags, github_url, demo_url, "
    "devpost_url, created_at, updated_at"
)

# Postgres unique_violation SQLSTATE — raised when devpost_url already
# exists (either this user's own project or, in principle, the constraint
# itself, since devpost_url is globally unique per the extension's schema).
UNIQUE_VIOLATION_CODE = "23505"


class DuplicateProjectError(Exception):
    """Raised when a manually-entered devpost_url already has a saved project."""


def list_projects(client: Client) -> list[dict[str, Any]]:
    response = (
        client.table("projects")
        .select(PROJECT_COLUMNS)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def create_project(client: Client, project: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Manually adds a project. Raises DuplicateProjectError if devpost_url
    is already saved, rather than silently overwriting someone's data."""
    payload = {**project, "user_id": user_id}
    try:
        response = client.table("projects").insert(payload).select(PROJECT_COLUMNS).execute()
    except PostgrestAPIError as exc:
        if getattr(exc, "code", None) == UNIQUE_VIOLATION_CODE:
            raise DuplicateProjectError(
                "A project with this Devpost URL is already saved."
            ) from exc
        raise
    if not response.data:
        raise RuntimeError("Project save did not return the saved row.")
    return response.data[0]


def update_project(client: Client, project_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    response = (
        client.table("projects")
        .update(patch)
        .eq("id", project_id)
        .select(PROJECT_COLUMNS)
        .execute()
    )
    if not response.data:
        raise RuntimeError("Project update did not return the updated row.")
    return response.data[0]


def delete_project(client: Client, project_id: str) -> None:
    client.table("projects").delete().eq("id", project_id).execute()


def search_projects(projects: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return projects

    def matches(p: dict[str, Any]) -> bool:
        haystack_parts = [
            p.get("title") or "",
            p.get("problem_solved") or "",
            p.get("description") or "",
            " ".join(p.get("tags") or []),
        ]
        return q in " ".join(haystack_parts).lower()

    return [p for p in projects if matches(p)]


def find_projects_by_name(projects: list[dict[str, Any]], *names: str) -> list[dict[str, Any]]:
    """Case-insensitive exact/substring match on title — used by agents that
    need to look up specific projects the user named (e.g. "compare X and Y")."""
    results: list[dict[str, Any]] = []
    for name in names:
        needle = name.strip().lower()
        if not needle:
            continue
        for p in projects:
            title = (p.get("title") or "").lower()
            if needle == title or needle in title or title in needle:
                if p not in results:
                    results.append(p)
    return results
