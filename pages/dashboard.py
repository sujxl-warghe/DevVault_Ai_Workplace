from __future__ import annotations

import streamlit as st

from services.dates import format_deadline, format_time_remaining, next_milestone_at
from services.matching_engine import rank_matches
from services.requests_service import pending_counts
from services.state import get_active_hackathons, get_projects, require_auth


def render() -> None:
    st.title("🏠 Dashboard")

    auth = require_auth()
    if not auth:
        return
    settings, client, profile = auth

    if profile.is_admin:
        _render_admin_notifications(client)

    projects = get_projects(client)
    hackathons = get_active_hackathons(client)

    col1, col2 = st.columns(2)
    col1.metric("📂 Total Projects", len(projects))
    col2.metric("🏆 Active Hackathons", len(hackathons))

    st.divider()

    col3, col4 = st.columns(2)

    with col3:
        st.subheader("⏰ Next Hackathon Ending")
        if hackathons:

            def _sort_key(h: dict) -> str:
                dt = next_milestone_at(h.get("start_at"), h.get("end_at"))
                return dt.isoformat() if dt else (h.get("end_at") or "")

            soonest = min(hackathons, key=_sort_key)
            st.markdown(f"**{soonest['name']}**")
            st.caption(format_deadline(soonest.get("end_at")))
            st.caption(format_time_remaining(soonest.get("end_at")))
            if soonest.get("prize_amount"):
                st.markdown(f"🏆 {soonest['prize_amount']}")
            if soonest.get("registration_link"):
                st.link_button("Register", soonest["registration_link"], width="stretch")
        else:
            st.info("No active hackathons yet.")

    with col4:
        st.subheader("⭐ Best Match Today")
        if not projects:
            st.info("No projects in DevVault yet.")
        elif not hackathons:
            st.info("No active hackathons to match against yet.")
        else:
            top = rank_matches(projects, hackathons, top_n=1)
            if top:
                match = top[0]
                st.markdown(f"**{match['project']['title']}** → *{match['hackathon']['name']}*")
                st.caption(f"{match['score']}% match (database-computed)")
                if st.button("Get full AI reasoning in AI Chat →", width="stretch"):
                    st.session_state["pending_chat_prompt"] = (
                        f"What's the best matching project for {match['hackathon']['name']}?"
                    )
                    st.switch_page("pages/ai_chat.py")
            else:
                st.info("No match could be computed yet.")


def _render_admin_notifications(client) -> None:
    counts = pending_counts(client)
    if counts["total"] == 0:
        return
    st.info(
        f"🔔 **Pending Requests: {counts['total']}** — "
        f"Projects: {counts['projects']} · Hackathons: {counts['hackathons']} · "
        f"Deletions: {counts['deletions']}"
    )
    if st.button("Review Submission Requests →"):
        st.session_state["settings_default_tab"] = "requests"
        st.switch_page("pages/settings_page.py")


render()
