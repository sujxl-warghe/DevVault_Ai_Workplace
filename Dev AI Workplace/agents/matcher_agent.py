"""Matcher Agent.

Two layers, per the spec ("Do not rely entirely on Gemini for scoring"):

1. services/matching_engine.py computes a deterministic 0-100 match score
   for every project×hackathon pair from real saved data (title/details
   text overlap, repo/live link presence) — no AI call, always available,
   always reproducible.
2. Gemini is asked, in a single batched call for the top-N deterministic
   matches, to write the "why it matches" / "missing features" /
   "suggested improvements" narrative. If Gemini is unavailable (503, 429,
   500, timeout, network error — even after retries), the deterministic
   engine's own plain-language explanation is used instead, so the user
   always gets a real recommendation.

Every GitHub/Demo/Devpost link returned is copied verbatim from the actual
project/hackathon records already retrieved from Supabase — never invented
or rewritten by Gemini.
"""
from __future__ import annotations

import json
from typing import Any

from services.gemini_service import GeminiUnavailableError, generate_text
from services.matching_engine import deterministic_explanation, rank_matches

TOP_N = 5


def run(
    client: Any,
    model: str,
    query: str,
    projects: list[dict[str, Any]],
    hackathons: list[dict[str, Any]],
) -> dict[str, Any]:
    if not projects:
        return {"module": "matcher", "matches": [], "note": "No saved projects to match against."}
    if not hackathons:
        return {"module": "matcher", "matches": [], "note": "No active hackathons to match against."}

    ranked = rank_matches(projects, hackathons, top_n=TOP_N)

    gemini_unavailable = False
    reasoning_by_index: dict[int, dict[str, str]] = {}

    if client is not None and model:
        try:
            raw = _call_gemini_for_reasoning(client, model, query, ranked)
            reasoning_by_index = _parse_reasoning_response(raw, len(ranked))
        except GeminiUnavailableError:
            gemini_unavailable = True
        except Exception:  # noqa: BLE001 - never let a malformed response crash the chat
            gemini_unavailable = True
    else:
        gemini_unavailable = True

    matches = []
    for i, match in enumerate(ranked):
        reasoning = reasoning_by_index.get(i) or deterministic_explanation(match)
        project = match["project"]
        hackathon = match["hackathon"]
        matches.append(
            {
                "project_title": project.get("title"),
                "hackathon_name": hackathon.get("name"),
                "match_score": match["score"],
                "why_it_matches": reasoning.get("why_it_matches"),
                "missing_features": reasoning.get("missing_features"),
                "suggested_improvements": reasoning.get("suggested_improvements"),
                "repo_link": project.get("github_url"),
                "live_link": project.get("demo_url"),
                "registration_link": hackathon.get("registration_link"),
            }
        )

    return {"module": "matcher", "matches": matches, "gemini_unavailable": gemini_unavailable}


def _call_gemini_for_reasoning(
    client: Any, model: str, query: str, ranked: list[dict[str, Any]]
) -> str:
    lines = []
    for i, match in enumerate(ranked):
        p, h = match["project"], match["hackathon"]
        lines.append(
            f"[{i}] Project: {p.get('title')}\n"
            f"    Details: {(p.get('description') or 'not recorded')[:300]}\n"
            f"    Has repo link: {'yes' if p.get('github_url') else 'no'} | Has live link: {'yes' if p.get('demo_url') else 'no'}\n"
            f"    Hackathon: {h.get('name')}\n"
            f"    Prize pool: {h.get('prize_amount') or 'not recorded'}\n"
            f"    Deterministic match score (already computed, do not change it): {match['score']}/100"
        )

    prompt = f"""You are the Matcher Agent inside DevVault. A deterministic engine has
already scored the following project↔hackathon pairs (do not recompute or
alter the scores). Your only job is to write, for each pair, a short
"why it matches", "missing features", and "suggested improvements" — using
ONLY the information given below. Never invent projects, hackathons, repo
links, or live links.

PAIRS:
{chr(10).join(lines)}

USER REQUEST:
{query}

Respond with ONLY a JSON array (no markdown fences, no prose outside the
JSON), one object per pair index above, in this exact shape:
[
  {{"index": 0, "why_it_matches": "1-2 sentences", "missing_features": "1 sentence or 'None identified'", "suggested_improvements": "1-2 sentences"}}
]"""

    return generate_text(client, model, prompt)


def _parse_reasoning_response(raw: str, expected_count: int) -> dict[int, dict[str, str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}

    if not isinstance(parsed, list):
        return {}

    result: dict[int, dict[str, str]] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        if not isinstance(idx, int) or not (0 <= idx < expected_count):
            continue
        result[idx] = {
            "why_it_matches": item.get("why_it_matches") or "",
            "missing_features": item.get("missing_features") or "",
            "suggested_improvements": item.get("suggested_improvements") or "",
        }
    return result
