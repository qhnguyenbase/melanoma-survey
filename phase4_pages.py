from __future__ import annotations

import csv
from datetime import datetime
import json
import os
from pathlib import Path
import random
from typing import Any

import streamlit as st

from utils import (
    append_to_sheet,
    cleanup_result_cache,
    DATA_DIR,
    ensure_response_timer,
    get_phase4_labeled_images,
    get_response_time_seconds,
    init_session,
    render_pdf_in_ui,
    run_model,
    use_phase2_heatmap_defaults,
    use_phase2_prototree_defaults,
    use_phase2_weakly_supervised_defaults,
)
CHECKLIST_TABLE_COLUMNS_BY_WIDTH: dict[int, list[str]] = {
    5: ["Attribute", "Prediction", "State", "Points", "Probability (%)"],
    6: ["Attribute", "Prediction", "State", "Points", "Probability (%)"],
}
PHASE4_MODELS: list[dict[str, str]] = [
    {"kind": "heatmap", "label": "Grad-CAM", "slug": "GradCAM"},
    {"kind": "prototree", "label": "ProtoTree", "slug": "ProtoTree"},
    {"kind": "clustering", "label": "Clustering", "slug": "Clustering"},
    {"kind": "weakly_supervised", "label": "Concept-Based", "slug": "MyModel"},
]
PHASE4_METRICS: list[tuple[str, str, str]] = [
    (
        "fidelity",
        "Fidelity",
        "How well does the explanation approximate the prediction of the model?",
    ),
    (
        "comprehensibility",
        "Comprehensibility",
        "How easy is the explanation to understand?",
    ),
    (
        "effectiveness",
        "Effectiveness",
        "How much does the explanation help you make a diagnosis decision?",
    ),
    (
        "usefulness",
        "Usefulness",
        "How well does the AI explanation align with your own reasoning process?",
    ),
    (
        "stability",
        "Stability",
        "How reliable and consistent does the explanation seem across similar cases?",
    ),
]


PHASE4_RESPONSES_FILE = DATA_DIR / "phase4_responses.json"
PHASE4_RESPONSES_FLAT_FILE = DATA_DIR / "phase4_responses_flat.csv"
PHASE4_IMAGES_PER_LABEL = 10
# Changing this reshuffles which images the survey uses; rerun precompute.py.
PHASE4_SAMPLE_SEED = 20260828


