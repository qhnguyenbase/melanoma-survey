from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st

import i18n
from utils import (
    require_registration,
    already_submitted,
    mark_submitted,
    render_next_button,
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
    st.set_page_config(page_title="Giai đoạn 2", page_icon="🧪", layout="centered")

    init_session()
    require_registration()

    st.title("Giai đoạn 2: Chẩn đoán có hỗ trợ của AI")

    st.markdown(
        """
        Ở Giai đoạn 2, mỗi câu hỏi đều theo cùng một quy trình:

        1. Xem ảnh soi da được gán cho câu hỏi đó.
        2. Bấm **Chạy mô hình** để tạo dự đoán của AI.
        3. Xem dự đoán của AI hiển thị trên trang.
        4. Chọn chẩn đoán của Quý bác sĩ: `Lành tính` hoặc `U hắc tố ác tính (Melanoma)`.
        5. Đặt mức độ tự tin từ 0% đến 100% rồi gửi câu trả lời.
        """
    )

    st.markdown("### Cách xem ảnh và lấy dự đoán")
    st.markdown(
        """
        1. Bấm nút bên dưới để bắt đầu các câu hỏi của Giai đoạn 2.
        2. Xem ảnh hiển thị trên trang của câu hỏi đó.
        3. Bấm `Chạy mô hình`.
        4. Ứng dụng sẽ chạy mô hình dự đoán u hắc tố ác tính trên ảnh của câu hỏi đó.
        5. Dự đoán sẽ hiện trên trang dưới dạng `Lành tính` hoặc `U hắc tố ác tính (Melanoma)`, kèm theo nguy cơ ước tính khi có.
        6. Sau khi xem dự đoán, hãy chọn chẩn đoán và mức độ tự tin của chính Quý bác sĩ, rồi bấm `Gửi câu trả lời`.
        """
    )
    st.caption("Giai đoạn 2 sử dụng bộ ảnh cố định được lưu trong `app/images/phase_2/`.")

    if st.button("Đến câu hỏi 1 của Giai đoạn 2", type="primary"):
        st.switch_page("pages/10_Phase_2_Question_1.py")


def render_phase2_question(question_number: int, total_questions: int = 8) -> None:
    st.set_page_config(
        page_title=f"Giai đoạn 2 - Câu {question_number}",
        page_icon="🧪",
        layout="centered",
    )

    init_session()
    require_registration()

    st.markdown(
        f"### Giai đoạn 2 - Câu {question_number}: Xem ảnh và dự đoán của AI."
    )
    st.caption(
        "Xem ảnh của Giai đoạn 2, chạy mô hình, sau đó chọn chẩn đoán và mức độ tự tin."
    )

    question_key = f"ph2_q{question_number}"
    result_key = f"{question_key}_result"
    timer_key = f"{question_key}_timer"
    ensure_response_timer(timer_key)

    image_paths = get_phase2_question_images(total_questions=total_questions)

    if not image_paths:
        st.error(
            "Không tìm thấy ảnh hợp lệ trong `app/images/phase_2/`. Vui lòng thông báo cho nhóm nghiên cứu."
        )
        st.stop()

    if len(image_paths) < question_number:
        st.error(
            f"Không đủ ảnh hợp lệ trong `app/images/phase_2/` cho Câu {question_number}. "
            f"Hiện có {len(image_paths)} ảnh."
        )
        st.stop()

    image_path = image_paths[question_number - 1]
    st.image(
        image_path,
        caption=f"Ảnh của câu hỏi: {Path(image_path).name}",
        use_container_width=True,
    )

    if st.button(
        "Chạy mô hình",
        type="primary",
        key=f"{question_key}_infer",
    ):
        use_phase2_model_defaults()
        with st.spinner("Đang chạy mô hình..."):
            try:
                result = run_model(img_path=image_path, image_name=Path(image_path).name)
            except Exception as exc:
                _clear_phase2_result(question_key)
                st.error(f"Chạy mô hình thất bại: {exc}")
            else:
                cleanup_result_artifacts(result)
                st.session_state[result_key] = result
                st.success("Đã chạy xong mô hình.")

    result = st.session_state.get(result_key)
    if result:
        _render_phase2_prediction(result)
    else:
        st.warning("Hãy chạy mô hình để xem dự đoán của AI trước khi gửi câu trả lời.")

    # The stored value stays English so the results spreadsheet and the analysis
    # scripts are unchanged by the translation; only the label is Vietnamese.
    answer = st.radio(
        "Chẩn đoán",
        ["Benign", "Melanoma"],
        format_func=i18n.diagnosis,
        horizontal=True,
        label_visibility="collapsed",
        key=f"{question_key}_answer_input",
        disabled=result is None,
    )

    st.markdown("#### Mức độ tự tin")
    confidence = st.slider(
        "Quý bác sĩ tự tin đến mức nào về câu trả lời của mình? (0% = không tự tin, 100% = rất tự tin)",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        key=f"{question_key}_confidence_input",
        disabled=result is None,
    )

    submitted = already_submitted(question_key)
    # `disabled` is presentation only -- a double click can still deliver a
    # second event, which is how the duplicate rows in the collected data
    # arose. The write path itself has to be idempotent.
    if st.button(
        "Gửi câu trả lời",
        type="primary",
        key=f"{question_key}_submit",
        disabled=result is None or submitted,
    ) and not submitted:
        mark_submitted(question_key)
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

        submitted = True

    if submitted:
        if question_number < total_questions:
            st.success("Đã lưu câu trả lời của Quý bác sĩ.")
        else:
            st.success("Đã lưu câu trả lời. Giai đoạn 2 đã hoàn tất.")
        render_next_button(
            f"pages/{9 + question_number}_Phase_2_Question_{question_number}.py",
            "Câu hỏi tiếp theo" if question_number < total_questions else "Tiếp tục sang Giai đoạn 3",
        )


def _render_phase2_prediction(result: dict[str, Any]) -> None:
    st.markdown("#### Dự đoán của AI")

    prediction = result.get("prediction") or "Unavailable"
    st.success(f"Dự đoán: {i18n.diagnosis(prediction)}")

    prob_melanoma = result.get("prob_melanoma")
    if isinstance(prob_melanoma, (int, float)):
        st.caption(f"Nguy cơ u hắc tố ác tính ước tính: {float(prob_melanoma) * 100:.1f}%")


def _clear_phase2_result(question_key: str) -> None:
    result = st.session_state.pop(f"{question_key}_result", None)
    cleanup_result_artifacts(result)


def _format_risk(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return f"{float(value) * 100:.1f}%"
    return None
