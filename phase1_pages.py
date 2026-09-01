from __future__ import annotations

from datetime import datetime
from pathlib import Path

import streamlit as st

import i18n
from utils import (
    require_registration,
    already_submitted,
    mark_submitted,
    render_next_button,
    require_registration,
    DATA_DIR,
    ensure_response_timer,
    get_phase1_question_images,
    get_response_time_seconds,
    init_session,
    save_to_csv,
)

PHASE1_RESPONSES_FILE = DATA_DIR / "phase1_responses.csv"


def render_phase1_intro() -> None:
    st.set_page_config(page_title="Giai đoạn 1", page_icon="🧪", layout="centered")

    init_session()
    require_registration()

    st.title("Giai đoạn 1: Chẩn đoán độc lập")

    st.markdown(
        """
        Ở Giai đoạn 1, mỗi câu hỏi đều theo cùng một quy trình:

        1. Xem một ảnh soi da (dermoscopy), không có hỗ trợ của AI.
        2. Chọn chẩn đoán của Quý bác sĩ: `Lành tính` hoặc `U hắc tố ác tính (Melanoma)`.
        3. Đặt mức độ tự tin từ 0% đến 100% rồi gửi câu trả lời.
        """
    )

    st.markdown("### Giai đoạn 1 diễn ra như thế nào")
    st.markdown(
        """
        1. Bấm nút bên dưới để bắt đầu các câu hỏi của Giai đoạn 1.
        2. Xem ảnh soi da hiển thị trên trang.
        3. Chọn chẩn đoán của Quý bác sĩ: `Lành tính` hoặc `U hắc tố ác tính (Melanoma)`.
        4. Đặt mức độ tự tin từ 0% đến 100%.
        5. Bấm `Gửi câu trả lời` để lưu và chuyển sang câu hỏi tiếp theo.
        """
    )
    st.caption(
        "Giai đoạn 1 sử dụng bộ ảnh cố định được lưu trong `app/images/phase_1/`."
    )

    if st.button("Đến câu hỏi 1 của Giai đoạn 1", type="primary"):
        st.switch_page("pages/1_question_1.py")


def render_phase1_question(question_number: int, total_questions: int = 8) -> None:
    st.set_page_config(
        page_title=f"Giai đoạn 1 - Câu {question_number}",
        page_icon="🧪",
        layout="centered",
    )

    init_session()
    require_registration()

    st.markdown(
        f"### Giai đoạn 1 - Câu {question_number}: Xem ảnh và chọn chẩn đoán của Quý bác sĩ."
    )
    st.caption(
        "Xem một ảnh soi da mà không có hỗ trợ của AI, sau đó chọn chẩn đoán và mức độ tự tin."
    )

    question_key = f"ph1_q{question_number}"
    timer_key = f"{question_key}_timer"
    ensure_response_timer(timer_key)

    image_paths = get_phase1_question_images(total_questions=total_questions)

    if not image_paths:
        st.error(
            "Không tìm thấy ảnh hợp lệ trong `app/images/phase_1/`. Vui lòng thông báo cho nhóm nghiên cứu."
        )
        st.stop()

    if len(image_paths) < question_number:
        st.error(
            f"Không đủ ảnh hợp lệ trong `app/images/phase_1/` cho Câu {question_number}. "
            f"Hiện có {len(image_paths)} ảnh."
        )
        st.stop()

    image_path = image_paths[question_number - 1]
    st.image(
        image_path,
        caption=f"Ảnh của câu hỏi: {Path(image_path).name}",
        use_container_width=True,
    )

    # The stored value stays English so the results spreadsheet and the analysis
    # scripts are unchanged by the translation; only the label is Vietnamese.
    answer = st.radio(
        "Chẩn đoán",
        ["Benign", "Melanoma"],
        format_func=i18n.diagnosis,
        horizontal=True,
        label_visibility="collapsed",
        key=f"{question_key}_answer_input",
    )

    st.markdown("#### Mức độ tự tin")
    confidence = st.slider(
        "Quý bác sĩ tự tin đến mức nào về câu trả lời của mình? (0% = không tự tin, 100% = rất tự tin)",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        key=f"{question_key}_confidence_input",
    )

    submitted = already_submitted(question_key)
    # `disabled` is presentation only -- a double click can still deliver a
    # second event, which is how the duplicate rows in the collected data
    # arose. The write path itself has to be idempotent.
    if st.button("Gửi câu trả lời", type="primary", key=f"{question_key}_submit",
                 disabled=submitted) and not submitted:
        st.session_state[f"q{question_number}_answer"] = answer
        st.session_state[f"q{question_number}_confidence"] = confidence
        mark_submitted(question_key)

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

        submitted = True

    if submitted:
        if question_number < total_questions:
            st.success("Đã lưu câu trả lời của Quý bác sĩ.")
        else:
            st.success("Đã lưu câu trả lời. Giai đoạn 1 đã hoàn tất.")
        render_next_button(
            f"pages/{question_number}_question_{question_number}.py",
            "Câu hỏi tiếp theo" if question_number < total_questions else "Tiếp tục sang Giai đoạn 2",
        )
