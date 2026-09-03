"""Determines which agent(s) a chat message needs, *before* calling Gemini.

Deliberately rule-based (no LLM call) — classification only needs to decide
which Supabase data to fetch and which agent(s) to run; spending a Gemini
call just to route would violate "avoid unnecessary AI calls." If a query
matches nothing specific, Project Agent is the safe default since most
questions are ultimately about saved projects.

A "direct" query (simple listing/browsing, e.g. "show my projects") skips
Gemini entirely — the retrieved rows are formatted straight into the reply
by services/chat.py — per "Simple database query: → Direct Supabase query."
"""
from __future__ import annotations

EXPORT_TRIGGERS = ["export", "download", "csv", "excel", "spreadsheet", "xlsx"]

MATCHER_TRIGGERS = [
    "best project for",
    "best fit",
    "best match",
    "suggest the best project",
    "should i focus",
    "which project should",
    "recommend a project",
    "match score",
    "fit",
    "improve",
]

HACKATHON_TRIGGERS = [
    "hackathon",
    "deadline",
    "ending",
    "due",
    "submission period",
    "register",
    "theme",
    "track",
    "sponsor",
    "prize",
]

PROJECT_TRIGGERS = [
    "project",
    "github",
    "demo",
    "saved",
    "compare",
    "tag",
    "technology",
]

# Phrases that signal "just show me the raw list," not a request for
# reasoning/comparison/recommendation — these route straight to a direct
# Supabase read with zero Gemini calls.
DIRECT_PROJECT_PATTERNS = [
    "show my projects",
    "show saved projects",
    "list my projects",
    "list projects",
    "list saved projects",
    "what projects do i have",
    "show all my projects",
]

DIRECT_HACKATHON_PATTERNS = [
    "show hackathons",
    "show active hackathons",
    "list hackathons",
    "list active hackathons",
    "what hackathons are there",
    "show all hackathons",
]

# If any of these appear, the query needs actual reasoning even if it also
# matches a "direct" phrase (e.g. "list hackathons ending this week and
# tell me which is best") — so direct-routing only applies when none of
# these reasoning cues are present.
REASONING_OVERRIDE_TRIGGERS = [
    "best",
    "compare",
    "why",
    "improve",
    "match",
    "fit",
    "suggest",
    "recommend",
    "should i",
]

VALID_MODULES = ("project", "hackathon", "matcher", "export", "direct_project", "direct_hackathon")


def classify_intent(query: str) -> list[str]:
    """Returns an ordered list of modules to run: any combination of
    'project'/'hackathon'/'matcher', or a single-item list —
    ['export'], ['direct_project'], or ['direct_hackathon']."""
    q = query.lower().strip()
    if not q:
        return ["project"]

    if any(trigger in q for trigger in EXPORT_TRIGGERS):
        return ["export"]

    needs_reasoning = any(trigger in q for trigger in REASONING_OVERRIDE_TRIGGERS)

    if not needs_reasoning:
        if any(pattern in q for pattern in DIRECT_PROJECT_PATTERNS):
            return ["direct_project"]
        if any(pattern in q for pattern in DIRECT_HACKATHON_PATTERNS):
            return ["direct_hackathon"]

    matcher_hit = any(trigger in q for trigger in MATCHER_TRIGGERS)
    hackathon_hit = any(trigger in q for trigger in HACKATHON_TRIGGERS)
    project_hit = any(trigger in q for trigger in PROJECT_TRIGGERS)

    if matcher_hit:
        # Matching a project to a hackathon always needs both datasets.
        return ["project", "hackathon", "matcher"]

    if hackathon_hit and not project_hit:
        return ["hackathon"]

    if hackathon_hit and project_hit:
        # Mentions both but no explicit matching language — still avoid the
        # matcher (and its extra Gemini narrative) unless truly needed.
        return ["project", "hackathon"]

    # project_hit, or no signal at all — Project Agent is the safe default.
    return ["project"]
