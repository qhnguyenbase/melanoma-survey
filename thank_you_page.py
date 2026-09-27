from __future__ import annotations

from datetime import datetime

import streamlit as st

from utils import DATA_DIR, init_session, require_registration, save_to_csv


def render_thank_you_page() -> None:
    st.set_page_config(page_title="Cảm ơn Quý bác sĩ", page_icon="🩺", layout="centered")

    init_session()
    require_registration()

    name = st.session_state.get("name")
    participant_label = name or "Quý bác sĩ"

    st.title("Cảm ơn Quý bác sĩ")
    st.markdown(
        f"""
        Cảm ơn {participant_label} đã hoàn thành nghiên cứu này.

        Các câu trả lời của Quý bác sĩ đã được ghi nhận. Quý bác sĩ có thể đóng trang này.
        """
    )

    st.info(
        "Nếu cần trao đổi thêm về việc tham gia nghiên cứu, xin liên hệ nhóm nghiên cứu theo thông tin đã được cung cấp."
    )

    st.subheader("Ý kiến thêm (không bắt buộc)")
    st.text_area(
        "Xin chia sẻ nhận xét của Quý bác sĩ về trải nghiệm khi làm khảo sát:",
        key="final_comment",
        max_chars=2000,
        placeholder="Nhập ý kiến của Quý bác sĩ tại đây...",
    )

    # Saving runs as a button callback rather than inline. Streamlit refuses to
    # let a widget's session_state key be reassigned once that widget has been
    # instantiated in the current run, so clearing the box inline crashed the
    # page after every successful submit. Callbacks run before the widgets are
    # rebuilt, which is where the reset is allowed.
    st.button("Gửi ý kiến", type="secondary", on_click=_save_comment)

    status = st.session_state.pop("comment_status", None)
    if status:
        level, message = status
        getattr(st, level)(message)


def _save_comment() -> None:
    comment = str(st.session_state.get("final_comment", "")).strip()
    if not comment:
        st.session_state.comment_status = (
            "warning",
            "Vui lòng nhập nội dung trước khi gửi.",
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
    st.session_state.comment_status = ("success", "Cảm ơn Quý bác sĩ! Ý kiến đã được lưu lại.")
    st.session_state.final_comment = ""