def render_phase4_page() -> None:
    st.set_page_config(page_title="Phase 4", page_icon="🧪", layout="centered")

    init_session()

    st.title("Phase 4: Explanation Comparison")

    st.markdown(
        """
        In Phase 4, you are asked to provide feedback on different types of AI explanations for melanoma detection. The workflow is as follows:

        1. Select one dermoscopic image from the dropdown menu.
        2. Open one explanation type at a time, you can test as many images as you want before scoring.
        3. After reviewing each explanation, rate them on a scale of 1 to 10 based on 5 standards: fidelity, comprehensibility, effectiveness, usefulness, and stability.
        4. Close it and move to the next explanation type.
        5. Submit the evaluation after all four explanation types are scored.

        NOTE: 
        - There is a Full Screen button in the top-right corner of the explanation that you can use to expand the workspace, which is recommended for better viewing of the explanation results.
        """
    )

    st.markdown("### Explanation types")
    st.markdown(
        """
        Phase 4 compares these four explanation types for the same image:

        - `Grad-CAM`
        - `ProtoTree`
        - `Clustering`
        - `Concept-Based`
        """
    )

    st.markdown("### Interpretability scores")
    st.markdown(
        """
        - `Fidelity`: how well the explanation reflects the actual reasoning used by the model to make its prediction.
        - `Comprehensibility`: how easy it is for you to read, follow, and understand the explanation.
        - `Effectiveness`: how much the explanation helps you make a diagnosis or affects your decision-making.
        - `Usefulness`: how well the explanation matches your own reasoning process when you inspect the lesion.
        - `Stability`: how reliable and consistent the explanation seems across similar cases or small changes in the input.
        """
    )

    st.markdown("### Phase 4 evaluation")
    st.caption(
        "Select one image, review its known label, open each explanation type, score it, then submit after all four are completed."
    )

    question_key = "ph4_eval"
    selection_token_key = f"{question_key}_selection_token"
    active_kind_key = f"{question_key}_active_kind"
    results_key = f"{question_key}_results"
    flash_message_key = f"{question_key}_flash_message"
    timer_key = f"{question_key}_timer"
    ensure_response_timer(timer_key)

    phase4_images_all = get_phase4_labeled_images()
    phase4_images = _sample_phase4_images_for_session(
        phase4_images_all,
        question_key=question_key,
        per_label=PHASE4_IMAGES_PER_LABEL,
    )
    if not phase4_images:
        st.error(
            "No Phase 4 images were found. Please add labeled images under "
            "`app/images/phase_4/benign/` and `app/images/phase_4/melanoma/`."
        )
        st.stop()

    image_options = {
        f"{item['name']} ({item['label']})": item
        for item in phase4_images
    }
    selected_option = st.selectbox(
        "Select image for explanation comparison",
        options=list(image_options.keys()),
        key=f"{question_key}_image_select",
    )
    selected_image = image_options[selected_option]
    selected_image_name = selected_image["name"]
    selected_image_label = selected_image["label"]
    selected_image_path = selected_image["path"]

    current_selection_token = selected_image_path
    previous_selection_token = st.session_state.get(selection_token_key)
    if previous_selection_token and previous_selection_token != current_selection_token:
        _save_phase4_state_for_image(question_key, previous_selection_token)
    if current_selection_token != previous_selection_token:
        _load_phase4_state_for_image(question_key, current_selection_token)
        st.session_state[selection_token_key] = current_selection_token

    st.image(
        selected_image_path,
        caption=f"Selected image: {selected_image_name}",
        use_container_width=True,
    )
    st.caption(f"Known label: {selected_image_label}")

    flash_message = st.session_state.pop(flash_message_key, None)
    if flash_message:
        st.success(flash_message)

    scored_models = _get_phase4_scores(question_key)
    st.markdown(
        f"#### Progress: {len(scored_models)}/{len(PHASE4_MODELS)} explanation types scored"
    )
    _render_phase4_status_row(scored_models)

    st.markdown("#### Explanation buttons")
    button_cols = st.columns(len(PHASE4_MODELS))
    selected_kind: str | None = None
    for col, model in zip(button_cols, PHASE4_MODELS):
        with col:
            button_label = model["label"]
            if model["kind"] in scored_models:
                button_label = f"{button_label} Saved"
            if st.button(
                button_label,
                key=f"{question_key}_{model['kind']}_open",
                use_container_width=True,
            ):
                selected_kind = model["kind"]

    if selected_kind:
        try:
            result_cache = _get_phase4_results(question_key)
            if selected_kind not in result_cache:
                result_cache[selected_kind] = _run_phase4_backend(
                    img_path=selected_image_path,
                    image_name=selected_image_name,
                    kind=selected_kind,
                )
                st.session_state[results_key] = result_cache
            st.session_state[active_kind_key] = selected_kind
        except Exception as exc:
            st.error(f"{_model_label(selected_kind)} failed: {exc}")

    active_kind = st.session_state.get(active_kind_key)
    active_result = _get_phase4_results(question_key).get(active_kind) if active_kind else None
    if active_kind and active_result:
        st.markdown("---")
        header_cols = st.columns([4, 1])
        with header_cols[0]:
            st.markdown(f"#### {_model_label(active_kind)} explanation")
        with header_cols[1]:
            if st.button("Close", key=f"{question_key}_close_active", use_container_width=True):
                st.session_state[active_kind_key] = None
                st.rerun()

        _render_phase4_result(
            title=_model_label(active_kind),
            kind=active_kind,
            result=active_result,
            key_prefix=f"{question_key}_{active_kind}",
        )
        _render_phase4_scores_form(question_key=question_key, kind=active_kind)

    missing_models = [
        model["label"]
        for model in PHASE4_MODELS
        if model["kind"] not in scored_models
    ]
    if missing_models:
        st.info(
            "Score all four explanation types before submitting this question: "
            + ", ".join(missing_models)
            + "."
        )

    if st.button(
        "Submit interpretability evaluation",
        type="primary",
        key=f"{question_key}_submit",
        disabled=bool(missing_models),
    ):
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        response_time_seconds = get_response_time_seconds(timer_key, reset=True)
        name = st.session_state.get("name")
        email = st.session_state.get("email")
        result_cache = _get_phase4_results(question_key)
        score_cache = _get_phase4_scores(question_key)
        _ = response_time_seconds
        _append_phase4_json_record(
            PHASE4_RESPONSES_FILE,
            {
                "Timestamp": timestamp,
                "Name": name,
                "Email": email,
                "InterpretabilityScores": _phase4_interpretability_scores_payload(score_cache),
            },
        )
        _append_phase4_flat_csv_record(
            PHASE4_RESPONSES_FLAT_FILE,
            timestamp=timestamp,
            name=name,
            email=email,
            score_cache=score_cache,
        )
        cleanup_result_cache(result_cache)
        st.session_state["phase4_completed"] = True
        st.switch_page("pages/36_Thank_You.py")


