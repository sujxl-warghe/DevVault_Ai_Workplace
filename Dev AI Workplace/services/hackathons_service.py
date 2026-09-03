"""Read/write access to the global `hackathons` table (see
supabase/migrations/0005_global_hackathons.sql, extended by
0011_hackathons_minimal_fields_admin_rls.sql).

Hackathons are global/shared: every active authenticated user reads the
same rows (RLS: hackathons_select_active), but only an admin can INSERT,
UPDATE, or DELETE directly (RLS: hackathons_*_admin_only). Normal users
add hackathons via hackathon_submission_requests instead; approving a
request calls create_or_update_hackathon() below as the admin.

This is entirely separate from the Chrome Extension's `joined_hackathons`
table — see 0005_global_hackathons.sql for why they're deliberately not
the same table. Nothing here is written to or read by the extension.

`registration_link` is the primary de-duplication key for the current
minimal form (Name, Template/Photo, Starting Time, Ending Time,
Registration Link, Prize Pool). When it's provided, adding the "same"
hackathon again updates the existing row instead of creating a duplicate.
When it's not provided, there's no reliable identity to dedupe on, so a
plain insert is used — this matches the spec's own "when possible" hedge.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from supabase import Client

HACKATHON_COLUMNS = (
    "id, created_by, name, template_photo, registration_link, prize_amount, "
    "start_at, end_at, devpost_url, description, themes, tracks, sponsor_apis, "
    "prizes, registration_deadline, created_at, updated_at"
)


def list_active_hackathons(client: Client) -> list[dict[str, Any]]:
    """All hackathons where end_at > NOW() — matches both what the UI
    should show as 'active' and what the scheduled cleanup job (pg_cron)
    guarantees will eventually be deleted once expired, so a hackathon is
    never shown as active past its own end date even if cleanup hasn't
    run yet."""
    now_iso = datetime.now(timezone.utc).isoformat()
    response = (
        client.table("hackathons")
        .select(HACKATHON_COLUMNS)
        .gt("end_at", now_iso)
        .order("end_at", desc=False)
        .execute()
    )
    return response.data or []


def create_or_update_hackathon(client: Client, hackathon: dict[str, Any], user_id: str) -> dict[str, Any]:
    """Upserts on registration_link when provided (the current dedup key);
    otherwise inserts a new row, since there's nothing reliable to key an
    upsert on. `created_by` is audit-only per the global/shared model —
    any admin can manage any hackathon regardless of who added it."""
    payload = {**hackathon, "created_by": user_id}
    table = client.table("hackathons")

    if payload.get("registration_link"):
        response = (
            table.upsert(payload, on_conflict="registration_link").select(HACKATHON_COLUMNS).execute()
        )
    else:
        response = table.insert(payload).select(HACKATHON_COLUMNS).execute()

    if not response.data:
        raise RuntimeError("Hackathon save did not return the saved row.")
    return response.data[0]


def delete_hackathon(client: Client, hackathon_id: str) -> None:
    client.table("hackathons").delete().eq("id", hackathon_id).execute()


def find_hackathon_by_name(hackathons: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    needle = name.strip().lower()
    if not needle:
        return None
    for h in hackathons:
        title = (h.get("name") or "").lower()
        if needle == title or needle in title or title in needle:
            return h
    return None
