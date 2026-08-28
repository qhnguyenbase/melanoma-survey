from __future__ import annotations

from datetime import datetime

import streamlit as st

from utils import DATA_DIR, init_session, save_to_csv


def render_thank_you_page() -> None:
    st.set_page_config(page_title="Thank You", page_icon="🩺", layout="centered")

    init_session()

    name = st.session_state.get("name")
    participant_label = f", {name}" if name else ""

    st.title("Thank You")
    st.markdown(
        f"""
        Thank you for completing the study{participant_label}.

        Your responses have been recorded. You may now close this page.
        """
    )

    st.info(
        "If you need to follow up about your participation, please contact the research team using the study details provided to you."
    )

    st.subheader("Optional Comment")
    comment = st.text_area(
        "Share any feedback about your experience:",
        key="final_comment",
        max_chars=2000,
        placeholder="Type your comment here...",
    )

    if st.button("Submit Comment", type="secondary"):
        cleaned_comment = comment.strip()
        if not cleaned_comment:
            st.warning("Please enter a comment before submitting.")
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            row = [
                timestamp,
                st.session_state.get("name") or "",
                st.session_state.get("email") or "",
                cleaned_comment,
            ]
            headers = ["Timestamp", "Name", "Email", "Comment"]
            save_to_csv(DATA_DIR / "comments.csv", row, headers)
            st.success("Thanks! Your comment has been saved.")
            st.session_state.final_comment = ""
