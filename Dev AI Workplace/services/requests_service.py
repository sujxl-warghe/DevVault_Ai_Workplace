"""Project/hackathon submission requests and project deletion requests.

Normal users create requests here (their own session, allowed by RLS).
Only an admin can approve/reject; approving is what performs the actual
write into `projects`/`hackathons` — done as the admin's own authenticated
call, which RLS already permits (see 0010/0011's admin-only policies).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from postgrest.exceptions import APIError as PostgrestAPIError
from supabase import Client

from services.hackathons_service import create_or_update_hackathon
from services.projects_service import create_project

REQUEST_STATUS_PENDING = "pending"
REQUEST_STATUS_APPROVED = "approved"
REQUEST_STATUS_REJECTED = "rejected"


class DuplicatePendingRequestError(Exception):
    """Raised when a user tries to submit a second pending deletion
    request for the same project (see the DB-level partial unique index)."""


# --- Project submission requests -----------------------------------------


def submit_project_request(
    client: Client, submitted_by: str, title: str, details: str | None, repo_link: str | None,
    live_link: str | None,
) -> dict[str, Any]:
    response = (
        client.table("project_submission_requests")
        .insert(
            {
                "submitted_by": submitted_by,
                "title": title,
                "details": details,
                "repo_link": repo_link,
                "live_link": live_link,
            }
        )
        .execute()
    )
    return response.data[0]


def list_own_project_requests(client: Client, user_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("project_submission_requests")
        .select("*")
        .eq("submitted_by", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def list_pending_project_requests(client: Client) -> list[dict[str, Any]]:
    response = (
        client.table("project_submission_requests")
        .select("*")
        .eq("status", REQUEST_STATUS_PENDING)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []


def approve_project_request(client: Client, request_id: str, admin_id: str) -> dict[str, Any]:
    request_row = (
        client.table("project_submission_requests").select("*").eq("id", request_id).single().execute()
    ).data

    project = create_project(
        client,
        {
            "title": request_row["title"],
            "problem_solved": None,
            "description": request_row.get("details"),
            "tags": None,
            "github_url": request_row.get("repo_link"),
            "demo_url": request_row.get("live_link"),
            "devpost_url": None,
        },
        admin_id,
    )

    now = datetime.now(timezone.utc).isoformat()
    client.table("project_submission_requests").update(
        {"status": REQUEST_STATUS_APPROVED, "reviewed_by": admin_id, "reviewed_at": now}
    ).eq("id", request_id).execute()

    return project


def reject_project_request(
    client: Client, request_id: str, admin_id: str, reason: str | None
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    client.table("project_submission_requests").update(
        {
            "status": REQUEST_STATUS_REJECTED,
            "reviewed_by": admin_id,
            "reviewed_at": now,
            "rejection_reason": reason,
        }
    ).eq("id", request_id).execute()


# --- Hackathon submission requests -----------------------------------------


def submit_hackathon_request(
    client: Client,
    submitted_by: str,
    name: str,
    template_photo: str | None,
    start_time: str | None,
    end_time: str | None,
    registration_link: str | None,
    prize_pool: str | None,
) -> dict[str, Any]:
    response = (
        client.table("hackathon_submission_requests")
        .insert(
            {
                "submitted_by": submitted_by,
                "name": name,
                "template_photo": template_photo,
                "start_time": start_time,
                "end_time": end_time,
                "registration_link": registration_link,
                "prize_pool": prize_pool,
            }
        )
        .execute()
    )
    return response.data[0]


def list_own_hackathon_requests(client: Client, user_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("hackathon_submission_requests")
        .select("*")
        .eq("submitted_by", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def list_pending_hackathon_requests(client: Client) -> list[dict[str, Any]]:
    response = (
        client.table("hackathon_submission_requests")
        .select("*")
        .eq("status", REQUEST_STATUS_PENDING)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []


def approve_hackathon_request(client: Client, request_id: str, admin_id: str) -> dict[str, Any]:
    request_row = (
        client.table("hackathon_submission_requests")
        .select("*")
        .eq("id", request_id)
        .single()
        .execute()
    ).data

    if not request_row.get("end_time"):
        raise ValueError("This request has no ending time and cannot be approved as-is.")

    hackathon = create_or_update_hackathon(
        client,
        {
            "name": request_row["name"],
            "template_photo": request_row.get("template_photo"),
            "start_at": request_row.get("start_time"),
            "end_at": request_row["end_time"],
            "registration_link": request_row.get("registration_link"),
            "prize_amount": request_row.get("prize_pool"),
        },
        admin_id,
    )

    now = datetime.now(timezone.utc).isoformat()
    client.table("hackathon_submission_requests").update(
        {"status": REQUEST_STATUS_APPROVED, "reviewed_by": admin_id, "reviewed_at": now}
    ).eq("id", request_id).execute()

    return hackathon


def reject_hackathon_request(
    client: Client, request_id: str, admin_id: str, reason: str | None
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    client.table("hackathon_submission_requests").update(
        {
            "status": REQUEST_STATUS_REJECTED,
            "reviewed_by": admin_id,
            "reviewed_at": now,
            "rejection_reason": reason,
        }
    ).eq("id", request_id).execute()


# --- Project deletion requests ----------------------------------------------


def submit_deletion_request(
    client: Client, project_id: str, requested_by: str, reason: str | None
) -> dict[str, Any]:
    try:
        response = (
            client.table("project_deletion_requests")
            .insert({"project_id": project_id, "requested_by": requested_by, "reason": reason})
            .execute()
        )
    except PostgrestAPIError as exc:
        if getattr(exc, "code", None) == "23505":
            raise DuplicatePendingRequestError(
                "There is already a pending deletion request for this project."
            ) from exc
        raise
    return response.data[0]


def list_own_deletion_requests(client: Client, user_id: str) -> list[dict[str, Any]]:
    response = (
        client.table("project_deletion_requests")
        .select("*")
        .eq("requested_by", user_id)
        .order("created_at", desc=True)
        .execute()
    )
    return response.data or []


def list_pending_deletion_requests(client: Client) -> list[dict[str, Any]]:
    response = (
        client.table("project_deletion_requests")
        .select("*")
        .eq("status", REQUEST_STATUS_PENDING)
        .order("created_at", desc=False)
        .execute()
    )
    return response.data or []


def approve_deletion_request(client: Client, request_id: str, admin_id: str) -> None:
    request_row = (
        client.table("project_deletion_requests").select("*").eq("id", request_id).single().execute()
    ).data

    client.table("projects").delete().eq("id", request_row["project_id"]).execute()

    now = datetime.now(timezone.utc).isoformat()
    client.table("project_deletion_requests").update(
        {"status": REQUEST_STATUS_APPROVED, "reviewed_by": admin_id, "reviewed_at": now}
    ).eq("id", request_id).execute()


def reject_deletion_request(client: Client, request_id: str, admin_id: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    client.table("project_deletion_requests").update(
        {"status": REQUEST_STATUS_REJECTED, "reviewed_by": admin_id, "reviewed_at": now}
    ).eq("id", request_id).execute()


def pending_counts(client: Client) -> dict[str, int]:
    projects = len(list_pending_project_requests(client))
    hackathons = len(list_pending_hackathon_requests(client))
    deletions = len(list_pending_deletion_requests(client))
    return {
        "projects": projects,
        "hackathons": hackathons,
        "deletions": deletions,
        "total": projects + hackathons + deletions,
    }
