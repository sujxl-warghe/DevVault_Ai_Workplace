from __future__ import annotations

import streamlit as st

from services.export import export_projects_to_csv_bytes, export_projects_to_excel_bytes
from services.state import get_projects, require_auth


def render() -> None:
    st.title("📥 Export")
    st.caption("Export DevVault's shared projects to Excel or CSV.")

    auth = require_auth()
    if not auth:
        return
    settings, client, profile = auth

    projects = get_projects(client)
    st.metric("Projects available to export", len(projects))

    if not projects:
        st.info("No projects in DevVault yet.")
        return

    col1, col2 = st.columns(2)

    with col1:
        excel_bytes, excel_filename = export_projects_to_excel_bytes(projects)
        st.download_button(
            "Export to Excel",
            data=excel_bytes,
            file_name=excel_filename,
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            width="stretch",
        )

    with col2:
        csv_bytes, csv_filename = export_projects_to_csv_bytes(projects)
        st.download_button(
            "Export to CSV",
            data=csv_bytes,
            file_name=csv_filename,
            mime="text/csv",
            width="stretch",
        )

    with st.expander("Preview what will be exported"):
        st.write(
            [
                {
                    "Title": p.get("title"),
                    "Details": p.get("description"),
                    "Repo Link": p.get("github_url"),
                    "Live Link": p.get("demo_url"),
                }
                for p in projects
            ]
        )


render()
