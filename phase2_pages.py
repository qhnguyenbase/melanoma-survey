from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

from utils import (
    cleanup_result_artifacts,
    DATA_DIR,
    ensure_response_timer,
    get_phase2_question_images,
    get_response_time_seconds,
    init_session,
    run_model,
    save_to_csv,
    use_phase2_model_defaults,
)


def render_phase2_intro() -> None:
    st.set_page_config(page_title="Phase 2", page_icon="🧪", layout="centered")

    init_session()

    st.title("Phase 2: AI-Assisted Diagnosis")

    st.markdown(
        """
        In Phase 2, each question follows the same workflow:

        1. Review the assigned dermoscopic image for that question.
        2. Click **Run inference** to generate the AI prediction.
        3. Review the AI prediction shown on the page.
        4. Choose your diagnosis: `Benign` or `Melanoma`.
        5. Set your confidence level from 0% to 100% and submit.
        """
    )

    st.markdown("### How to review the image and get a prediction")
    st.markdown(
        """
        1. Open a Phase 2 question page from the sidebar or click the button below.
        2. Review the image shown on the page for that question.
        3. Click `Run inference`.
        4. The app will run the melanoma prediction model on that question image.
        5. The prediction will appear on the page as `Benign` or `Melanoma`, with an estimated melanoma risk when available.
        6. After reviewing the prediction, choose your own diagnosis and confidence level, then click `Submit`.
        """
    )
    st.caption("Phase 2 uses the fixed image set stored in `app/images/phase_2/`.")

    if st.button("Go to Phase 2 Question 1", type="primary"):
        st.switch_page("pages/10_Phase_2_Question_1.py")


def render_phase2_question(question_number: int, total_questions: int = 8) -> None:
    st.set_page_config(
        page_title=f"Phase 2 Question {question_number}",
        page_icon="🧪",
        layout="centered",
    )

    init_session()

    st.markdown(
        f"### Phase 2 - Question {question_number}: Review the image and the AI prediction."
    )
    st.caption(
        "Review the assigned Phase 2 image, run inference, then choose your diagnosis and confidence."
    )

    question_key = f"ph2_q{question_number}"
    result_key = f"{question_key}_result"
    timer_key = f"{question_key}_timer"
    ensure_response_timer(timer_key)

    image_paths = get_phase2_question_images(total_questions=total_questions)

    if not image_paths:
        st.error(
            "No supported images found in `app/images/phase_2/`. Please add your dermoscopic images there."
        )
        st.stop()

    if len(image_paths) < question_number:
        st.error(
            f"Not enough supported images found in `app/images/phase_2/` for Question {question_number}. "
            f"Found {len(image_paths)}."
        )
        st.stop()

    image_path = image_paths[question_number - 1]
    st.image(
        image_path,
        caption=f"Question image: {Path(image_path).name}",
        use_container_width=True,
    )

    if st.button(
        "Run inference",
        type="primary",
        key=f"{question_key}_infer",
    ):
        use_phase2_model_defaults()
        with st.spinner("Running inference..."):
            try:
                result = run_model(img_path=image_path, image_name=Path(image_path).name)
            except Exception as exc:
                _clear_phase2_result(question_key)
                st.error(f"Inference failed: {exc}")
            else:
                cleanup_result_artifacts(result)
                st.session_state[result_key] = result
                st.success("Inference complete.")

    result = st.session_state.get(result_key)
    if result:
        _render_phase2_prediction(result)
    else:
        st.warning("Run inference to view the AI prediction before submitting your answer.")

    answer = st.radio(
        "Diagnosis",
        ["Benign", "Melanoma"],
        horizontal=True,
        label_visibility="collapsed",
        key=f"{question_key}_answer_input",
        disabled=result is None,
    )

    st.markdown("#### Confidence level")
    confidence = st.slider(
        "How confident are you in your answer? (0% = not confident, 100% = very confident)",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        key=f"{question_key}_confidence_input",
        disabled=result is None,
    )

    if st.button(
        "Submit",
        type="primary",
        key=f"{question_key}_submit",
        disabled=result is None,
    ):
        st.session_state[f"{question_key}_answer"] = answer
        st.session_state[f"{question_key}_confidence"] = confidence

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response_time_seconds = get_response_time_seconds(timer_key, reset=True)
        name = st.session_state.get("name")
        email = st.session_state.get("email")
        headers = [
            "Timestamp",
            "Name",
            "Email",
            "Question",
            "UploadedImage",
            "ModelPrediction",
            "ModelMelanomaRisk",
            "Answer",
            "Confidence",
            "ResponseTimeSeconds",
        ]
        save_to_csv(
            DATA_DIR / "phase2_responses.csv",
            [
                timestamp,
                name,
                email,
                f"PH2_Q{question_number}",
                Path(image_path).name,
                result.get("prediction"),
                _format_risk(result.get("prob_melanoma")),
                answer,
                confidence,
                response_time_seconds,
            ],
            headers,
        )

        if question_number < total_questions:
            st.success("Saved your answer. Use the sidebar to continue to the next Phase 2 question.")
        else:
            st.success("Saved your answer. Phase 2 is complete. Use the sidebar to continue to Phase 3.")


def _render_phase2_prediction(result: dict[str, Any]) -> None:
    st.markdown("#### AI prediction")

    prediction = result.get("prediction") or "Unavailable"
    st.success(f"Prediction: {prediction}")

    prob_melanoma = result.get("prob_melanoma")
    if isinstance(prob_melanoma, (int, float)):
        st.caption(f"Estimated melanoma risk: {float(prob_melanoma) * 100:.1f}%")


def _clear_phase2_result(question_key: str) -> None:
    result = st.session_state.pop(f"{question_key}_result", None)
    cleanup_result_artifacts(result)


def _format_risk(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return f"{float(value) * 100:.1f}%"
    return None