def render_phase4_intro() -> None:
    render_phase4_page()


def _run_phase4_backend(img_path: str, image_name: str, kind: str) -> dict[str, Any]:
    if kind == "weakly_supervised":
        use_phase2_weakly_supervised_defaults()
    elif kind == "heatmap":
        use_phase2_heatmap_defaults()
    elif kind == "prototree":
        use_phase2_prototree_defaults()
    elif kind == "clustering":
        pass
    else:
        raise ValueError(f"Unsupported Phase 4 backend: {kind}")

    return run_model(
        img_path=img_path,
        explanation_kind=kind,
        image_name=image_name,
    )


def _render_phase4_result(
    title: str,
    kind: str,
    result: dict[str, Any],
    key_prefix: str,
) -> None:
    prediction = result.get("prediction") or "Unavailable"
    st.success(f"{title} prediction: {prediction}")

    prob_melanoma = result.get("prob_melanoma")
    if isinstance(prob_melanoma, (int, float)):
        st.caption(f"Estimated melanoma risk: {float(prob_melanoma) * 100:.1f}%")

    explanation_description = _phase4_explanation_description(kind)
    if explanation_description:
        if kind == "weakly_supervised":
            st.markdown(f"### {explanation_description}")
        else:
            st.markdown(explanation_description)

    top_attribute = result.get("top_attribute")
    top_attribute_label = result.get("top_attribute_label")
    if top_attribute:
        detail = (
            f"{top_attribute}: {top_attribute_label}"
            if top_attribute_label
            else str(top_attribute)
        )
        st.caption(f"Key detail: {detail}")

    explanation_note = result.get("explanation_note")
    if explanation_note:
        st.info(str(explanation_note))

    resolved_image_id = result.get("resolved_image_id")
    resolved_image_id_source = result.get("resolved_image_id_source")
    if resolved_image_id:
        match_text = f"Matched image ID: {resolved_image_id}"
        if resolved_image_id_source:
            match_text += f" ({resolved_image_id_source})"
        st.caption(match_text)

    checklist_table = result.get("checklist_table")
    table_rows = _normalize_checklist_table_rows(checklist_table)
    if kind == "weakly_supervised" and table_rows:
        st.markdown("##### Attribute scores")
        st.dataframe(table_rows, hide_index=True, use_container_width=True)

    if kind == "clustering":
        _render_clustering_nearest_cases(result)

    _render_phase4_explanation_preview(title=title, result=result)

    if kind != "weakly_supervised" and table_rows:
        st.markdown("##### Attribute scores")
        st.dataframe(table_rows, hide_index=True, use_container_width=True)

    explanation_pdf = result.get("explanation_pdf")
    if explanation_pdf:
        pdf_path = Path(explanation_pdf)
        if pdf_path.exists():
            st.download_button(
                f"Download {title} PDF",
                data=pdf_path.read_bytes(),
                file_name=pdf_path.name,
                mime="application/pdf",
                key=f"{key_prefix}_download",
            )
            if result.get("show_pdf_inline"):
                st.markdown("##### Explanation report")
                render_pdf_in_ui(pdf_path, height=720)


def _render_clustering_nearest_cases(result: dict[str, Any]) -> None:
    nearest_cases = result.get("nearest_latent_cases")
    if not isinstance(nearest_cases, list) or not nearest_cases:
        return

    valid_cases = []
    for case in nearest_cases:
        if not isinstance(case, dict):
            continue
        image_path = case.get("image_path")
        if not image_path:
            continue
        path = Path(str(image_path))
        if not path.exists():
            continue
        valid_cases.append(case)
        if len(valid_cases) == 3:
            break

    if not valid_cases:
        return

    st.markdown("##### 3 closest images in latent space")
    cols = st.columns(len(valid_cases))
    for col, case in zip(cols, valid_cases):
        with col:
            true_label = "Melanoma" if int(case.get("true_label", 0)) == 1 else "Non-melanoma"
            predicted_label = (
                "Melanoma" if int(case.get("predicted_label", 0)) == 1 else "Non-melanoma"
            )
            image_key = str(case.get("image_key", "")).strip() or "Unknown"
            st.image(
                str(case.get("image_path")),
                caption=f"{image_key}",
                use_container_width=True,
            )
            st.caption(f"True: {true_label} | Pred: {predicted_label}")


