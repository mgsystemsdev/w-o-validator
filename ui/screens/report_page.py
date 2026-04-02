"""Report screen: moving log and pending movings (UI scaffold)."""

from __future__ import annotations

import streamlit as st


def render_report_page() -> None:
    st.title("Report")

    tab_moving_log, tab_pending = st.tabs(["Moving Log", "Pending Movings"])

    with tab_moving_log:
        st.subheader("Moving Log")
        st.caption(
            "Placeholder: moving history and log views will be added here in a future update."
        )

    with tab_pending:
        st.subheader("Pending Movings")
        st.caption(
            "Placeholder: pending movings workflow will be added here in a future update."
        )
