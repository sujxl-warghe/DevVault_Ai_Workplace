"""Project Agent.

Responsible for everything project-related in a chat turn: listing,
searching, and formatting saved projects as grounded context for Gemini.
Never invents projects, GitHub links, or demo links — it only ever hands
Gemini exactly what came back from Supabase, and instructs Gemini (via the
prompt built in services/chat.py) to do the same.
"""
from __future__ import annotations

from typing import Any

from services.projects_service import find_projects_by_name, search_projects


def run(query: str, all_projects: list[dict[str, Any]]) -> dict[str, Any]:
    """Picks the most relevant subset of saved projects for this query.

    Falls back to the full list (capped) if nothing specific matches, so
    Gemini still has real data to ground an answer in rather than none.
    """
    # If the query looks like it's naming specific projects (e.g. a
    # "compare X and Y" request), try to resolve exact/substring matches
    # first — that's more precise than a generic keyword search.
    named = _extract_quoted_or_capitalized_terms(query)
    named_matches = find_projects_by_name(all_projects, *named) if named else []

    if named_matches:
        relevant = named_matches
    else:
        relevant = search_projects(all_projects, query)
        if not relevant:
            relevant = all_projects

    # Cap what we hand to the model — plenty for grounding without bloating
    # the prompt on large libraries.
    capped = relevant[:25]

    return {
        "module": "project",
        "projects": capped,
        "total_saved": len(all_projects),
    }


def _extract_quoted_or_capitalized_terms(query: str) -> list[str]:
    import re

    quoted = re.findall(r'"([^"]+)"|\'([^\']+)\'', query)
    terms = [a or b for a, b in quoted]

    # Heuristic: standalone capitalized words/short phrases (project names
    # are often CamelCase or Titlecase, e.g. "RepoMedic", "RescueMesh").
    capitalized = re.findall(r"\b([A-Z][a-zA-Z0-9]{2,})\b", query)
    # Filter out generic sentence-starters that happen to be capitalized.
    stopwords = {"Compare", "Which", "Can", "How", "Show", "Find", "Best", "This"}
    terms += [w for w in capitalized if w not in stopwords]

    return list(dict.fromkeys(terms))  # de-dupe, preserve order
