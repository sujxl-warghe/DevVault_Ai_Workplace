"""Orchestrates a single AI Chat turn.

Flow: classify_intent() picks a route -> for 'direct_*' routes, retrieved
rows are formatted straight into the reply with ZERO Gemini calls -> for
'export', the reply just points at the Export page -> otherwise only the
needed agents run (and only they touch Supabase), their data is assembled
into a grounded prompt, and Gemini answers using ONLY that data. If Gemini
is unavailable after retries, the user still gets a useful, data-grounded
answer via the deterministic fallback rather than an error.

All authenticated users share the same pool: projects and hackathons are
both global, so AI Chat sees identical underlying data for every user —
there is no per-user project scoping anymore.
"""
from __future__ import annotations

from typing import Any

from agents import hackathon_agent, matcher_agent, project_agent
from agents.router import classify_intent
from services.dates import compute_status, format_date, format_time_remaining, status_label
from services.gemini_service import GeminiUnavailableError, generate_text

SYSTEM_PREAMBLE = """You are DevVault AI, a focused assistant for hackathon \
strategy. You help the user decide what to build and which shared DevVault \
project best fits available hackathons.

Ground every answer ONLY in the PROJECTS and ACTIVE HACKATHONS data \
provided below. Never invent a project, a hackathon, a repo link, a live \
link, or a deadline. If the data needed to answer isn't present, say so \
plainly instead of guessing. Be concise and practical."""

GEMINI_UNAVAILABLE_NOTICE = (
    "⚠ Gemini is temporarily unavailable. Showing database-based recommendations."
)


def run_chat_turn(
    supabase_client: Any,
    gemini_client: Any,
    gemini_model: str,
    query: str,
    all_projects: list[dict[str, Any]],
    all_hackathons: list[dict[str, Any]],
) -> dict[str, Any]:
    modules = classify_intent(query)
    agent_outputs: dict[str, Any] = {"modules_used": modules}

    if modules == ["export"]:
        agent_outputs["export"] = True
        return agent_outputs

    if modules == ["direct_project"]:
        agent_outputs["reply"] = _format_projects_directly(all_projects)
        return agent_outputs

    if modules == ["direct_hackathon"]:
        agent_outputs["reply"] = _format_hackathons_directly(all_hackathons)
        return agent_outputs

    project_result = None
    hackathon_result = None

    if "project" in modules:
        project_result = project_agent.run(query, all_projects)
        agent_outputs["project"] = project_result

    if "hackathon" in modules:
        hackathon_result = hackathon_agent.run(query, all_hackathons)
        agent_outputs["hackathon"] = hackathon_result

    if "matcher" in modules:
        matcher_projects = project_result["projects"] if project_result else all_projects
        matcher_hackathons = hackathon_result["hackathons"] if hackathon_result else all_hackathons
        matcher_result = matcher_agent.run(
            gemini_client, gemini_model, query, matcher_projects, matcher_hackathons
        )
        agent_outputs["matcher"] = matcher_result
        reply = _format_matcher_reply(matcher_result)
        if matcher_result.get("gemini_unavailable"):
            reply = f"{GEMINI_UNAVAILABLE_NOTICE}\n\n{reply}"
        agent_outputs["reply"] = reply
        return agent_outputs

    # Project and/or Hackathon Agent only: one grounded Gemini call using
    # whatever data those agents retrieved, with a deterministic fallback
    # if Gemini can't be reached.
    prompt = _build_grounded_prompt(query, project_result, hackathon_result)
    try:
        if gemini_client is None:
            raise GeminiUnavailableError("Gemini not configured")
        agent_outputs["reply"] = generate_text(gemini_client, gemini_model, prompt)
    except GeminiUnavailableError:
        fallback = _fallback_reply(project_result, hackathon_result)
        agent_outputs["reply"] = f"{GEMINI_UNAVAILABLE_NOTICE}\n\n{fallback}"

    return agent_outputs


