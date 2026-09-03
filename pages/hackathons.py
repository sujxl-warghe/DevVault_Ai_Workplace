from __future__ import annotations

import streamlit as st

from services.dates import combine_date_time_utc, compute_status, format_date, format_time_remaining, next_milestone_at, status_label
from services.hackathons_service import create_or_update_hackathon, delete_hackathon
from services.matching_engine import rank_matches
from services.requests_service import submit_hackathon_request
from services.state import get_active_hackathons, get_current_user_id, get_projects, require_auth
from services.storage_service import storage_available, upload_template_photo


def render() -> None:
    st.title("🏆 Hackathons")
    st.caption("Global — shared with every DevVault user.")

    auth = require_auth()
    if not auth:
        return
    settings, client, profile = auth

    if profile.is_admin:
        _render_admin_add_form(client)
    else:
        _render_user_submit_form(client, profile)

    st.divider()

    hackathons = get_active_hackathons(client)
    projects = get_projects(client)

    if not hackathons:
        st.info("No active hackathons yet.")
        return

    def _sort_key(h: dict) -> str:
        dt = next_milestone_at(h.get("start_at"), h.get("end_at"))
        return dt.isoformat() if dt else (h.get("end_at") or "")

    ordered = sorted(hackathons, key=_sort_key)

    best_matches: dict[str, dict] = {}
    if projects:
        for h in ordered:
            ranked = rank_matches(projects, [h], top_n=1)
            if ranked:
                best_matches[h["id"]] = ranked[0]

    st.caption(f"{len(ordered)} active hackathon(s)")

    for h in ordered:
        _render_hackathon_card(client, h, best_matches.get(h["id"]), profile)


def _template_photo_input(client, key_prefix: str) -> str | None:
    """Template/Photo field: always a URL text input; if the optional
    storage bucket exists, also offers a file uploader that wins if used."""
    url = st.text_input("Template / Photo URL", key=f"{key_prefix}_url")

    uploaded_url = None
    if storage_available(client):
        uploaded_file = st.file_uploader(
            "...or upload an image", type=["png", "jpg", "jpeg", "webp"], key=f"{key_prefix}_upload"
        )
        if uploaded_file is not None:
            try:
                uploaded_url = upload_template_photo(client, uploaded_file.read(), uploaded_file.name)
                st.image(uploaded_url, width=200)
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Upload failed, you can still use the URL field instead: {exc}")

    return uploaded_url or (url.strip() or None)


def _render_admin_add_form(client) -> None:
    with st.expander("➕ Add Hackathon", expanded=False):
        st.caption("Enter all times in UTC.")
        with st.form("add_hackathon_form", clear_on_submit=True):
            name = st.text_input("Hackathon Name *")
            template_photo = _template_photo_input(client, "admin_add")
            registration_link = st.text_input("Registration Link")
            prize_pool = st.text_input("Prize Pool")

            col1, col2 = st.columns(2)
            start_date = col1.date_input("Starting Date", value=None)
            start_time = col2.time_input("Starting Time (UTC)", value=None)
            col3, col4 = st.columns(2)
            end_date = col3.date_input("Ending Date *", value=None)
            end_time = col4.time_input("Ending Time (UTC) *", value=None)

            submitted = st.form_submit_button("Add Hackathon", width="stretch")
            if submitted:
                end_at = combine_date_time_utc(end_date, end_time)
                if not name.strip() or not end_at:
                    st.error("Hackathon Name and Ending Date/Time are required.")
                else:
                    try:
                        user_id = get_current_user_id(client)
                        create_or_update_hackathon(
                            client,
                            {
                                "name": name.strip(),
                                "template_photo": template_photo,
                                "registration_link": registration_link.strip() or None,
                                "prize_amount": prize_pool.strip() or None,
                                "start_at": _iso_or_none(combine_date_time_utc(start_date, start_time)),
                                "end_at": end_at.isoformat(),
                            },
                            user_id,
                        )
                        get_active_hackathons_refresh(client)
                        st.success(f"Added {name}.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't add hackathon: {exc}")


def _render_user_submit_form(client, profile) -> None:
    with st.expander("➕ Add Hackathon", expanded=False):
        st.caption(
            "Your submission will be reviewed by an admin before it appears for everyone. "
            "Enter all times in UTC."
        )
        with st.form("submit_hackathon_form", clear_on_submit=True):
            name = st.text_input("Hackathon Name *")
            template_photo = _template_photo_input(client, "user_submit")
            registration_link = st.text_input("Registration Link")
            prize_pool = st.text_input("Prize Pool")

            col1, col2 = st.columns(2)
            start_date = col1.date_input("Starting Date", value=None)
            start_time = col2.time_input("Starting Time (UTC)", value=None)
            col3, col4 = st.columns(2)
            end_date = col3.date_input("Ending Date *", value=None)
            end_time = col4.time_input("Ending Time (UTC) *", value=None)

            submitted = st.form_submit_button("Submit for Approval", width="stretch")
            if submitted:
                end_at = combine_date_time_utc(end_date, end_time)
                if not name.strip() or not end_at:
                    st.error("Hackathon Name and Ending Date/Time are required.")
                else:
                    try:
                        submit_hackathon_request(
                            client,
                            profile.id,
                            name.strip(),
                            template_photo,
                            _iso_or_none(combine_date_time_utc(start_date, start_time)),
                            end_at.isoformat(),
                            registration_link.strip() or None,
                            prize_pool.strip() or None,
                        )
                        st.success("Submitted for admin approval. Track it under Settings → My Requests.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't submit request: {exc}")


def _iso_or_none(dt) -> str | None:
    return dt.isoformat() if dt else None


def get_active_hackathons_refresh(client) -> None:
    get_active_hackathons(client, force_refresh=True)


def _render_hackathon_card(client, h: dict, best_match: dict | None, profile) -> None:
    status = compute_status(h.get("start_at"), h.get("end_at"))

    with st.container(border=True):
        cols = st.columns([1, 2, 1]) if h.get("template_photo") else st.columns([3, 1])

        if h.get("template_photo"):
            img_col, info_col, action_col = cols
            try:
                img_col.image(h["template_photo"], width="stretch")
            except Exception:
                pass
        else:
            info_col, action_col = cols

        with info_col:
            st.markdown(f"### {h['name']}")
            st.markdown(status_label(status))

            meta_cols = st.columns(2)
            if h.get("start_at"):
                meta_cols[0].caption("Starts")
                meta_cols[0].write(format_date(h["start_at"]))
            meta_cols[1].caption("Ends")
            meta_cols[1].write(format_date(h.get("end_at")))

            st.write(f"⏳ {format_time_remaining(h.get('end_at'))}")

            if h.get("prize_amount"):
                st.markdown(f"🏆 **Prize Pool:** {h['prize_amount']}")

            if best_match:
                st.markdown(
                    f"**Best Matching Project:** {best_match['project']['title']} "
                    f"— {best_match['score']}% match"
                )

        with action_col:
            if h.get("registration_link"):
                st.link_button("Register", h["registration_link"], width="stretch")
            if profile.is_admin:
                if st.button("Delete", key=f"delete_hackathon_{h['id']}", width="stretch"):
                    delete_hackathon(client, h["id"])
                    get_active_hackathons_refresh(client)
                    st.rerun()
            if st.button("Full AI match →", key=f"match_{h['id']}", width="stretch"):
                st.session_state["pending_chat_prompt"] = (
                    f"What's the best matching project for {h['name']}?"
                )
                st.switch_page("pages/ai_chat.py")


render()
