from __future__ import annotations

import pandas as pd
import streamlit as st

from services.projects_service import (
    DuplicateProjectError,
    create_project,
    delete_project,
    search_projects,
    update_project,
)
from services.requests_service import DuplicatePendingRequestError, submit_deletion_request, submit_project_request
from services.state import get_current_user_id, get_projects, require_auth

DISPLAY_COLUMNS = {
    "title": "Title",
    "problem_solved": "Problem Solved",
    "description": "Details",
    "github_url": "Repo Link",
    "demo_url": "Live Link",
}


def render() -> None:
    st.title("📂 Projects")
    st.caption("Shared with every DevVault user.")

    auth = require_auth()
    if not auth:
        return
    settings, client, profile = auth

    if profile.is_admin:
        _render_admin_add_form(client)
    else:
        _render_user_submit_form(client, profile)

    st.divider()

    projects = get_projects(client)
    query = st.text_input("Search title or details", "")
    filtered = search_projects(projects, query) if query else projects

    st.caption(f"{len(filtered)} of {len(projects)} project(s)")

    if not filtered:
        st.info(
            "No projects in DevVault yet."
            if not projects
            else "No projects match your search."
        )
        return

    for project in filtered:
        _render_project_card(client, project, profile)

    with st.expander("View as table"):
        df = pd.DataFrame(filtered)
        keep = [c for c in DISPLAY_COLUMNS if c in df.columns]
        df = df[keep].rename(columns=DISPLAY_COLUMNS)
        st.dataframe(df, width="stretch", hide_index=True)


def _render_admin_add_form(client) -> None:
    with st.expander("➕ Add Project", expanded=False):
        with st.form("add_project_form", clear_on_submit=True):
            title = st.text_input("Title *")
            details = st.text_area("Details", height=100)
            repo_link = st.text_input("Repo Link")
            live_link = st.text_input("Live Link")

            submitted = st.form_submit_button("Add Project", width="stretch")
            if submitted:
                if not title.strip():
                    st.error("Title is required.")
                else:
                    try:
                        user_id = get_current_user_id(client)
                        create_project(
                            client,
                            {
                                "title": title.strip(),
                                "problem_solved": None,
                                "description": details.strip() or None,
                                "tags": None,
                                "github_url": repo_link.strip() or None,
                                "demo_url": live_link.strip() or None,
                                "devpost_url": None,
                            },
                            user_id,
                        )
                        get_projects(client, force_refresh=True)
                        st.success(f"Added {title}.")
                        st.rerun()
                    except DuplicateProjectError:
                        st.error("A project with this identifier already exists.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't add project: {exc}")


def _render_user_submit_form(client, profile) -> None:
    with st.expander("➕ Add Project", expanded=False):
        st.caption("Your submission will be reviewed by an admin before it appears for everyone.")
        with st.form("submit_project_form", clear_on_submit=True):
            title = st.text_input("Title *")
            details = st.text_area("Details", height=100)
            repo_link = st.text_input("Repo Link")
            live_link = st.text_input("Live Link")

            submitted = st.form_submit_button("Submit for Approval", width="stretch")
            if submitted:
                if not title.strip():
                    st.error("Title is required.")
                else:
                    try:
                        submit_project_request(
                            client,
                            profile.id,
                            title.strip(),
                            details.strip() or None,
                            repo_link.strip() or None,
                            live_link.strip() or None,
                        )
                        st.success("Submitted for admin approval. Track it under Settings → My Requests.")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't submit request: {exc}")


def _render_project_card(client, project: dict, profile) -> None:
    editing_key = f"editing_{project['id']}"
    is_editing = st.session_state.get(editing_key, False)

    with st.container(border=True):
        if is_editing and profile.is_admin:
            _render_edit_form(client, project, editing_key)
            return

        cols = st.columns([3, 1])
        with cols[0]:
            st.markdown(f"**{project['title']}**")
            if project.get("problem_solved"):
                st.markdown(f"**Problem Solved:** {project['problem_solved']}")
            if project.get("description"):
                st.markdown(f"**Details:** {project['description']}")
        with cols[1]:
            if project.get("github_url"):
                st.link_button("Repo Link", project["github_url"], width="stretch")
            if project.get("demo_url"):
                st.link_button("Live Link", project["demo_url"], width="stretch")

            if profile.is_admin:
                action_cols = st.columns(2)
                if action_cols[0].button("Edit", key=f"edit_{project['id']}", width="stretch"):
                    st.session_state[editing_key] = True
                    st.rerun()
                if action_cols[1].button("Delete", key=f"delete_{project['id']}", width="stretch"):
                    delete_project(client, project["id"])
                    get_projects(client, force_refresh=True)
                    st.rerun()
            else:
                _render_request_delete(client, project, profile)


def _render_request_delete(client, project: dict, profile) -> None:
    request_key = f"requesting_delete_{project['id']}"
    if not st.session_state.get(request_key):
        if st.button("Request Delete", key=f"reqdel_{project['id']}", width="stretch"):
            st.session_state[request_key] = True
            st.rerun()
        return

    with st.form(f"delete_reason_form_{project['id']}"):
        reason = st.text_input("Reason (optional)")
        col1, col2 = st.columns(2)
        submit = col1.form_submit_button("Submit Request", width="stretch")
        cancel = col2.form_submit_button("Cancel", width="stretch")
        if submit:
            try:
                submit_deletion_request(client, project["id"], profile.id, reason.strip() or None)
                st.session_state[request_key] = False
                st.success("Deletion request submitted.")
                st.rerun()
            except DuplicatePendingRequestError as exc:
                st.error(str(exc))
        if cancel:
            st.session_state[request_key] = False
            st.rerun()


def _render_edit_form(client, project: dict, editing_key: str) -> None:
    with st.form(f"edit_form_{project['id']}"):
        title = st.text_input("Title *", value=project.get("title") or "")
        details = st.text_area("Details", value=project.get("description") or "", height=100)
        repo_link = st.text_input("Repo Link", value=project.get("github_url") or "")
        live_link = st.text_input("Live Link", value=project.get("demo_url") or "")

        col1, col2 = st.columns(2)
        save_clicked = col1.form_submit_button("Save Changes", width="stretch")
        cancel_clicked = col2.form_submit_button("Cancel", width="stretch")

        if save_clicked:
            if not title.strip():
                st.error("Title is required.")
            else:
                try:
                    update_project(
                        client,
                        project["id"],
                        {
                            "title": title.strip(),
                            "description": details.strip() or None,
                            "github_url": repo_link.strip() or None,
                            "demo_url": live_link.strip() or None,
                        },
                    )
                    get_projects(client, force_refresh=True)
                    st.session_state[editing_key] = False
                    st.success("Saved.")
                    st.rerun()
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Couldn't save changes: {exc}")

        if cancel_clicked:
            st.session_state[editing_key] = False
            st.rerun()


render()