def _build_grounded_prompt(
    query: str,
    project_result: dict[str, Any] | None,
    hackathon_result: dict[str, Any] | None,
) -> str:
    sections = [SYSTEM_PREAMBLE]

    if project_result is not None:
        projects = project_result["projects"]
        if projects:
            lines = []
            for p in projects:
                lines.append(
                    f"- {p.get('title')}\n"
                    f"  Details: {(p.get('description') or 'not recorded')[:300]}\n"
                    f"  Repo Link: {p.get('github_url') or 'none'}\n"
                    f"  Live Link: {p.get('demo_url') or 'none'}"
                )
            sections.append("PROJECTS (global, shared with every user):\n" + "\n".join(lines))
        else:
            sections.append("PROJECTS: (none added yet)")

    if hackathon_result is not None:
        hackathons = hackathon_result["hackathons"]
        if hackathons:
            lines = []
            for h in hackathons:
                lines.append(
                    f"- {h.get('name')}\n"
                    f"  Starting: {h.get('start_at') or 'not recorded'}\n"
                    f"  Ending: {h.get('end_at')}\n"
                    f"  Prize Pool: {h.get('prize_amount') or 'not recorded'}\n"
                    f"  Registration Link: {h.get('registration_link') or 'none'}"
                )
            sections.append("ACTIVE HACKATHONS (global, shared):\n" + "\n".join(lines))
        else:
            sections.append("ACTIVE HACKATHONS: (none currently active)")

    sections.append(f"USER QUESTION:\n{query}")
    return "\n\n".join(sections)


def _format_matcher_reply(matcher_result: dict[str, Any]) -> str:
    matches = matcher_result.get("matches") or []
    if not matches:
        note = matcher_result.get("note") or "I couldn't compute a match from the available data."
        return note

    lines = []
    for m in matches:
        lines.append(
            f"**{m.get('project_title')}** → *{m.get('hackathon_name')}* — "
            f"Match score: {m.get('match_score')}/100\n"
            f"- Why it matches: {m.get('why_it_matches')}\n"
            f"- Missing features: {m.get('missing_features')}\n"
            f"- Suggested improvements: {m.get('suggested_improvements')}\n"
            f"- Repo Link: {m.get('repo_link') or 'none'} | Live Link: {m.get('live_link') or 'none'} | "
            f"Registration: {m.get('registration_link') or 'none'}"
        )
    return "\n\n".join(lines)


def _format_projects_directly(projects: list[dict[str, Any]]) -> str:
    """Simple database query -> direct Supabase read, formatted straight
    into the reply, no Gemini call at all."""
    if not projects:
        return "There are no projects in DevVault yet."
    lines = [f"There are {len(projects)} project(s) in DevVault:"]
    for p in projects:
        lines.append(
            f"- **{p.get('title')}** — {p.get('description') or 'no details recorded'}"
        )
    return "\n".join(lines)


def _format_hackathons_directly(hackathons: list[dict[str, Any]]) -> str:
    if not hackathons:
        return "There are no active hackathons right now."
    lines = [f"There are {len(hackathons)} active hackathon(s):"]
    for h in hackathons:
        status = status_label(compute_status(h.get("start_at"), h.get("end_at")))
        lines.append(
            f"- **{h.get('name')}** — {status}, ends {format_date(h.get('end_at'))} "
            f"({format_time_remaining(h.get('end_at'))})"
        )
    return "\n".join(lines)


def _fallback_reply(
    project_result: dict[str, Any] | None, hackathon_result: dict[str, Any] | None
) -> str:
    """Used only when Gemini is unavailable and the query didn't need the
    Matcher Agent (which has its own deterministic fallback). Falls back to
    a plain listing of whatever real data was retrieved."""
    parts = []
    if project_result is not None:
        parts.append(_format_projects_directly(project_result["projects"]))
    if hackathon_result is not None:
        parts.append(_format_hackathons_directly(hackathon_result["hackathons"]))
    return "\n\n".join(parts) if parts else "No matching data was found."
