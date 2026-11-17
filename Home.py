"""
Landing page for participant registration.
"""

import streamlit as st

from utils import init_session, save_participant, sheets_status


def main() -> None:
    st.set_page_config(
        page_title="Doctor Participation Confirmation",
        page_icon="🩺",
        layout="centered",
    )

    init_session()

    st.title("Doctor Participation Confirmation")

    # Storage is checked on the landing page rather than left to fail silently
    # at submit time: on a hosted app the local filesystem is wiped on every
    # restart, so a broken Sheets connection means every response is lost.
    storage_ok, storage_detail = sheets_status()
    if not storage_ok:
        st.error(
            "**Responses are not being saved.** Please contact the researcher "
            "before starting.\n\n"
            f"Technical detail: {storage_detail}"
        )

    st.markdown(
        """
        ### Welcome to the Study
        Thank you for participating in this research project.

        **Privacy Notice:**
        - All data will be **anonymized** before analysis, and no personally identifiable information will be shared.
        - Your participation is voluntary.
        - You may withdraw at any time.
        - Please note that all models used in this survey are not clinically approved, they are only for research purposes.
        - The estimated time to finish this survey is about 30 minutes.
        """
    )

    with st.form("confirmation_form"):
        name = st.text_input("Full Name")
        email = st.text_input("Email Address")
        consent = st.checkbox("I agree to participate in this study.")
        submit = st.form_submit_button("Start Survey")

    if submit:
        if not name or not email or not consent:
            st.error("Please complete all fields.")
        else:
            save_participant(name, email)
            st.session_state.name = name
            st.session_state.email = email
            st.switch_page("pages/00_Introduction.py")


if __name__ == "__main__":
    main()
