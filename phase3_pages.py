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
    get_phase3_question_images,
    get_response_time_seconds,
    init_session,
    render_pdf_in_ui,
    run_model,
    save_to_csv,
    use_phase3_model_defaults,
)
# English keys throughout: they match what the model cache produces, and are
# translated for display by i18n.checklist_rows.
CHECKLIST_TABLE_COLUMNS_BY_WIDTH: dict[int, list[str]] = {
    5: ["Attribute", "Prediction", "State", "Points", "Probability (%)"],
    6: ["Attribute", "Prediction", "State", "Points", "Attr score", "Probability (%)"],
}


def render_phase3_intro() -> None:
    st.set_page_config(page_title="Giai đoạn 3", page_icon="🧪", layout="centered")

    init_session()
    require_registration()

    st.title("Giai đoạn 3: Dự đoán của AI kèm giải thích dạng PDF")

    st.markdown(
        """
        Ở Giai đoạn 3, mỗi câu hỏi đều theo quy trình sau:

        1. Xem ảnh soi da được gán cho câu hỏi đó.
        2. Bấm **Chạy mô hình**.
        3. Xem dự đoán của AI và bản giải thích dạng PDF do mô hình tạo ra.
        4. Chọn chẩn đoán của Quý bác sĩ: `Lành tính` hoặc `U hắc tố ác tính (Melanoma)`.
        5. Đặt mức độ tự tin từ 0% đến 100% rồi gửi câu trả lời.
        """
    )

    st.markdown("### Cách xem ảnh và phần giải thích")
    st.markdown(
        """
        1. Bấm nút bên dưới để bắt đầu các câu hỏi của Giai đoạn 3.
        2. Xem ảnh hiển thị trên trang của câu hỏi đó.
        3. Bấm `Chạy mô hình`.
        4. Ứng dụng sẽ chạy mô hình trên ảnh của câu hỏi đó và tạo ra dự đoán kèm bản giải thích dạng PDF.
        5. Hãy xem kỹ dự đoán và bản giải thích PDF hiển thị trên trang trước khi gửi câu trả lời.
        """
    )
    st.caption("Giai đoạn 3 sử dụng bộ ảnh cố định được lưu trong `app/images/phase_3/`.")

    st.markdown("### Những điểm giữ nguyên như trước")
    st.markdown(
        """
        - 8 câu hỏi
        - 2 lựa chọn chẩn đoán: `Lành tính` và `U hắc tố ác tính (Melanoma)`
        - Thanh trượt mức độ tự tin từ 0% đến 100%
        """
    )

    if st.button("Đến câu hỏi 1 của Giai đoạn 3", type="primary"):
        st.switch_page("pages/19_Phase_3_Question_1.py")


def render_phase3_question(question_number: int, total_questions: int = 8) -> None:
    st.set_page_config(
        page_title=f"Giai đoạn 3 - Câu {question_number}",
        page_icon="🧪",
        layout="centered",
    )

    init_session()
    require_registration()

    st.markdown(
        f"### Giai đoạn 3 - Câu {question_number}: Xem ảnh, dự đoán và bản giải thích PDF."
    )
    st.caption(
        "Xem ảnh của Giai đoạn 3, chạy mô hình, xem bản giải thích PDF, sau đó chọn chẩn đoán và mức độ tự tin."
    )

    question_key = f"ph3_q{question_number}"
    result_key = f"{question_key}_result"
    timer_key = f"{question_key}_timer"
    ensure_response_timer(timer_key)

    image_paths = get_phase3_question_images(total_questions=total_questions)

    if not image_paths:
        st.error(
            "Không tìm thấy ảnh hợp lệ trong `app/images/phase_3/`. Vui lòng thông báo cho nhóm nghiên cứu."
        )
        st.stop()

    if len(image_paths) < question_number:
        st.error(
            f"Không đủ ảnh hợp lệ trong `app/images/phase_3/` cho Câu {question_number}. "
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
        use_phase3_model_defaults()
        with st.spinner("Đang chạy mô hình và tạo bản giải thích PDF..."):
            try:
                result = run_model(img_path=image_path, image_name=Path(image_path).name)
            except Exception as exc:
                _clear_phase3_result(question_key)
                st.error(f"Chạy mô hình thất bại: {exc}")
            else:
                st.session_state[result_key] = result
                st.success("Đã chạy xong mô hình. Dự đoán và phần giải thích đã sẵn sàng.")

    result = st.session_state.get(result_key)
    if result:
        _render_phase3_prediction(result)
    else:
        st.warning("Hãy chạy mô hình để xem dự đoán và phần giải thích của AI trước khi gửi câu trả lời.")

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
            "ExplanationPdf",
            "Answer",
            "Confidence",
            "ResponseTimeSeconds",
        ]
        save_to_csv(
            DATA_DIR / "phase3_responses.csv",
            [
                timestamp,
                name,
                email,
                f"PH3_Q{question_number}",
                Path(image_path).name,
                result.get("prediction"),
                _format_risk(result.get("prob_melanoma")),
                None,
                answer,
                confidence,
                response_time_seconds,
            ],
            headers,
        )
        cleanup_result_artifacts(result)

        submitted = True

    if submitted:
        if question_number < total_questions:
            st.success("Đã lưu câu trả lời của Quý bác sĩ.")
        else:
            st.success("Đã lưu câu trả lời. Giai đoạn 3 đã hoàn tất.")
        render_next_button(
            f"pages/{18 + question_number}_Phase_3_Question_{question_number}.py",
            "Câu hỏi tiếp theo" if question_number < total_questions else "Tiếp tục sang Giai đoạn 4",
        )


