from __future__ import annotations

from datetime import datetime, timezone


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        # Supabase returns e.g. "2026-08-01T23:59:00+00:00"
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def format_deadline(value: str | None) -> str:
    dt = parse_iso(value)
    if not dt:
        return "Unknown"
    return dt.strftime("%b %d, %Y %I:%M %p UTC")


def format_time_remaining(value: str | None) -> str:
    dt = parse_iso(value)
    if not dt:
        return "Unknown"
    now = datetime.now(timezone.utc)
    delta = dt - now
    total_seconds = int(delta.total_seconds())
    if total_seconds <= 0:
        return "Ended"

    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    if days > 0:
        return f"{days}d {hours}h left"
    if hours > 0:
        return f"{hours}h {minutes}m left"
    return f"{minutes}m left"


def hours_remaining(value: str | None) -> float | None:
    dt = parse_iso(value)
    if not dt:
        return None
    now = datetime.now(timezone.utc)
    return (dt - now).total_seconds() / 3600


# --- Hackathon status/timeline helpers -------------------------------------
#
# Status is always derived from real database timestamps at render time —
# never hardcoded, never computed by Gemini — so it's automatically correct
# as time passes.

ENDING_SOON_THRESHOLD_HOURS = 24

STATUS_ENDED = "ENDED"
STATUS_ENDING_SOON = "ENDING SOON"
STATUS_ONGOING = "ONGOING"
STATUS_UPCOMING = "UPCOMING"

STATUS_LABELS = {
    STATUS_ENDED: "⏹ Ended",
    STATUS_ENDING_SOON: "🔥 Ending Soon",
    STATUS_ONGOING: "🟢 Ongoing",
    STATUS_UPCOMING: "🗓 Upcoming",
}


def compute_status(start_at: str | None, end_at: str | None, now: datetime | None = None) -> str:
    """Derives a hackathon's status purely from its start/end timestamps.

    - current time <  start_time                            -> UPCOMING
    - current time >= start_time AND < end_time              -> ONGOING
    - end_time is approaching (within ENDING_SOON_THRESHOLD_HOURS) -> ENDING SOON
      (checked first — it can override ONGOING or, for a very short
      upcoming event, even UPCOMING, since "about to end" is more useful
      to surface than "technically hasn't started")
    - current time >= end_time                                -> ENDED
    """
    now = now or datetime.now(timezone.utc)
    end_dt = parse_iso(end_at)
    start_dt = parse_iso(start_at)

    if end_dt and end_dt <= now:
        return STATUS_ENDED
    if end_dt and (end_dt - now).total_seconds() <= ENDING_SOON_THRESHOLD_HOURS * 3600:
        return STATUS_ENDING_SOON
    if start_dt and start_dt <= now:
        return STATUS_ONGOING
    return STATUS_UPCOMING


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)


def next_milestone_at(start_at: str | None, end_at: str | None) -> datetime | None:
    """The soonest upcoming timestamp between start and end — used to sort
    the timeline chronologically so an about-to-start hackathon surfaces
    before one that starts later but ends sooner isn't accidentally
    mis-ordered."""
    now = datetime.now(timezone.utc)
    candidates = [dt for dt in (parse_iso(start_at), parse_iso(end_at)) if dt and dt > now]
    if candidates:
        return min(candidates)
    return parse_iso(end_at)


def format_date(value: str | None) -> str:
    dt = parse_iso(value)
    if not dt:
        return "—"
    return dt.strftime("%b %d, %Y")


def format_datetime_short(value: str | None) -> str:
    dt = parse_iso(value)
    if not dt:
        return "—"
    return dt.strftime("%b %d, %I:%M %p UTC")


def combine_date_time_utc(date_value, time_value) -> datetime | None:
    """Combines a Streamlit st.date_input / st.time_input pair into a UTC
    datetime. Manually entered hackathon dates are treated as UTC — this is
    stated in the UI and README so there's no ambiguity about timezone."""
    if not date_value:
        return None
    from datetime import time as time_cls

    t = time_value or time_cls(0, 0)
    return datetime.combine(date_value, t, tzinfo=timezone.utc)
