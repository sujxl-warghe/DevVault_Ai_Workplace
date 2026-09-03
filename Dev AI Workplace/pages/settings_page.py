from __future__ import annotations

import streamlit as st

from services.admin_service import (
    AdminAPINotConfiguredError,
    UsernameTakenError,
    create_user,
    delete_user,
    generate_temp_password,
    list_all_profiles,
    reset_password,
    set_user_status,
)
from services.auth_service import InvalidUsernameError
from services.requests_service import (
    approve_deletion_request,
    approve_hackathon_request,
    approve_project_request,
    list_own_deletion_requests,
    list_own_hackathon_requests,
    list_own_project_requests,
    list_pending_deletion_requests,
    list_pending_hackathon_requests,
    list_pending_project_requests,
    reject_deletion_request,
    reject_hackathon_request,
    reject_project_request,
)
from services.state import (
    clear_gemini_key,
    get_active_hackathons,
    get_projects,
    get_settings,
    is_gemini_key_set,
    require_auth,
    save_gemini_key,
    sign_out_current_user,
)

STATUS_EMOJI = {"pending": "🟡 Pending", "approved": "🟢 Approved", "rejected": "🔴 Rejected"}


def render() -> None:
    st.title("⚙️ Settings")

    auth = require_auth()
    if not auth:
        return
    settings, client, profile = auth

    tab_names = ["Account", "Gemini API", "My Requests"]
    if profile.is_admin:
        tab_names += ["User Management", "Submission Requests", "Deletion Requests"]

    tabs = st.tabs(tab_names)

    with tabs[0]:
        _render_account(client, profile)
    with tabs[1]:
        _render_gemini_section()
    with tabs[2]:
        _render_my_requests(client, profile)

    if profile.is_admin:
        with tabs[3]:
            _render_user_management(client, settings, profile)
        with tabs[4]:
            _render_submission_requests(client, profile)
        with tabs[5]:
            _render_deletion_requests(client, profile)


def _render_account(client, profile) -> None:
    st.subheader("Account")
    st.write(f"**Username:** {profile.username}")
    st.write(f"**Role:** {'Admin' if profile.is_admin else 'User'}")
    st.write("**Status:** 🟢 Active")
    if st.button("Sign out"):
        sign_out_current_user(client)
        st.rerun()


def _render_gemini_section() -> None:
    st.subheader("Gemini API Key")
    st.caption(
        "Your key is kept only in this browser session's memory — it is never written to "
        "Supabase or any file, and the app continues to work without it (AI Chat falls back "
        "to database-only recommendations)."
    )

    current_settings = get_settings()

    with st.form("gemini_key_form", clear_on_submit=False):
        new_key = st.text_input(
            "Gemini API Key",
            value=current_settings.gemini_api_key or "",
            type="password",
            placeholder="AIza...",
            label_visibility="collapsed",
        )
        col1, col2 = st.columns(2)
        save_clicked = col1.form_submit_button("Save API Key", width="stretch")
        clear_clicked = col2.form_submit_button("Clear API Key", width="stretch")

        if save_clicked:
            if new_key.strip():
                save_gemini_key(new_key)
                st.success("Gemini API key saved for this session.")
                st.rerun()
            else:
                st.warning("Enter a key before saving.")

        if clear_clicked:
            clear_gemini_key()
            st.info("Gemini API key cleared.")
            st.rerun()

    if is_gemini_key_set():
        st.success("✓ Gemini configured")
    else:
        st.warning("⚠ Gemini API key not configured")


def _render_my_requests(client, profile) -> None:
    st.subheader("My Requests")

    project_reqs = [(r, "Project") for r in list_own_project_requests(client, profile.id)]
    hackathon_reqs = [(r, "Hackathon") for r in list_own_hackathon_requests(client, profile.id)]
    deletion_reqs = [(r, "Deletion") for r in list_own_deletion_requests(client, profile.id)]

    all_reqs = project_reqs + hackathon_reqs + deletion_reqs
    all_reqs.sort(key=lambda pair: pair[0].get("created_at") or "", reverse=True)

    if not all_reqs:
        st.info("You haven't submitted any requests yet.")
        return

    for req, kind in all_reqs:
        with st.container(border=True):
            name = req.get("title") or req.get("name") or f"Project #{str(req.get('project_id', ''))[:8]}"
            st.markdown(f"**{name}** — {kind}")
            st.write(STATUS_EMOJI.get(req["status"], req["status"]))
            st.caption(f"Submitted: {req.get('created_at', '—')}")
            if req.get("reviewed_at"):
                st.caption(f"Reviewed: {req['reviewed_at']}")
            if req["status"] == "rejected" and req.get("rejection_reason"):
                st.caption(f"Reason: {req['rejection_reason']}")


