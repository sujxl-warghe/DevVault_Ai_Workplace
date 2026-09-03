"""Hackathon Agent.

Retrieves and lightly filters active global hackathons (already end_at >
NOW() from the service layer) for use as grounded chat context — e.g.
"which hackathons are ending this week?" or as input to the Matcher Agent.
"""
from __future__ import annotations

from typing import Any

from services.dates import hours_remaining
from services.hackathons_service import find_hackathon_by_name


def run(query: str, all_hackathons: list[dict[str, Any]]) -> dict[str, Any]:
    named = find_hackathon_by_name(all_hackathons, query)
    relevant = [named] if named else all_hackathons

    q = query.lower()
    if "this week" in q or "next 7 days" in q:
        relevant = [h for h in relevant if _within_hours(h, 24 * 7)]
    elif "today" in q or "24 hours" in q or "tomorrow" in q:
        relevant = [h for h in relevant if _within_hours(h, 48)]

    return {
        "module": "hackathon",
        "hackathons": relevant,
        "total_active": len(all_hackathons),
    }


def _within_hours(hackathon: dict[str, Any], hours: float) -> bool:
    remaining = hours_remaining(hackathon.get("end_at"))
    return remaining is not None and 0 <= remaining <= hours
