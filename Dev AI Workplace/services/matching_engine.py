"""Deterministic project↔hackathon matching engine.

Computes a 0-100 fit score from real saved data alone — no Gemini call
involved — so the app always has a useful, reproducible ranking even when
Gemini is unavailable, rate-limited, or not configured.

The available fields are now deliberately minimal (per the simplified
Project: Title/Details/Repo Link/Live Link and Hackathon: Name/Template
Photo/Start/End/Registration Link/Prize Pool forms), so scoring uses four
factors instead of the richer tag-based scheme from earlier phases:

  - Name/Title similarity      (25%) — token overlap between project title and hackathon name
  - Details/context similarity (40%) — token overlap between project details and hackathon name/any legacy description text
  - Hackathon template/context similarity (10%) — proxy: a template/photo and/or prize pool being set suggests a more concretely-defined, matchable event
  - Implementation Feasibility (25%) — proxy: has a working live link and/or repo link
"""
from __future__ import annotations

import re
from typing import Any

WEIGHTS = {
    "name_title_similarity": 0.25,
    "details_context_similarity": 0.40,
    "hackathon_context_similarity": 0.10,
    "feasibility": 0.25,
}

_WORD_RE = re.compile(r"[a-z0-9]+")

# Common words that don't carry matching signal on their own.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "to", "of", "in", "on",
    "is", "are", "this", "that", "it", "using", "app", "project", "build",
    "hackathon", "hack", "2024", "2025", "2026",
}


def _tokenize(*texts: str | None) -> set[str]:
    combined = " ".join(t for t in texts if t)
    tokens = set(_WORD_RE.findall(combined.lower()))
    return {t for t in tokens if t not in _STOPWORDS and len(t) > 2}


def _overlap_score(a: set[str], b: set[str]) -> float:
    """0-100 from how much of the smaller token set is covered by the
    larger, so short titles aren't unfairly penalized against long ones."""
    if not a or not b:
        return 0.0
    intersection = a & b
    smaller = min(len(a), len(b))
    if smaller == 0:
        return 0.0
    return min(100.0, (len(intersection) / smaller) * 100.0)


def compute_match(project: dict[str, Any], hackathon: dict[str, Any]) -> dict[str, Any]:
    """Returns a breakdown + overall 0-100 score for one project×hackathon
    pair, plus the matched keyword list used to build human-readable
    "why it matches" text without any LLM."""
    project_title_tokens = _tokenize(project.get("title"))
    project_detail_tokens = _tokenize(project.get("title"), project.get("description"))

    hackathon_name_tokens = _tokenize(hackathon.get("name"))
    # Legacy columns (description/themes/tracks) may still be populated on
    # older rows even though the current minimal form doesn't collect
    # them — used opportunistically for extra context when present.
    hackathon_context_tokens = _tokenize(
        hackathon.get("name"),
        hackathon.get("description"),
        " ".join(hackathon.get("themes") or []),
        " ".join(hackathon.get("tracks") or []),
    )

    name_title_similarity = _overlap_score(project_title_tokens, hackathon_name_tokens)
    details_context_similarity = _overlap_score(project_detail_tokens, hackathon_context_tokens)

    # Template/context proxy: a hackathon with a template photo and/or a
    # prize pool set is more concretely defined, which makes any match
    # against it more meaningful than an almost-empty record.
    context_richness = 0.0
    if hackathon.get("template_photo"):
        context_richness += 50.0
    if hackathon.get("prize_amount"):
        context_richness += 50.0

    feasibility = 0.0
    if project.get("demo_url"):
        feasibility += 60.0
    if project.get("github_url"):
        feasibility += 40.0

    factors = {
        "name_title_similarity": name_title_similarity,
        "details_context_similarity": details_context_similarity,
        "hackathon_context_similarity": context_richness,
        "feasibility": feasibility,
    }

    overall = sum(factors[k] * WEIGHTS[k] for k in WEIGHTS)
    matched_tokens = sorted(project_detail_tokens & hackathon_context_tokens)

    return {
        "project": project,
        "hackathon": hackathon,
        "score": round(overall),
        "factors": {k: round(v) for k, v in factors.items()},
        "matched_tokens": matched_tokens,
    }


def rank_matches(
    projects: list[dict[str, Any]], hackathons: list[dict[str, Any]], top_n: int = 5
) -> list[dict[str, Any]]:
    """All project×hackathon combinations, scored and sorted best-first."""
    results = [compute_match(p, h) for p in projects for h in hackathons]
    results.sort(key=lambda r: r["score"], reverse=True)
    return results[:top_n]


def deterministic_explanation(match: dict[str, Any]) -> dict[str, str]:
    """Builds plain-language why/improvements text from the score
    breakdown alone — used both as a quick preview (no AI) and as the
    fallback when Gemini is unavailable."""
    matched = match["matched_tokens"]
    factors = match["factors"]

    if matched:
        why = f"Shares keywords with the hackathon: {', '.join(matched[:5])}."
    elif factors["name_title_similarity"] >= 30:
        why = "The project's title closely echoes this hackathon's name."
    else:
        why = "Limited direct overlap found — this is a lower-confidence match."

    improvements = []
    if not match["project"].get("demo_url"):
        improvements.append("add a live link")
    if not match["project"].get("github_url"):
        improvements.append("add a repo link")
    if not matched:
        improvements.append("clarify how the project's details relate to this hackathon's theme")
    improvements_text = (
        f"Could improve fit by: {', '.join(improvements)}."
        if improvements
        else "Already well-aligned based on recorded data."
    )

    return {
        "why_it_matches": why,
        "missing_features": "None identified from the recorded fields." if matched else "No shared keywords found between the project and hackathon.",
        "suggested_improvements": improvements_text,
    }