def _render_phase3_prediction(result: dict[str, Any]) -> None:
    st.markdown("#### Dự đoán của AI")
    st.markdown(
        "### Mô hình đề nghị đánh giá thêm nếu tổng điểm soi da từ 3 trở lên."
    )

    prediction = result.get("prediction") or "Unavailable"
    st.success(f"Dự đoán: {i18n.diagnosis(prediction)}")

    prob_melanoma = result.get("prob_melanoma")
    if isinstance(prob_melanoma, (int, float)):
        st.caption(f"Nguy cơ u hắc tố ác tính ước tính: {float(prob_melanoma) * 100:.1f}%")

    explanation_image = result.get("explanation_image")
    if explanation_image:
        st.markdown("#### Xem trước phần giải thích")
        st.image(
            explanation_image,
            caption="Bản xem trước phần giải thích được tạo từ kết quả của mô hình",
            use_container_width=True,
        )

    checklist_table = result.get("checklist_table")
    table_rows = _normalize_checklist_table_rows(checklist_table)
    if table_rows:
        st.markdown("#### Điểm của từng đặc điểm")
        st.dataframe(
            i18n.checklist_rows(table_rows),
            hide_index=True,
            use_container_width=True,
        )

    st.markdown("#### Bản giải thích PDF")
    explanation_pdf = result.get("explanation_pdf")
    if explanation_pdf:
        pdf_path = Path(explanation_pdf)
        if pdf_path.exists():
            st.download_button(
                "Tải bản giải thích PDF",
                data=pdf_path.read_bytes(),
                file_name=pdf_path.name,
                mime="application/pdf",
                key=f"download_{pdf_path.stem}",
            )
        else:
            st.warning(f"Không tìm thấy bản giải thích PDF: {pdf_path}")
    else:
        st.warning("Lần chạy này không tạo ra bản giải thích PDF.")


def _clear_phase3_result(question_key: str) -> None:
    result = st.session_state.pop(f"{question_key}_result", None)
    cleanup_result_artifacts(result)


def _format_risk(value: Any) -> str | None:
    if isinstance(value, (int, float)):
        return f"{float(value) * 100:.1f}%"
    return None


def _normalize_checklist_table_rows(checklist_table: Any) -> list[dict[str, Any]]:
    if not isinstance(checklist_table, list) or not checklist_table:
        return []

    first_row = checklist_table[0]
    if isinstance(first_row, dict):
        return [row for row in checklist_table if isinstance(row, dict)]

    if not isinstance(first_row, (list, tuple)):
        return []

    headers = CHECKLIST_TABLE_COLUMNS_BY_WIDTH.get(len(first_row))
    if not headers:
        return []

    rows: list[dict[str, Any]] = []
    for row in checklist_table:
        if not isinstance(row, (list, tuple)):
            continue
        values = list(row[: len(headers)])
        if len(values) < len(headers):
            values.extend([None] * (len(headers) - len(values)))
        rows.append(dict(zip(headers, values)))
    return rows