def _render_user_management(client, settings, profile) -> None:
    st.subheader("User Management")

    if not settings.admin_api_configured:
        st.error(
            "Creating/resetting/deleting users requires SUPABASE_SERVICE_ROLE_KEY to be set "
            "as a server-side environment variable (never entered here). Activate/deactivate "
            "still works without it."
        )

    with st.expander("➕ Create User", expanded=False):
        with st.form("create_user_form", clear_on_submit=True):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            role = st.selectbox("Role", ["user", "admin"], index=0)

            submitted = st.form_submit_button("Create User", width="stretch")
            if submitted:
                if not username.strip() or not password:
                    st.error("Username and password are required.")
                elif password != confirm_password:
                    st.error("Passwords do not match.")
                elif len(password) < 8:
                    st.error("Password must be at least 8 characters.")
                else:
                    try:
                        result = create_user(settings, username, password, role)
                        st.success(f"User '{result.username}' created.")
                        st.rerun()
                    except InvalidUsernameError as exc:
                        st.error(str(exc))
                    except UsernameTakenError as exc:
                        st.error(str(exc))
                    except AdminAPINotConfiguredError as exc:
                        st.error(str(exc))
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't create user: {exc}")

    st.divider()
    users = list_all_profiles(client)
    st.caption(f"{len(users)} user(s)")

    for u in users:
        with st.container(border=True):
            cols = st.columns([2, 1, 1, 1])
            cols[0].write(f"**{u['username']}**")
            cols[1].write("Admin" if u["role"] == "admin" else "User")
            cols[2].write("🟢 Active" if u["status"] == "active" else "🔴 Inactive")
            cols[3].caption(u.get("created_at", "—"))

            is_self = u["id"] == profile.id
            action_cols = st.columns(4)

            if u["status"] == "active":
                if action_cols[0].button("Deactivate", key=f"deact_{u['id']}", disabled=is_self, width="stretch"):
                    set_user_status(client, u["id"], "inactive")
                    st.rerun()
            else:
                if action_cols[0].button("Activate", key=f"act_{u['id']}", width="stretch"):
                    set_user_status(client, u["id"], "active")
                    st.rerun()

            reset_key = f"resetting_{u['id']}"
            if action_cols[1].button("Reset Password", key=f"resetbtn_{u['id']}", width="stretch"):
                st.session_state[reset_key] = True

            if action_cols[3].button("Delete User", key=f"del_{u['id']}", disabled=is_self, width="stretch"):
                try:
                    delete_user(settings, u["id"])
                    st.success(f"Deleted {u['username']}.")
                    st.rerun()
                except AdminAPINotConfiguredError as exc:
                    st.error(str(exc))
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Couldn't delete user: {exc}")

            if st.session_state.get(reset_key):
                with st.form(f"reset_form_{u['id']}"):
                    new_password = st.text_input("New password", type="password", key=f"newpw_{u['id']}")
                    gen = st.form_submit_button("Generate random password")
                    apply_btn = st.form_submit_button("Apply", width="stretch")
                    if gen:
                        st.session_state[f"newpw_{u['id']}"] = generate_temp_password()
                        st.rerun()
                    if apply_btn:
                        if not new_password or len(new_password) < 8:
                            st.error("Enter a password of at least 8 characters, or click Generate.")
                        else:
                            try:
                                reset_password(settings, u["id"], new_password)
                                st.success(f"Password reset for {u['username']}. Share it with them securely.")
                                st.session_state[reset_key] = False
                            except AdminAPINotConfiguredError as exc:
                                st.error(str(exc))
                            except Exception as exc:  # noqa: BLE001
                                st.error(f"Couldn't reset password: {exc}")


