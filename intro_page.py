from __future__ import annotations

import streamlit as st

from utils import init_session, require_registration


def render_intro_page() -> None:
    st.set_page_config(page_title="Introduction", page_icon="🩺", layout="centered")

    init_session()
    require_registration()

    name = st.session_state.get("name")
    email = st.session_state.get("email")
    if not name or not email:
        st.warning("Please complete the Home page registration before starting the survey.")
        if st.button("Go to Home", type="primary"):
            st.switch_page("Home.py")
        return

    st.title("Survey Introduction")

    st.markdown(
        f"""
        Welcome, {name}.

        This survey has four phases and is designed to evaluate how AI support and AI explanations influence melanoma-related decision making.
        """
    )

    st.markdown("### Survey structure")
    st.markdown(
        """
        **Phase 1: No AI support**  
        You review dermoscopic images without any AI assistance and provide your diagnosis and confidence.

        **Phase 2: AI prediction without model reasoning**  
        You upload an image, review the model prediction only, and then provide your diagnosis and confidence.

        **Phase 3: AI prediction with model explanation**  
        You upload an image, review the model prediction together with its explanation, and then provide your diagnosis and confidence.

        **Phase 4: Evaluation of interpretability**  
        You evaluate the interpretability of different explanation methods, including Grad-CAM, LIME, ProtoTree, Clustering, and the weakly supervised model.
        """
    )

    st.markdown("### Before you begin")
    st.markdown(
        """
        - Use the buttons at the bottom of each page to move through the survey.
        - Complete each phase in order.
        - For diagnosis questions, answer based on your own judgment.
        - For Phase 4, score each explanation type before submitting the final evaluation.
        """
    )

    if st.button("Start Phase 1", type="primary"):
        st.switch_page("pages/0_Phase_1.py")
