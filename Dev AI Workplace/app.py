"""DevVault AI Workspace — entrypoint.

Run with: streamlit run app.py
"""
from __future__ import annotations

import streamlit as st

st.set_page_config(
    page_title="DevVault AI Workspace",
    page_icon="🗂️",
    layout="wide",
    initial_sidebar_state="expanded",
)

pages = [
    st.Page("pages/dashboard.py", title="Dashboard", icon="🏠", default=True),
    st.Page("pages/projects.py", title="Projects", icon="📂"),
    st.Page("pages/hackathons.py", title="Hackathons", icon="🏆"),
    st.Page("pages/ai_chat.py", title="AI Chat", icon="🤖"),
    st.Page("pages/export_page.py", title="Export", icon="📥"),
    st.Page("pages/settings_page.py", title="Settings", icon="⚙️"),
]

with st.sidebar:
    st.markdown("## 🗂️ DevVault")
    st.caption("Multi-user hackathon workspace")
    st.divider()

nav = st.navigation(pages)
nav.run()