def _render_phase4_explanation_preview(title: str, result: dict[str, Any]) -> None:
    explanation_image_global = result.get("explanation_image_global")
    explanation_image_local = result.get("explanation_image_local")
    explanation_image = result.get("explanation_image")
    global_preview_label = result.get("global_preview_label") or "global explanation"
    local_preview_label = result.get("local_preview_label") or "local explanation"
    if explanation_image_global and explanation_image_local:
        st.markdown("##### Explanation preview")
        preview_cols = st.columns(2)
        with preview_cols[0]:
            st.image(
                explanation_image_global,
                caption=f"{title} {global_preview_label}",
                use_container_width=True,
            )
        with preview_cols[1]:
            st.image(
                explanation_image_local,
                caption=f"{title} {local_preview_label}",
                use_container_width=True,
            )
    elif explanation_image_global:
        st.image(
            explanation_image_global,
            caption=f"{title} {global_preview_label}",
            use_container_width=True,
        )
    elif explanation_image_local:
        st.image(
            explanation_image_local,
            caption=f"{title} {local_preview_label}",
            use_container_width=True,
        )
    elif explanation_image:
        model_backend = str(result.get("model_backend") or "")
        if model_backend == "phase2_clustering_cluster":
            st.image(
                explanation_image,
                caption=f"{title} explanation preview",
                use_container_width=True,
            )
        else:
            st.image(
                explanation_image,
                caption=f"{title} explanation preview",
                use_container_width=True,
            )


def _render_phase4_scores_form(question_key: str, kind: str) -> None:
    st.markdown("#### Interpretability scores")

    existing_scores = _get_phase4_scores(question_key).get(kind, {})
    for metric_key, _, _ in PHASE4_METRICS:
        slider_key = _phase4_metric_widget_key(question_key, kind, metric_key)
        if slider_key not in st.session_state:
            st.session_state[slider_key] = existing_scores.get(metric_key, 5)

    with st.form(key=f"{question_key}_{kind}_score_form"):
        ratings: dict[str, int] = {}
        for metric_key, metric_label, metric_prompt in PHASE4_METRICS:
            ratings[metric_key] = st.slider(
                f"{metric_label}: {metric_prompt}",
                min_value=1,
                max_value=10,
                step=1,
                help=metric_prompt,
                key=_phase4_metric_widget_key(question_key, kind, metric_key),
            )

        saved = st.form_submit_button(
            f"Save scores for {_model_label(kind)}",
            type="primary",
        )

    if saved:
        score_cache = _get_phase4_scores(question_key)
        score_cache[kind] = ratings
        st.session_state[f"{question_key}_scores"] = score_cache
        image_token = st.session_state.get(f"{question_key}_selection_token")
        if image_token:
            _save_phase4_state_for_image(question_key, image_token)
        st.session_state[f"{question_key}_active_kind"] = None
        st.session_state[f"{question_key}_flash_message"] = (
            f"Saved scores for {_model_label(kind)}."
        )
        st.rerun()


def _render_phase4_status_row(score_cache: dict[str, dict[str, int]]) -> None:
    status_cols = st.columns(len(PHASE4_MODELS))
    for col, model in zip(status_cols, PHASE4_MODELS):
        with col:
            status = "Saved" if model["kind"] in score_cache else "Pending"
            st.caption(f"{model['label']}: {status}")


def _phase4_response_headers() -> list[str]:
    headers: list[str] = []
    for model in PHASE4_MODELS:
        slug = model["slug"]
        headers.extend(
            [
                f"{slug}_Prediction",
                f"{slug}_MelanomaRisk",
                f"{slug}_ExplanationPdf",
            ]
        )
        headers.extend(f"{slug}_{metric_label}" for _, metric_label, _ in PHASE4_METRICS)
    return headers


def _phase4_response_values(
    result_cache: dict[str, dict[str, Any]],
    score_cache: dict[str, dict[str, int]],
) -> list[Any]:
    values: list[Any] = []
    for model in PHASE4_MODELS:
        kind = model["kind"]
        result = result_cache.get(kind, {})
        scores = score_cache.get(kind, {})
        values.extend(
            [
                result.get("prediction"),
                _format_risk(result.get("prob_melanoma")),
                None,
            ]
        )
        values.extend(scores.get(metric_key) for metric_key, _, _ in PHASE4_METRICS)
    return values