def _render_submission_requests(client, profile) -> None:
    st.subheader("Submission Requests")
    sub_tabs = st.tabs(["Project Requests", "Hackathon Requests"])

    with sub_tabs[0]:
        pending = list_pending_project_requests(client)
        if not pending:
            st.info("No pending project requests.")
        for req in pending:
            with st.container(border=True):
                st.markdown(f"**Project:** {req['title']}")
                if req.get("details"):
                    st.write(f"**Details:** {req['details']}")
                if req.get("repo_link"):
                    st.write(f"**Repo:** {req['repo_link']}")
                if req.get("live_link"):
                    st.write(f"**Live:** {req['live_link']}")
                st.caption(f"Submitted: {req.get('created_at', '—')}")

                cols = st.columns(2)
                if cols[0].button("Approve", key=f"approve_proj_{req['id']}", width="stretch"):
                    try:
                        approve_project_request(client, req["id"], profile.id)
                        get_projects(client, force_refresh=True)
                        st.success("Approved.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't approve: {exc}")

                reject_key = f"rejecting_proj_{req['id']}"
                if cols[1].button("Reject", key=f"reject_proj_btn_{req['id']}", width="stretch"):
                    st.session_state[reject_key] = True
                if st.session_state.get(reject_key):
                    reason = st.text_input("Rejection reason (optional)", key=f"reason_proj_{req['id']}")
                    if st.button("Confirm Reject", key=f"confirm_reject_proj_{req['id']}"):
                        reject_project_request(client, req["id"], profile.id, reason.strip() or None)
                        st.session_state[reject_key] = False
                        st.rerun()

    with sub_tabs[1]:
        pending = list_pending_hackathon_requests(client)
        if not pending:
            st.info("No pending hackathon requests.")
        for req in pending:
            with st.container(border=True):
                if req.get("template_photo"):
                    try:
                        st.image(req["template_photo"], width=200)
                    except Exception:
                        pass
                st.markdown(f"**Hackathon:** {req['name']}")
                st.write(f"**Starting:** {req.get('start_time') or 'not set'}")
                st.write(f"**Ending:** {req.get('end_time') or 'not set'}")
                if req.get("registration_link"):
                    st.write(f"**Registration:** {req['registration_link']}")
                if req.get("prize_pool"):
                    st.write(f"**Prize Pool:** {req['prize_pool']}")
                st.caption(f"Submitted: {req.get('created_at', '—')}")

                cols = st.columns(2)
                if cols[0].button("Approve", key=f"approve_hack_{req['id']}", width="stretch"):
                    try:
                        approve_hackathon_request(client, req["id"], profile.id)
                        get_active_hackathons(client, force_refresh=True)
                        st.success("Approved.")
                        st.rerun()
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Couldn't approve: {exc}")

                reject_key = f"rejecting_hack_{req['id']}"
                if cols[1].button("Reject", key=f"reject_hack_btn_{req['id']}", width="stretch"):
                    st.session_state[reject_key] = True
                if st.session_state.get(reject_key):
                    reason = st.text_input("Rejection reason (optional)", key=f"reason_hack_{req['id']}")
                    if st.button("Confirm Reject", key=f"confirm_reject_hack_{req['id']}"):
                        reject_hackathon_request(client, req["id"], profile.id, reason.strip() or None)
                        st.session_state[reject_key] = False
                        st.rerun()


def _render_deletion_requests(client, profile) -> None:
    st.subheader("Deletion Requests")
    pending = list_pending_deletion_requests(client)
    if not pending:
        st.info("No pending deletion requests.")
        return

    projects_by_id = {p["id"]: p for p in get_projects(client)}

    for req in pending:
        with st.container(border=True):
            project = projects_by_id.get(req["project_id"])
            st.markdown(f"**Project:** {project['title'] if project else req['project_id']}")
            if req.get("reason"):
                st.write(f"**Reason:** {req['reason']}")
            st.caption(f"Requested: {req.get('created_at', '—')}")

            cols = st.columns(2)
            if cols[0].button("Approve", key=f"approve_del_{req['id']}", width="stretch"):
                approve_deletion_request(client, req["id"], profile.id)
                get_projects(client, force_refresh=True)
                st.success("Approved — project deleted.")
                st.rerun()
            if cols[1].button("Reject", key=f"reject_del_{req['id']}", width="stretch"):
                reject_deletion_request(client, req["id"], profile.id)
                st.success("Rejected — project kept.")
                st.rerun()


render()
