from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

from utils import (
    DATA_DIR,
    ensure_response_timer,
    get_phase1_question_images,
    get_response_time_seconds,
    init_session,
    save_to_csv,
)

PHASE1_RESPONSES_FILE = DATA_DIR / "phase1_responses.csv"


def render_phase1_intro() -> None:
    st.set_page_config(page_title="Phase 1", page_icon="🧪", layout="centered")

    init_session()

    st.title("Phase 1: Independent Diagnosis")

    st.markdown(
        """
        In Phase 1, each question follows the same workflow:

        1. Review one dermoscopic image without AI assistance.
        2. Choose your diagnosis: `Benign` or `Melanoma`.
        3. Set your confidence level from 0% to 100% and submit.
        """
    )

    st.markdown("### How Phase 1 works")
    st.markdown(
        """
        1. Open a Phase 1 question page from the sidebar or click the button below.
        2. Review the dermoscopic image shown on the page.
        3. Choose your diagnosis: `Benign` or `Melanoma`.
        4. Set your confidence level from 0% to 100%.
        5. Click `Submit` to save your answer and move to the next question.
        """
    )
    st.caption(
        "Phase 1 uses the fixed image set stored in `app/images/phase_1/`."
    )

    if st.button("Go to Phase 1 Question 1", type="primary"):
        st.switch_page("pages/1_question_1.py")


def render_phase1_question(question_number: int, total_questions: int = 8) -> None:
    st.set_page_config(
        page_title=f"Phase 1 Question {question_number}",
        page_icon="🧪",
        layout="centered",
    )

    init_session()

    st.markdown(
        f"### Phase 1 - Question {question_number}: Review the image and choose your diagnosis."
    )
    st.caption(
        "Review one dermoscopic image without AI assistance, then choose your diagnosis and confidence."
    )

    question_key = f"ph1_q{question_number}"
    timer_key = f"{question_key}_timer"
    ensure_response_timer(timer_key)

    image_paths = get_phase1_question_images(total_questions=total_questions)

    if not image_paths:
        st.error(
            "No supported images found in `app/images/phase_1/`. Please add your dermoscopic images there."
        )
        st.stop()

    if len(image_paths) < question_number:
        st.error(
            f"Not enough supported images found in `app/images/phase_1/` for Question {question_number}. "
            f"Found {len(image_paths)}."
        )
        st.stop()

    image_path = image_paths[question_number - 1]
    st.image(
        image_path,
        caption=f"Question image: {Path(image_path).name}",
        use_container_width=True,
    )

    answer = st.radio(
        "Diagnosis",
        ["Benign", "Melanoma"],
        horizontal=True,
        label_visibility="collapsed",
        key=f"{question_key}_answer_input",
    )

    st.markdown("#### Confidence level")
    confidence = st.slider(
        "How confident are you in your answer? (0% = not confident, 100% = very confident)",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        key=f"{question_key}_confidence_input",
    )

    if st.button("Submit", type="primary", key=f"{question_key}_submit"):
        st.session_state[f"q{question_number}_answer"] = answer
        st.session_state[f"q{question_number}_confidence"] = confidence

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response_time_seconds = get_response_time_seconds(timer_key, reset=True)
        name = st.session_state.get("name")
        email = st.session_state.get("email")

        headers = [
            "Timestamp",
            "Name",
            "Email",
            "Question",
            "Answer",
            "Confidence",
            "ResponseTimeSeconds",
        ]
        save_to_csv(
            PHASE1_RESPONSES_FILE,
            [
                timestamp,
                name,
                email,
                f"Q{question_number}",
                answer,
                confidence,
                response_time_seconds,
            ],
            headers,
        )

        if question_number < total_questions:
            st.success(
                "Saved your answer. Use the sidebar to continue to the next Phase 1 question."
            )
        else:
            st.success(
                "Saved your answer. Phase 1 is complete. Use the sidebar to continue to Phase 2."
            )