def _model_label(kind: str | None) -> str:
    if kind is None:
        return ""
    for model in PHASE4_MODELS:
        if model["kind"] == kind:
            return model["label"]
    return kind


def _phase4_explanation_description(kind: str) -> str | None:
    descriptions = {
        "heatmap": (
            "The region highlighted below represents the area that contributed most "
            "to the model's decision."
        ),
        "clustering": (
            "The model places the test image (star in the latent space) into a "
            "cluster of training images with similar characteristics."
        ),
        "prototree": (
            "The prediction is based on the similarity between regions of the test "
            "image and representative prototype patches learned from the training "
            "dataset, with the decision guided by a decision tree."
        ),
        "weakly_supervised": (
            "The model suggests further assessment if the total dermoscopic score is "
            "equal or greater than 3."
        ),
    }
    return descriptions.get(kind)


def _phase4_metric_widget_key(question_key: str, kind: str, metric_key: str) -> str:
    return f"{question_key}_{kind}_{metric_key}_score"


def _phase4_interpretability_scores_payload(
    score_cache: dict[str, dict[str, int]],
) -> dict[str, dict[str, int | None]]:
    payload: dict[str, dict[str, int | None]] = {}
    for model in PHASE4_MODELS:
        kind = model["kind"]
        model_scores = score_cache.get(kind, {})
        payload[model["label"]] = {
            metric_label: model_scores.get(metric_key)
            for metric_key, metric_label, _ in PHASE4_METRICS
        }
    return payload


