from __future__ import annotations

import streamlit as st

from utils import init_session, require_registration


def render_intro_page() -> None:
    st.set_page_config(page_title="Giới thiệu", page_icon="🩺", layout="centered")

    init_session()
    require_registration()

    name = st.session_state.get("name")
    email = st.session_state.get("email")
    if not name or not email:
        st.warning("Vui lòng hoàn tất phần đăng ký ở trang chủ trước khi bắt đầu khảo sát.")
        if st.button("Về trang chủ", type="primary"):
            st.switch_page("Home.py")
        return

    st.title("Giới thiệu khảo sát")

    st.markdown(
        f"""
        Xin chào, {name}.

        Khảo sát này gồm bốn giai đoạn, nhằm đánh giá ảnh hưởng của hỗ trợ từ AI và của các phần giải thích do AI đưa ra đối với quyết định chẩn đoán u hắc tố ác tính (melanoma).
        """
    )

    st.markdown("### Cấu trúc khảo sát")
    st.markdown(
        """
        **Giai đoạn 1: Không có hỗ trợ của AI**  
        Quý bác sĩ xem ảnh soi da (dermoscopy) mà không có bất kỳ hỗ trợ nào từ AI, sau đó đưa ra chẩn đoán và mức độ tự tin của mình.

        **Giai đoạn 2: Có dự đoán của AI, không có giải thích**  
        Quý bác sĩ xem ảnh, xem dự đoán của mô hình (không kèm giải thích), sau đó đưa ra chẩn đoán và mức độ tự tin của mình.

        **Giai đoạn 3: Có dự đoán của AI kèm phần giải thích**  
        Quý bác sĩ xem ảnh, xem dự đoán của mô hình cùng với phần giải thích, sau đó đưa ra chẩn đoán và mức độ tự tin của mình.

        **Giai đoạn 4: Đánh giá khả năng diễn giải**  
        Quý bác sĩ đánh giá khả năng diễn giải của các phương pháp giải thích khác nhau, gồm Grad-CAM, ProtoTree, Clustering (phân cụm) và mô hình dựa trên khái niệm (Concept-Based).
        """
    )

    st.markdown("### Trước khi bắt đầu")
    st.markdown(
        """
        - Dùng các nút ở cuối mỗi trang để di chuyển trong khảo sát.
        - Hoàn thành các giai đoạn theo đúng thứ tự.
        - Với các câu hỏi chẩn đoán, xin trả lời theo nhận định của chính Quý bác sĩ.
        - Ở Giai đoạn 4, hãy chấm điểm từng loại giải thích trước khi gửi đánh giá cuối cùng.
        """
    )

    if st.button("Bắt đầu Giai đoạn 1", type="primary"):
        st.switch_page("pages/0_Phase_1.py")
