"""
Landing page for participant registration.
"""

import streamlit as st

from utils import init_session, save_participant, sheets_status


def main() -> None:
    st.set_page_config(
        page_title="Xác nhận tham gia khảo sát",
        page_icon="🩺",
        layout="centered",
    )

    init_session()

    st.title("Xác nhận tham gia khảo sát")

    # Storage is checked on the landing page rather than left to fail silently
    # at submit time: on a hosted app the local filesystem is wiped on every
    # restart, so a broken Sheets connection means every response is lost.
    storage_ok, storage_detail = sheets_status()
    if not storage_ok:
        st.error(
            "**Câu trả lời hiện KHÔNG được lưu lại.** Vui lòng liên hệ nhóm "
            "nghiên cứu trước khi bắt đầu.\n\n"
            f"Chi tiết kỹ thuật: {storage_detail}"
        )

    st.markdown(
        """
        ### Chào mừng Quý bác sĩ đến với nghiên cứu
        Cảm ơn Quý bác sĩ đã nhận lời tham gia dự án nghiên cứu này.

        **Thông tin về bảo mật:**
        - Toàn bộ dữ liệu sẽ được **ẩn danh** trước khi phân tích; không có thông tin định danh cá nhân nào được chia sẻ.
        - Việc tham gia là hoàn toàn tự nguyện.
        - Quý bác sĩ có thể dừng tham gia bất cứ lúc nào.
        - Lưu ý: tất cả các mô hình sử dụng trong khảo sát này **chưa được phê duyệt để dùng trên lâm sàng**, chỉ phục vụ mục đích nghiên cứu.
        - Thời gian hoàn thành khảo sát ước tính khoảng 30 phút.
        """
    )

    with st.form("confirmation_form"):
        name = st.text_input("Họ và tên")
        email = st.text_input("Địa chỉ email")
        consent = st.checkbox("Tôi đồng ý tham gia nghiên cứu này.")
        submit = st.form_submit_button("Bắt đầu khảo sát")

    if submit:
        if not name or not email or not consent:
            st.error("Vui lòng điền đầy đủ tất cả các mục.")
        else:
            save_participant(name, email)
            st.session_state.name = name
            st.session_state.email = email
            st.switch_page("pages/00_Introduction.py")


if __name__ == "__main__":
    main()
