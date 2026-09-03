from __future__ import annotations

import streamlit as st

from services.chat import run_chat_turn
from services.gemini_service import get_gemini_client
from services.state import get_active_hackathons, get_projects, require_auth

CHAT_HISTORY_KEY = "ai_chat_history"

EXAMPLE_PROMPTS = [
    "Suggest the best project for all active hackathons",
    "Which hackathon should I focus on?",
    "Find AI healthcare projects",
    "Which hackathons are ending this week?",
]


def render() -> None:
    st.title("🤖 AI Chat")
    st.caption(
        "Ask about DevVault's shared projects and active hackathons. Answers are grounded "
        "only in real DevVault data."
    )

    auth = require_auth()
    if not auth:
        return
    settings, client, profile = auth

    if not settings.gemini_configured:
        st.info(
            "⚠ Gemini API key not configured. AI Chat still works using database-only "
            "recommendations — add a key on the **⚙️ Settings** page for full AI reasoning."
        )

    if CHAT_HISTORY_KEY not in st.session_state:
        st.session_state[CHAT_HISTORY_KEY] = []

    projects = get_projects(client)
    hackathons = get_active_hackathons(client)

    if not projects and not hackathons:
        st.info("There are no projects or active hackathons in DevVault yet.")

    st.write("Try asking:")
    cols = st.columns(len(EXAMPLE_PROMPTS))
    for col, prompt in zip(cols, EXAMPLE_PROMPTS):
        if col.button(prompt, width="stretch"):
            st.session_state["pending_chat_prompt"] = prompt

    for message in st.session_state[CHAT_HISTORY_KEY]:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    pending = st.session_state.pop("pending_chat_prompt", None)
    user_input = st.chat_input("Ask DevVault AI…")
    query = pending or user_input

    if query:
        st.session_state[CHAT_HISTORY_KEY].append({"role": "user", "content": query})
        with st.chat_message("user"):
            st.markdown(query)

        with st.chat_message("assistant"):
            with st.spinner("Thinking…"):
                reply = _answer(client, settings, query, projects, hackathons)
            st.markdown(reply)

        st.session_state[CHAT_HISTORY_KEY].append({"role": "assistant", "content": reply})

    if st.session_state[CHAT_HISTORY_KEY] and st.button("Clear conversation"):
        st.session_state[CHAT_HISTORY_KEY] = []
        st.rerun()


def _answer(client, settings, query: str, projects: list[dict], hackathons: list[dict]) -> str:
    # Gemini is optional: services/chat.py and agents/matcher_agent.py both
    # handle a None gemini_client (or a Gemini call that fails after
    # retries) by falling back to the deterministic matching engine and
    # plain data listings, never crashing and never showing a raw
    # exception. This function's own try/except is only a last-resort net
    # for genuinely unexpected errors (e.g. a Supabase network failure).
    gemini_client = None
    if settings.gemini_configured:
        try:
            gemini_client = get_gemini_client(settings)
        except Exception:  # noqa: BLE001
            gemini_client = None

    try:
        result = run_chat_turn(
            client, gemini_client, settings.gemini_model, query, projects, hackathons
        )
    except Exception as exc:  # noqa: BLE001
        return f"Something went wrong answering that: {exc}"

    if result.get("export"):
        return "Head to the **📥 Export** page to download projects as Excel or CSV."
    return result.get("reply") or "I couldn't generate a response from the available data."


render()