def _append_phase4_json_record(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]]
    if not path.exists() or path.stat().st_size == 0:
        rows = []
    else:
        try:
            with path.open("r", encoding="utf-8") as f:
                payload = json.load(f)
        except json.JSONDecodeError:
            rows = []
        else:
            if isinstance(payload, list):
                rows = [row for row in payload if isinstance(row, dict)]
            elif isinstance(payload, dict):
                rows = [payload]
            else:
                rows = []

    rows.append(record)
    with path.open("w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)


def _phase4_flat_score_headers() -> list[str]:
    headers: list[str] = ["Timestamp", "Name", "Email"]
    for model in PHASE4_MODELS:
        label_slug = model["label"].replace(" ", "_")
        for _, metric_label, _ in PHASE4_METRICS:
            metric_slug = metric_label.replace(" ", "_")
            headers.append(f"{label_slug}_{metric_slug}")
    return headers


def _append_phase4_flat_csv_record(
    path: Path,
    timestamp: str,
    name: Any,
    email: Any,
    score_cache: dict[str, dict[str, int]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    row: dict[str, Any] = {
        "Timestamp": timestamp,
        "Name": name,
        "Email": email,
    }
    for model in PHASE4_MODELS:
        kind = model["kind"]
        label_slug = model["label"].replace(" ", "_")
        model_scores = score_cache.get(kind, {})
        for metric_key, metric_label, _ in PHASE4_METRICS:
            metric_slug = metric_label.replace(" ", "_")
            row[f"{label_slug}_{metric_slug}"] = model_scores.get(metric_key)

    headers = _phase4_flat_score_headers()
    write_header = (not path.exists()) or path.stat().st_size == 0
    # BOM on creation only, so Excel renders non-ASCII correctly; appending with
    # utf-8-sig would inject a BOM mid-file. Mirrors save_to_csv in utils.py.
    encoding = "utf-8-sig" if write_header else "utf-8"
    with path.open("a", encoding=encoding, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

    # Phase 4 does not go through save_to_csv, so it needs its own mirror to
    # Sheets -- otherwise these scores are the one thing a restart would erase.
    append_to_sheet(
        [row.get(header) for header in headers],
        worksheet_name=path.stem,
        headers=headers,
    )


def _phase4_images_state_key(question_key: str) -> str:
    return f"{question_key}_images_state"


def _get_phase4_images_state(question_key: str) -> dict[str, dict[str, Any]]:
    return st.session_state.setdefault(_phase4_images_state_key(question_key), {})


def _save_phase4_state_for_image(question_key: str, image_token: str) -> None:
    if not image_token:
        return

    images_state = _get_phase4_images_state(question_key)
    images_state[image_token] = {
        "results": dict(_get_phase4_results(question_key)),
    }
    st.session_state[_phase4_images_state_key(question_key)] = images_state


def _clear_phase4_slider_widgets(question_key: str) -> None:
    for model in PHASE4_MODELS:
        for metric_key, _, _ in PHASE4_METRICS:
            st.session_state.pop(
                _phase4_metric_widget_key(question_key, model["kind"], metric_key),
                None,
            )


def _load_phase4_state_for_image(question_key: str, image_token: str) -> None:
    images_state = _get_phase4_images_state(question_key)
    state = images_state.get(image_token, {})

    st.session_state[f"{question_key}_results"] = dict(state.get("results", {}))
    st.session_state[f"{question_key}_active_kind"] = None
    st.session_state[f"{question_key}_flash_message"] = None


def select_phase4_images(
    images: list[dict[str, str]],
    per_label: int = PHASE4_IMAGES_PER_LABEL,
) -> list[dict[str, str]]:
    """The Phase 4 stimulus set: a seeded, deterministic sample per label.

    Pure and Streamlit-free so precompute.py can generate explanations for
    exactly the images the survey will show -- the two must never diverge.
    """
    if per_label <= 0 or not images:
        return images

    grouped: dict[str, list[dict[str, str]]] = {}
    for item in images:
        label = str(item.get("label", "")).strip().lower()
        grouped.setdefault(label, []).append(item)

    # Seeded so every participant sees the SAME stimulus set: ratings stay
    # comparable across participants, and the precomputed cache only has to
    # cover these images rather than all 160.
    rng = random.Random(PHASE4_SAMPLE_SEED)
    sampled: list[dict[str, str]] = []
    for _, group_items in sorted(grouped.items(), key=lambda kv: kv[0]):
        if len(group_items) <= per_label:
            sampled.extend(group_items)
            continue
        # Sort first: rng.sample over a dict-ordered list would depend on
        # filesystem iteration order, which is not stable across machines.
        ordered = sorted(group_items, key=lambda item: str(item.get("name", "")).lower())
        sampled.extend(rng.sample(ordered, per_label))

    return sorted(
        sampled,
        key=lambda item: (
            str(item.get("label", "")).lower(),
            str(item.get("name", "")).lower(),
        ),
    )


def _sample_phase4_images_for_session(
    images: list[dict[str, str]],
    question_key: str,
    per_label: int,
) -> list[dict[str, str]]:
    if per_label <= 0 or not images:
        return images

    pool_key = f"{question_key}_image_pool"
    signature_key = f"{question_key}_image_pool_signature"

    # Rebuild the sampled pool only when source image set changes.
    source_signature = "|".join(
        sorted(f"{item.get('label','')}::{item.get('path','')}" for item in images)
    )
    cached_pool = st.session_state.get(pool_key)
    cached_signature = st.session_state.get(signature_key)
    if isinstance(cached_pool, list) and cached_signature == source_signature:
        return cached_pool

    sampled = select_phase4_images(images, per_label)
    st.session_state[pool_key] = sampled
    st.session_state[signature_key] = source_signature
    return sampled


def _get_phase4_results(question_key: str) -> dict[str, dict[str, Any]]:
    return st.session_state.setdefault(f"{question_key}_results", {})


def _get_phase4_scores(question_key: str) -> dict[str, dict[str, int]]:
    return st.session_state.setdefault(f"{question_key}_scores", {})


def _reset_phase4_question_state(question_key: str) -> None:
    cleanup_result_cache(st.session_state.get(f"{question_key}_results"))
    for suffix in [
        "results",
        "scores",
        "active_kind",
        "flash_message",
    ]:
        st.session_state.pop(f"{question_key}_{suffix}", None)

    for model in PHASE4_MODELS:
        for metric_key, _, _ in PHASE4_METRICS:
            st.session_state.pop(
                _phase4_metric_widget_key(question_key, model["kind"], metric_key),
                None,
            )


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

    row_width = len(first_row)
    headers = CHECKLIST_TABLE_COLUMNS_BY_WIDTH.get(row_width)
    if not headers:
        return []

    rows: list[dict[str, Any]] = []
    for row in checklist_table:
        if not isinstance(row, (list, tuple)):
            continue
        row_values = list(row)
        if row_width == 6:
            # Backward compatibility: drop legacy "Attr score" column.
            row_values = row_values[:4] + row_values[5:]
        values = list(row_values[: len(headers)])
        if len(values) < len(headers):
            values.extend([None] * (len(headers) - len(values)))
        rows.append(dict(zip(headers, values)))
    return rows
