from __future__ import annotations

from datetime import datetime

import streamlit as st

from utils import DATA_DIR, init_session, require_registration, save_to_csv


def render_thank_you_page() -> None:
    st.set_page_config(page_title="Thank You", page_icon="🩺", layout="centered")

    init_session()
    require_registration()

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
    st.text_area(
        "Share any feedback about your experience:",
        key="final_comment",
        max_chars=2000,
        placeholder="Type your comment here...",
    )

    # Saving runs as a button callback rather than inline. Streamlit refuses to
    # let a widget's session_state key be reassigned once that widget has been
    # instantiated in the current run, so clearing the box inline crashed the
    # page after every successful submit. Callbacks run before the widgets are
    # rebuilt, which is where the reset is allowed.
    st.button("Submit Comment", type="secondary", on_click=_save_comment)

    status = st.session_state.pop("comment_status", None)
    if status:
        level, message = status
        getattr(st, level)(message)


def _save_comment() -> None:
    comment = str(st.session_state.get("final_comment", "")).strip()
    if not comment:
        st.session_state.comment_status = (
            "warning",
            "Please enter a comment before submitting.",
        )
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [
        timestamp,
        st.session_state.get("name") or "",
        st.session_state.get("email") or "",
        comment,
    ]
    headers = ["Timestamp", "Name", "Email", "Comment"]
    save_to_csv(DATA_DIR / "comments.csv", row, headers)
    st.session_state.comment_status = ("success", "Thanks! Your comment has been saved.")
    st.session_state.final_comment = ""
