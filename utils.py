import base64
import csv
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any

import streamlit as st
from streamlit.components.v1 import html

import precomputed_backend

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"
IMAGES_DIR = APP_DIR / "images"
VIDEOS_DIR = APP_DIR / "videos"
OUTPUTS_DIR = APP_DIR / "outputs"
VENDOR_DIR = APP_DIR / "vendor"
LOCAL_PH2_ROOT = APP_DIR / "datasets" / "PH2_dataset"

PHASE2_EXPLANATION_METRICS: list[tuple[str, str, str]] = [
    (
        "fidelity",
        "Fidelity",
        "How well does the explanation approximate the prediction of the black-box model?",
    ),
    (
        "comprehensibility",
        "Comprehensibility",
        "How well do humans understand the explanation?",
    ),
    (
        "usefulness",
        "Usefulness",
        "How well does the explanation support the decision-making process?",
    ),
    (
        "consistency",
        "Consistency",
        "How well does the explanation perform across multiple instances?",
    ),
    (
        "reliance",
        "Reliance",
        "How much would you rely on the model and its explanation?",
    ),
]


### -------------------------
### Initialize session state
### -------------------------
def _hide_streamlit_top_right_controls() -> None:
    st.markdown(
        """
        <style>
        header [data-testid="stToolbar"] {display: none !important;}
        /* The sidebar page list let participants jump to any phase, skip
           earlier ones, or land mid-survey unregistered. The survey is a fixed
           sequence, so navigation is driven by the Next buttons instead. */
        [data-testid="stSidebarNav"] {display: none !important;}
        [data-testid="stSidebarCollapseButton"] {display: none !important;}
        </style>
        """,
        unsafe_allow_html=True,
    )


# The survey is a fixed linear sequence. Keeping it in one place lets each page
# work out what comes next without hardcoding its neighbour.
SURVEY_PAGES: list[str] = (
    ["Home.py", "pages/00_Introduction.py", "pages/0_Phase_1.py"]
    + [f"pages/{i}_question_{i}.py" for i in range(1, 9)]
    + ["pages/9_Phase_2.py"]
    + [f"pages/{9 + i}_Phase_2_Question_{i}.py" for i in range(1, 9)]
    + ["pages/18_Phase_3.py"]
    + [f"pages/{18 + i}_Phase_3_Question_{i}.py" for i in range(1, 9)]
    + ["pages/27_Phase_4.py", "pages/36_Thank_You.py"]
)


def next_page(current: str) -> str | None:
    """The page after `current` in the survey sequence, or None at the end."""
    try:
        index = SURVEY_PAGES.index(current)
    except ValueError:
        return None
    return SURVEY_PAGES[index + 1] if index + 1 < len(SURVEY_PAGES) else None


def require_registration() -> None:
    """Send unregistered visitors back to the landing page.

    Session state does not survive a browser refresh, so without this a
    participant who reloads mid-survey carries on answering with no name or
    email attached, producing rows that cannot be tied to anyone.
    """
    if st.session_state.get("name") and st.session_state.get("email"):
        return

    # Stop and offer a button rather than redirecting automatically: it tells the
    # participant what happened, and cannot loop if the landing page is reached
    # in an unexpected state.
    st.warning(
        "Phiên làm việc của Quý bác sĩ đã kết thúc — điều này xảy ra khi trang "
        "được tải lại. Vui lòng đăng nhập lại để tiếp tục. Các câu trả lời đã "
        "gửi trước đó vẫn được lưu an toàn."
    )
    if st.button("Quay lại trang đầu", type="primary"):
        st.switch_page("Home.py")
    st.stop()


def already_submitted(question_key: str) -> bool:
    """True if this question was already saved in this session.

    Guards against the double-submit seen in the collected data, where a second
    click landed an identical row with a response time of ~0 seconds.
    """
    return question_key in st.session_state.setdefault("_submitted_questions", set())


def mark_submitted(question_key: str) -> None:
    st.session_state.setdefault("_submitted_questions", set()).add(question_key)


def render_next_button(current_page: str, label: str = "Tiếp tục") -> None:
    """Advance control, replacing the hidden sidebar navigation."""
    target = next_page(current_page)
    if target and st.button(label, type="primary", use_container_width=True):
        st.switch_page(target)


def init_session():
    _hide_streamlit_top_right_controls()
    if "name" not in st.session_state:
        st.session_state.name = None
    if "email" not in st.session_state:
        st.session_state.email = None


def ensure_response_timer(timer_key: str) -> None:
    if timer_key not in st.session_state:
        st.session_state[timer_key] = time.perf_counter()


def get_response_time_seconds(timer_key: str, reset: bool = False) -> float | None:
    started_at = st.session_state.get(timer_key)
    if started_at is None:
        return None

    elapsed = round(max(0.0, time.perf_counter() - float(started_at)), 2)
    if reset:
        st.session_state.pop(timer_key, None)
    return elapsed


def require_phase1_completion(total_questions: int = 8) -> None:
    """Phase 1 gating is disabled while Phase 2 is under active testing."""
    return


### -------------------------
### Load images from folder
### -------------------------
def load_images(folder):
    folder = Path(folder)
    images = [
        *folder.glob("*.jpg"),
        *folder.glob("*.jpeg"),
        *folder.glob("*.png"),
        *folder.glob("*.bmp"),
        *folder.glob("*.tif"),
        *folder.glob("*.tiff"),
    ]
    return [str(p) for p in sorted(images)]


def _get_fixed_phase_question_images(folder_name: str) -> list[str]:
    return load_images(IMAGES_DIR / folder_name)


def get_phase1_question_images(total_questions: int = 8) -> list[str]:
    """Return the fixed Phase 1 image order from app/images/phase_1/."""
    return _get_fixed_phase_question_images("phase_1")


def get_phase2_question_images(total_questions: int = 8) -> list[str]:
    """Return the fixed Phase 2 image order from app/images/phase_2/."""
    return _get_fixed_phase_question_images("phase_2")


def get_phase3_question_images(total_questions: int = 8) -> list[str]:
    """Return the fixed Phase 3 image order from app/images/phase_3/."""
    return _get_fixed_phase_question_images("phase_3")


def get_ph2_dataset_images() -> list[str]:
    """Return all PH2 dataset images from the configured all_images directory."""
    return load_images(_default_ph2_images_dir())


def get_phase4_labeled_images() -> list[dict[str, str]]:
    """Return Phase 4 image records from app/images/phase_4/<label>/."""
    phase4_root = IMAGES_DIR / "phase_4"
    if not phase4_root.exists():
        return []
    items: list[dict[str, str]] = []
    for label_dir in sorted(p for p in phase4_root.iterdir() if p.is_dir()):
        label = label_dir.name.replace("_", " ").strip().title()
        for image_path in load_images(label_dir):
            path = Path(image_path)
            items.append(
                {
                    "label": label,
                    "name": path.name,
                    "path": str(path),
                }
            )
    return items


def use_phase2_weakly_supervised_defaults() -> None:
    """Force Phase-2 pages to use the vendor weakly supervised model defaults."""
    model_dir = VENDOR_DIR / "weakly_supervised_prototype"
    os.environ["MODEL_DIR"] = str(model_dir)
    os.environ["MODEL_CKPT"] = str(model_dir / "outputs" / "best.pt")
    os.environ["MODEL_CHECKLIST_THRESHOLD"] = "3"
    os.environ["MODEL_RISK_THRESHOLD"] = "0.5"


def use_phase2_model_defaults() -> None:
    """Backward-compatible alias for weakly supervised defaults."""
    use_phase2_weakly_supervised_defaults()


def use_phase3_model_defaults() -> None:
    """Backward-compatible alias for Phase 3 PDF explanation defaults."""
    use_phase2_weakly_supervised_defaults()


def use_phase2_feature_importance_defaults() -> None:
    """Force Phase-2 Question 2 to use the vendored feature_importance project defaults."""
    project_dir = VENDOR_DIR / "feature_importance"
    os.environ["PHASE2_FEATURE_IMPORTANCE_DIR"] = str(project_dir)
    os.environ["PHASE2_FEATURE_IMPORTANCE_CKPT"] = str(
        project_dir / "outputs" / "resnet18_ph2_melanoma_best.pt"
    )


def use_phase2_heatmap_defaults() -> None:
    """Force Phase-2 Question 3 to use the vendored heatmap_explain project defaults."""
    project_dir = VENDOR_DIR / "heatmap_explain"
    os.environ["PHASE2_HEATMAP_DIR"] = str(project_dir)
    os.environ["PHASE2_HEATMAP_CKPT"] = str(
        project_dir / "artifacts_fixed_pdf_test" / "resnet18_ph2_melanoma_best.pt"
    )


def use_phase2_prototree_defaults() -> None:
    """Force Phase-2 Question 4 to use the vendored ProtoTree project defaults."""
    project_dir = VENDOR_DIR / "ProtoTree"
    os.environ["PHASE2_PROTOTREE_DIR"] = str(project_dir)
    os.environ["PHASE2_PROTOTREE_RUN_DIR"] = str(
        project_dir / "runs" / "prototree_ph2_depth3"
    )


### -------------------------
### Run model inference
### -------------------------
def _resolve_model_dir() -> Path:
    default = VENDOR_DIR / "weakly_supervised_prototype"
    env = os.environ.get("MODEL_DIR")
    return Path(env) if env else default


def _ensure_model_importable(model_dir: Path) -> None:
    p = str(model_dir)
    if p not in sys.path:
        sys.path.insert(0, p)


def _is_new_model_repo(model_dir: Path) -> bool:
    return (model_dir / "src" / "infer.py").exists() and (model_dir / "src" / "models" / "two_branch_model.py").exists()


def _load_json(path: str) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as f:
        return json.load(f)


def _render_pdf_preview_png(
    pdf_path: Path,
    png_path: Path,
    page_1based: int | None = None,
    scale: float | None = None,
) -> None:
    """Render a PDF page to PNG for Streamlit preview.

    Uses MODEL_PDF_PREVIEW_PAGE (1-based, default 2) when page_1based is not provided,
    and MODEL_PDF_RENDER_SCALE (default 2.0).
    """
    try:
        import pypdfium2 as pdfium
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "Missing dependency `pypdfium2` required to convert explanation PDF to PNG. "
            "Install it with: python -m pip install pypdfium2"
        ) from e

    render_scale = (
        float(scale)
        if scale is not None
        else float(os.environ.get("MODEL_PDF_RENDER_SCALE", "2.0"))
    )
    preferred_page_1based = (
        int(page_1based)
        if page_1based is not None
        else int(os.environ.get("MODEL_PDF_PREVIEW_PAGE", "2"))
    )

    pdf = pdfium.PdfDocument(str(pdf_path))
    page = None
    try:
        page_count = len(pdf)
        if page_count == 0:
            raise ValueError(f"PDF has no pages: {pdf_path}")

        page_index = max(0, min(preferred_page_1based - 1, page_count - 1))
        page = pdf[page_index]
        bitmap = page.render(scale=render_scale)
        pil_img = bitmap.to_pil()
        png_path.parent.mkdir(parents=True, exist_ok=True)
        pil_img.save(png_path, format="PNG")
    finally:
        if page is not None:
            page.close()
        pdf.close()


@st.cache_resource(show_spinner=False)
def _load_multiweakly_model(
    ckpt_path: str,
    label_maps_path: str,
    attr_num_classes_path: str,
    criterion_pos_indices_path: str,
    criterion_weights_path: str,
) -> dict[str, Any]:
    model_dir = _resolve_model_dir()
    _ensure_model_importable(model_dir)

    import torch
    from src.data.derm7pt_dataset import ATTR_NAMES
    from src.models import TwoBranchDerm7ptModel

    ckpt = torch.load(ckpt_path, map_location="cpu")
    cfg = ckpt["config"]

    label_maps = _load_json(label_maps_path)
    attr_num_classes = _load_json(attr_num_classes_path)
    criterion_pos_indices = _load_json(criterion_pos_indices_path)
    criterion_weights_map = _load_json(criterion_weights_path)
    criterion_weights = [int(criterion_weights_map[a]) for a in ATTR_NAMES]

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    model_checklist_threshold = float(
        os.environ.get(
            "MODEL_CHECKLIST_THRESHOLD",
            str(cfg.get("checklist", {}).get("threshold", 1.0)),
        )
    )

    model = TwoBranchDerm7ptModel(
        vit_name=cfg["model"]["vit_name"],
        vit_img_size=int(cfg["model"]["vit_img_size"]),
        resnet_name=cfg["model"]["resnet_name"],
        embed_dim=int(cfg["model"]["embed_dim"]),
        num_heads=int(cfg["model"]["num_heads"]),
        attr_num_classes=attr_num_classes,
        criterion_pos_indices=criterion_pos_indices,
        criterion_weights=criterion_weights,
        checklist_threshold=model_checklist_threshold,
        checklist_temperature=float(cfg.get("checklist", {}).get("temperature", 1.0)),
        attn_dropout=float(cfg["model"].get("attn_dropout", 0.0)),
        proj_dropout=float(cfg["model"].get("proj_dropout", 0.0)),
        pretrained=False,
    ).to(device)
    model.load_state_dict(ckpt["state_dict"], strict=True)
    model.eval()

    return {
        "device": device,
        "model": model,
        "cfg": cfg,
        "attr_names": ATTR_NAMES,
        "label_maps": label_maps,
    }


def _run_model_multiweakly(img_path: str, model_dir: Path) -> dict[str, Any]:
    ckpt_path = os.environ.get("MODEL_CKPT") or str(model_dir / "outputs" / "best.pt")
    label_maps_path = os.environ.get("MODEL_LABEL_MAPS") or str(model_dir / "outputs" / "label_maps.json")
    attr_num_classes_path = os.environ.get("MODEL_ATTR_NUM_CLASSES") or str(model_dir / "outputs" / "attr_num_classes.json")
    criterion_pos_indices_path = os.environ.get("MODEL_CRITERION_POS") or str(model_dir / "outputs" / "criterion_pos_indices.json")
    criterion_weights_path = os.environ.get("MODEL_CRITERION_WEIGHTS") or str(model_dir / "outputs" / "criterion_weights.json")

    required_paths = [
        ckpt_path,
        label_maps_path,
        attr_num_classes_path,
        criterion_pos_indices_path,
        criterion_weights_path,
    ]
    missing = [p for p in required_paths if not Path(p).exists()]
    if missing:
        raise FileNotFoundError(
            "Missing model artifact(s):\n" + "\n".join(str(p) for p in missing)
        )

    models = _load_multiweakly_model(
        ckpt_path=ckpt_path,
        label_maps_path=label_maps_path,
        attr_num_classes_path=attr_num_classes_path,
        criterion_pos_indices_path=criterion_pos_indices_path,
        criterion_weights_path=criterion_weights_path,
    )

    import numpy as np
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from src.infer import (
        ATTR_NAMES,
        attribute_state,
        crop_with_padding,
        criterion_points,
        criterion_weight,
        draw_numbered_boxes,
        invert_label_map,
        pretty_attr_name,
        run_inference,
        save_pdf_page1_with_grid_table,
        save_pdf_page2_image_with_thumbnails,
        scale_bbox_square_to_original,
    )
    from src.utils.vis import attn_to_grid_vit, grid_to_bbox_largest_connected_hotspot, normalize_01

    model = models["model"]
    device = models["device"]
    cfg = models["cfg"]
    label_maps = models["label_maps"]

    img_size = int(cfg.get("data", {}).get("img_size", cfg["model"]["vit_img_size"]))

    pil_orig, out, p_mel, p_crit, attr_pred_id = run_inference(
        model=model,
        image_path=img_path,
        img_size=img_size,
        device=device,
    )

    risk_threshold = float(os.environ.get("MODEL_RISK_THRESHOLD", "0.5"))
    checklist_threshold = int(os.environ.get("MODEL_CHECKLIST_THRESHOLD", "3"))
    topk_frac = float(os.environ.get("MODEL_VIZ_TOPK_FRAC", "0.05"))
    thumb_pad = float(os.environ.get("MODEL_THUMB_PAD", "0.18"))
    thumb_min_side = int(os.environ.get("MODEL_THUMB_MIN_SIDE", "96"))
    pdf_image_scale = float(os.environ.get("MODEL_PDF_IMAGE_SCALE", "0.8"))
    inv_maps = {a: invert_label_map(label_maps[a]) for a in ATTR_NAMES}
    labels_by_attr: dict[str, str] = {}
    states_by_attr: dict[str, str] = {}
    points_by_attr: dict[str, int] = {}
    for a in ATTR_NAMES:
        pred_label = inv_maps[a].get(attr_pred_id[a], str(attr_pred_id[a]))
        st = attribute_state(a, pred_label)
        pts = criterion_points(a, pred_label, st)
        labels_by_attr[a] = pred_label
        states_by_attr[a] = st
        points_by_attr[a] = int(pts)

    checklist_total = int(sum(points_by_attr.values()))
    checklist_says_high = checklist_total >= checklist_threshold
    high_risk = (p_mel >= risk_threshold) or checklist_says_high
    clue_attrs = [pretty_attr_name(a) for a in ATTR_NAMES if points_by_attr[a] > 0]
    risk_pct = p_mel * 100.0

    if high_risk:
        line1 = f"Further examination is recommended (estimated melanoma risk: {risk_pct:.1f}%)."
        line2 = "High risk based on the following clues: " + (", ".join(clue_attrs) + "." if clue_attrs else "dermoscopic clues.")
    else:
        line1 = f"No further examination needed (estimated melanoma risk: {risk_pct:.1f}%)."
        line2 = "Low risk of melanoma; no further examination is needed."

    table_data = [["Attribute", "Prediction", "State", "Points", "Probability (%)"]]
    for i, a in enumerate(ATTR_NAMES):
        table_data.append(
            [
                pretty_attr_name(a),
                labels_by_attr[a],
                states_by_attr[a],
                str(points_by_attr[a]),
                f"{float(p_crit[i] * 100.0):.1f}",
            ]
        )
    table_data.append(
        [
            "Total dermoscopic score",
            "",
            "",
            str(checklist_total),
            "",
        ]
    )

    numbered_items: list[dict[str, Any]] = []
    thumbs: list[dict[str, Any]] = []
    if high_risk:
        attn_vit = out["attn_vit"][0:1].detach().cpu()
        orig_w, orig_h = pil_orig.size
        clue_idx = 1
        attrs_to_localize: list[tuple[int, str, int]] = [
            (attr_idx, attr_name, points_by_attr[attr_name])
            for attr_idx, attr_name in enumerate(ATTR_NAMES)
            if points_by_attr[attr_name] > 0
        ]
        if not attrs_to_localize:
            # Fallback for melanoma predictions with low checklist score:
            # still show the most influential attribute region.
            top_attr_idx = int(np.argmax(p_crit))
            top_attr_name = ATTR_NAMES[top_attr_idx]
            attrs_to_localize = [(top_attr_idx, top_attr_name, 0)]

        for attr_idx, attr_name, pts in attrs_to_localize:

            grid = attn_to_grid_vit(attn_vit, token_index=attr_idx)[0]
            grid = normalize_01(grid)
            bbox_sq = grid_to_bbox_largest_connected_hotspot(
                grid,
                img_size=img_size,
                patch_size=16,
                topk_frac=topk_frac,
                connectivity=8,
            )
            bbox_orig = scale_bbox_square_to_original(
                bbox_sq,
                from_size=img_size,
                orig_w=orig_w,
                orig_h=orig_h,
            )
            numbered_items.append({"idx": clue_idx, "bbox": bbox_orig, "color": (220, 0, 0)})

            thumb_crop = crop_with_padding(
                pil_orig,
                bbox_orig,
                pad_ratio=thumb_pad,
                min_side=thumb_min_side,
            )
            thumbs.append(
                {
                    "idx": clue_idx,
                    "attr": pretty_attr_name(attr_name),
                    "points": pts,
                    "prob_pct": float(p_crit[attr_idx] * 100.0),
                    "thumb_pil": thumb_crop,
                }
            )
            clue_idx += 1

    annotated_main = draw_numbered_boxes(pil_orig, numbered_items)

    out_dir, out_base = _make_phase2_output_base(img_path, "weakly_supervised")
    out_png_path = out_dir / f"{out_base}_viz.png"
    out_pdf_path = out_dir / f"{out_base}_explain.pdf"

    c = canvas.Canvas(str(out_pdf_path), pagesize=A4)
    save_pdf_page1_with_grid_table(
        c,
        title="Risk Summary (7-point checklist)",
        line1=line1,
        line2=line2,
        table_data=table_data,
    )
    c.showPage()
    save_pdf_page2_image_with_thumbnails(
        c,
        main_img=annotated_main,
        thumbs=thumbs,
        image_scale=pdf_image_scale,
        numbered_items=numbered_items,
    )
    c.showPage()
    c.save()

    preview_source = "pdf"
    weakly_preview_scale = float(
        os.environ.get("PHASE2_WEAKLY_PREVIEW_SCALE", "1.2")
    )
    try:
        _render_pdf_preview_png(
            out_pdf_path,
            out_png_path,
            scale=weakly_preview_scale,
        )
    except Exception:
        # Safe fallback so inference results still render even if PDF rasterization is unavailable.
        annotated_main.save(out_png_path, format="PNG")
        preview_source = "png_fallback"

    top_attr_idx = int(np.argmax(p_crit))
    top_attribute = ATTR_NAMES[top_attr_idx]
    top_attribute_label = labels_by_attr.get(top_attribute, "")
    prediction = "Melanoma" if high_risk else "Benign"

    return {
        "prediction": prediction,
        "prob_melanoma": p_mel,
        "explanation_image": str(out_png_path),
        "explanation_pdf": str(out_pdf_path),
        "artifact_dir": str(out_dir),
        "checklist_table": table_data[1:],
        "top_attribute": pretty_attr_name(top_attribute),
        "top_attribute_label": top_attribute_label,
        "model_backend": "multiweakly_src_infer.py",
        "model_checkpoint": ckpt_path,
        "preview_source": preview_source,
    }


def _normalize_explanation_kind(kind: str | None) -> str:
    if not kind:
        return "weakly_supervised"
    key = kind.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "weakly": "weakly_supervised",
        "weaklysupervised": "weakly_supervised",
        "weakly_supervised": "weakly_supervised",
        "cluster": "clustering",
        "clustering": "clustering",
        "feature_importance": "feature_importance",
        "feature_important": "feature_importance",
        "featureimportance": "feature_importance",
        "lime": "feature_importance",
        "heatmap": "heatmap",
        "cam": "heatmap",
        "grad_cam": "heatmap",
        "prototree": "prototree",
        "proto_tree": "prototree",
        "prototype": "prototree",
    }
    if key in aliases:
        return aliases[key]
    raise ValueError(
        f"Unsupported explanation kind: {kind}. "
        "Expected one of clustering, feature_importance, heatmap, prototree, weakly_supervised."
    )


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _safe_stem(value: str) -> str:
    stem = Path(value).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._")
    return stem or "image"


def _extract_ph2_image_id(img_path: str, image_name: str | None) -> str | None:
    candidates = []
    if image_name:
        candidates.append(Path(image_name).stem)
    candidates.append(Path(img_path).stem)

    for candidate in candidates:
        match = re.search(r"(IMD\d+)", candidate, flags=re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return None


def _file_md5(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.md5()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


@lru_cache(maxsize=16)
def _index_images_by_md5(images_dir: str) -> dict[str, list[str]]:
    root = Path(images_dir)
    if not root.exists():
        return {}

    allowed_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    index: dict[str, list[str]] = {}
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
            continue
        try:
            digest = _file_md5(path)
        except OSError:
            continue
        index.setdefault(digest, []).append(str(path))
    return index


def _compute_dhash(path: Path, hash_size: int = 16) -> int:
    try:
        from PIL import Image
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(
            "Missing dependency `Pillow` required for clustering image matching."
        ) from e

    with Image.open(path) as img:
        grayscale = img.convert("L").resize((hash_size + 1, hash_size))
        pixels = list(grayscale.getdata())

    bit_value = 0
    for row in range(hash_size):
        row_offset = row * (hash_size + 1)
        for col in range(hash_size):
            left = pixels[row_offset + col]
            right = pixels[row_offset + col + 1]
            bit_value = (bit_value << 1) | int(left >= right)
    return bit_value


@lru_cache(maxsize=16)
def _index_images_by_dhash(images_dir: str) -> list[tuple[int, str]]:
    root = Path(images_dir)
    if not root.exists():
        return []

    allowed_suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"}
    index: list[tuple[int, str]] = []
    for path in root.iterdir():
        if not path.is_file() or path.suffix.lower() not in allowed_suffixes:
            continue
        try:
            image_hash = _compute_dhash(path)
        except Exception:
            continue
        index.append((image_hash, path.stem.upper()))
    return index


def _resolve_clustering_image_id_by_visual_match(
    uploaded_path: Path,
    images_dir: Path,
) -> tuple[str | None, str]:
    try:
        uploaded_hash = _compute_dhash(uploaded_path)
    except OSError:
        return None, "unreadable_uploaded_image"
    except Exception as exc:
        return None, f"visual_match_unavailable({exc})"

    candidates = _index_images_by_dhash(str(images_dir.resolve()))
    if not candidates:
        return None, "no_visual_index"

    scored_matches = sorted(
        ((int((uploaded_hash ^ candidate_hash).bit_count()), stem) for candidate_hash, stem in candidates),
        key=lambda item: (item[0], item[1]),
    )
    best_distance, best_stem = scored_matches[0]
    second_distance = scored_matches[1][0] if len(scored_matches) > 1 else None

    max_distance = int(os.environ.get("PHASE2_CLUSTERING_VISUAL_MATCH_MAX_DISTANCE", "12"))
    min_gap = int(os.environ.get("PHASE2_CLUSTERING_VISUAL_MATCH_MIN_GAP", "8"))

    if best_distance > max_distance:
        return None, f"no_visual_match(best={best_stem},distance={best_distance})"
    if second_distance is not None and (second_distance - best_distance) < min_gap:
        return None, (
            "ambiguous_visual_match("
            f"best={best_stem},distance={best_distance},second_distance={second_distance}"
            ")"
        )
    return best_stem, f"visual_match(distance={best_distance})"


def _resolve_clustering_image_id(
    img_path: str,
    image_name: str | None,
    images_dir: Path | None,
) -> tuple[str | None, str]:
    image_id = _extract_ph2_image_id(img_path=img_path, image_name=image_name)
    if image_id:
        return image_id, "filename"

    if images_dir is None or not images_dir.exists():
        return None, "missing_images_dir"

    uploaded_path = Path(img_path)
    if not uploaded_path.exists():
        return None, "missing_uploaded_image"

    try:
        uploaded_digest = _file_md5(uploaded_path)
    except OSError:
        return None, "unreadable_uploaded_image"

    matches = _index_images_by_md5(str(images_dir.resolve())).get(uploaded_digest, [])
    if not matches:
        return _resolve_clustering_image_id_by_visual_match(uploaded_path, images_dir)

    stems = sorted({Path(p).stem.upper() for p in matches if Path(p).stem})
    if not stems:
        return _resolve_clustering_image_id_by_visual_match(uploaded_path, images_dir)
    return stems[0], "hash_match"


def _load_module_from_file(module_name: str, path: Path) -> ModuleType:
    if not path.exists():
        raise FileNotFoundError(f"Module file not found: {path}")

    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec from: {path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _resolve_project_dir(env_var: str, default_path: Path) -> Path:
    raw = os.environ.get(env_var)
    path = Path(raw) if raw else default_path
    if not path.exists():
        raise FileNotFoundError(f"Project directory not found: {path} (env: {env_var})")
    return path

@st.cache_resource(show_spinner=False)
def _load_clustering_runtime(
    project_dir_str: str,
    artifact_path_str: str,
    data_path_str: str,
    sheet_name_raw: str,
) -> dict[str, Any]:
    import joblib
    import __main__

    project_dir = Path(project_dir_str)
    module = _load_module_from_file(
        "phase2_clustering_cluster",
        project_dir / "cluster.py",
    )

    # Backward compatibility for artifacts saved while cluster.py was run as __main__.
    setattr(__main__, "ClusterToBinaryClassifier", module.ClusterToBinaryClassifier)
    artifact = joblib.load(Path(artifact_path_str))
    if not isinstance(artifact, dict) or "model" not in artifact:
        raise ValueError(f"Invalid clustering artifact format: {artifact_path_str}")

    sheet_name: int | str = int(sheet_name_raw) if str(sheet_name_raw).isdigit() else sheet_name_raw
    bundle = module.load_dataset_bundle(path=Path(data_path_str), sheet_name=sheet_name)

    return {
        "module": module,
        "artifact": artifact,
        "bundle": bundle,
    }


def _default_ph2_xlsx_path() -> Path:
    candidates = [
        LOCAL_PH2_ROOT / "PH2.xlsx",
        APP_DIR / "datasets" / "PH2.xlsx",
        APP_DIR / "datasets" / "PH2_dataset" / "PH2.xlsx",
        Path(r"E:\datasets\Melanoma\PH2_dataset\PH2.xlsx"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return APP_DIR / "datasets" / "PH2.xlsx"


def _default_ph2_images_dir() -> Path:
    candidates = [
        LOCAL_PH2_ROOT / "all_images",
        APP_DIR / "datasets" / "all_images",
        APP_DIR / "datasets" / "PH2_dataset" / "all_images",
        Path(r"E:\datasets\Melanoma\PH2_dataset\all_images"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return APP_DIR / "datasets" / "all_images"


def _default_ph2_split_root() -> Path:
    candidates = [
        LOCAL_PH2_ROOT / "split_data_40",
        APP_DIR / "datasets" / "split_data_40",
        APP_DIR / "datasets" / "PH2_dataset" / "split_data_40",
        Path(r"E:\datasets\Melanoma\PH2_dataset\split_data_40"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return APP_DIR / "datasets" / "split_data_40"


def _make_runtime_output_dir(tag: str) -> Path:
    safe_tag = re.sub(r"[^A-Za-z0-9._-]+", "_", tag).strip("._") or "artifact"
    root = OUTPUTS_DIR / "explanations"
    root.mkdir(parents=True, exist_ok=True)
    out_dir = root / f"{safe_tag}_{uuid.uuid4().hex[:10]}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _make_phase2_output_base(source_name: str, tag: str) -> tuple[Path, str]:
    out_dir = _make_runtime_output_dir(tag)
    base = f"{_safe_stem(source_name)}_{tag}"
    return out_dir, base


def _run_model_weakly_supervised(img_path: str) -> dict[str, Any]:
    model_dir = _resolve_model_dir()
    if not model_dir.exists():
        raise FileNotFoundError(
            f"Model directory not found: {model_dir}\n"
            "Set MODEL_DIR to a valid model repository path."
        )
    if not _is_new_model_repo(model_dir):
        raise RuntimeError(
            f"Unsupported model directory: {model_dir}\n"
            "Expected new model repo layout with src/infer.py and src/models/two_branch_model.py."
        )
    return _run_model_multiweakly(img_path, model_dir)


@st.cache_resource(show_spinner=False)
def _load_feature_importance_runtime(
    project_dir_str: str,
    checkpoint_path_str: str,
    device_arg: str,
) -> dict[str, Any]:
    project_dir = Path(project_dir_str)
    module = _load_module_from_file(
        "phase2_feature_importance_lime",
        project_dir / "lime.py",
    )
    device = module.resolve_device(device_arg)
    model, image_size = module.load_model_from_checkpoint(
        Path(checkpoint_path_str),
        device=device,
    )
    eval_transform = module.build_eval_transform(image_size=image_size)
    return {
        "module": module,
        "device": device,
        "model": model,
        "eval_transform": eval_transform,
    }


def _run_model_feature_importance(img_path: str, image_name: str | None) -> dict[str, Any]:
    import numpy as np

    project_dir = _resolve_project_dir(
        "PHASE2_FEATURE_IMPORTANCE_DIR",
        VENDOR_DIR / "feature_importance",
    )
    checkpoint_path = Path(
        os.environ.get(
            "PHASE2_FEATURE_IMPORTANCE_CKPT",
            str(project_dir / "outputs" / "resnet18_ph2_melanoma_best.pt"),
        )
    )
    device_arg = os.environ.get("PHASE2_FEATURE_IMPORTANCE_DEVICE", "auto")
    runtime = _load_feature_importance_runtime(
        project_dir_str=str(project_dir.resolve()),
        checkpoint_path_str=str(checkpoint_path.resolve()),
        device_arg=device_arg,
    )
    module = runtime["module"]
    device = runtime["device"]
    model = runtime["model"]
    eval_transform = runtime["eval_transform"]

    image_np = module.load_image_np(Path(img_path))
    predict_fn = module.make_predict_fn(
        model=model,
        device=device,
        eval_transform=eval_transform,
    )
    base_probs = predict_fn(np.expand_dims(image_np, axis=0))[0]
    predicted_label = int(np.argmax(base_probs))
    target_label = module.choose_target_label(
        os.environ.get("PHASE2_FEATURE_IMPORTANCE_TARGET_LABEL", "predicted"),
        predicted_label,
    )

    num_samples = int(os.environ.get("PHASE2_FEATURE_IMPORTANCE_NUM_SAMPLES", "300"))
    top_labels = int(os.environ.get("PHASE2_FEATURE_IMPORTANCE_TOP_LABELS", "2"))
    num_features = int(os.environ.get("PHASE2_FEATURE_IMPORTANCE_NUM_FEATURES", "8"))
    min_weight = float(os.environ.get("PHASE2_FEATURE_IMPORTANCE_MIN_WEIGHT", "0.0"))
    positive_only = _env_flag("PHASE2_FEATURE_IMPORTANCE_POSITIVE_ONLY", default=False)
    hide_rest = _env_flag("PHASE2_FEATURE_IMPORTANCE_HIDE_REST", default=False)
    seed = int(os.environ.get("PHASE2_FEATURE_IMPORTANCE_SEED", "42"))

    explainer = module.lime_image.LimeImageExplainer(random_state=seed)
    explanation = explainer.explain_instance(
        image=image_np,
        classifier_fn=predict_fn,
        top_labels=top_labels,
        hide_color=0,
        num_samples=num_samples,
    )
    highlighted, mask = explanation.get_image_and_mask(
        label=target_label,
        positive_only=positive_only,
        hide_rest=hide_rest,
        num_features=num_features,
        min_weight=min_weight,
    )
    heatmap = module.build_weight_heatmap(explanation, target_label=target_label)
    records = module.build_importance_records(explanation, target_label=target_label)

    source_name = img_path
    out_dir, out_base = _make_phase2_output_base(source_name, "feature_importance")
    figure_path = out_dir / f"{out_base}.png"
    pdf_path = out_dir / f"{out_base}.pdf"
    json_path = out_dir / f"{out_base}.json"

    title = (
        f"LIME | predicted={module.BINARY_TO_CLASS[predicted_label]} "
        f"({base_probs[predicted_label]:.2%}) | explained={module.BINARY_TO_CLASS[target_label]}"
    )
    module.save_visualization(
        image_np=image_np,
        highlighted=highlighted,
        mask=mask,
        heatmap=heatmap,
        figure_path=figure_path,
        title=title,
    )
    module.write_lime_pdf_report(
        pdf_path=pdf_path,
        figure_path=figure_path,
        image_name=Path(img_path).name,
        predicted_label=predicted_label,
        prob_melanoma=float(base_probs[1]),
    )

    payload = {
        "image_path": str(img_path),
        "checkpoint": str(checkpoint_path),
        "predicted_label": predicted_label,
        "predicted_label_name": module.BINARY_TO_CLASS[predicted_label],
        "predicted_probabilities": {
            "benign": float(base_probs[0]),
            "melanoma": float(base_probs[1]),
        },
        "explained_label": target_label,
        "explained_label_name": module.BINARY_TO_CLASS[target_label],
        "superpixel_importance": records,
        "figure_path": str(figure_path),
        "report_pdf": str(pdf_path),
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    top_feature = records[0]["superpixel"] if records else None
    return {
        "prediction": "Melanoma" if predicted_label == 1 else "Benign",
        "prob_melanoma": float(base_probs[1]),
        "explanation_image": str(figure_path),
        "explanation_pdf": str(pdf_path),
        "artifact_dir": str(out_dir),
        "top_attribute": f"Superpixel {top_feature}" if top_feature is not None else None,
        "top_attribute_label": module.BINARY_TO_CLASS[target_label],
        "model_backend": "feature_importance_lime.py",
        "model_checkpoint": str(checkpoint_path),
        "explanation_json": str(json_path),
    }


def _run_model_heatmap(img_path: str, image_name: str | None) -> dict[str, Any]:
    import numpy as np
    import torch

    project_dir = _resolve_project_dir(
        "PHASE2_HEATMAP_DIR",
        VENDOR_DIR / "heatmap_explain",
    )
    module = _load_module_from_file(
        "phase2_heatmap_resnet_model",
        project_dir / "resnet_model.py",
    )

    checkpoint_path = Path(
        os.environ.get(
            "PHASE2_HEATMAP_CKPT",
            str(project_dir / "artifacts_fixed_pdf_test" / "resnet18_ph2_melanoma_best.pt"),
        )
    )
    if not checkpoint_path.exists():
        raise FileNotFoundError(f"Heatmap checkpoint not found: {checkpoint_path}")

    device = module.resolve_device(os.environ.get("PHASE2_HEATMAP_DEVICE", "auto"))
    image_size = int(os.environ.get("PHASE2_HEATMAP_IMAGE_SIZE", "224"))
    model = module.create_model(freeze_backbone=False).to(device)
    checkpoint = torch.load(checkpoint_path, map_location=device)
    state_dict = checkpoint.get("model_state_dict", checkpoint) if isinstance(checkpoint, dict) else checkpoint
    model.load_state_dict(state_dict)
    model.eval()
    _, eval_transform = module.build_transforms(image_size=image_size)
    image_tensor = module.load_and_preprocess_image(Path(img_path), eval_transform)

    with torch.no_grad():
        logits = model(image_tensor.unsqueeze(0).to(device))
        probs_before = torch.softmax(logits, dim=1)[0].detach().cpu().numpy()
    prediction_label = int(np.argmax(probs_before))

    cam_target_mode = os.environ.get("PHASE2_HEATMAP_CAM_TARGET", "predicted").strip().lower()
    cam_target = prediction_label if cam_target_mode == "predicted" else 1

    cam_map, probs_after = module.compute_grad_cam(
        model=model,
        image_tensor=image_tensor,
        device=device,
        target_class=cam_target,
    )
    display_image = module.tensor_to_display_image(image_tensor)
    panel_png = module.create_cam_panel(
        image_rgb=display_image,
        cam_map=cam_map,
        image_name=Path(img_path).name,
    )

    source_name = img_path
    out_dir, out_base = _make_phase2_output_base(source_name, "heatmap")
    png_path = out_dir / f"{out_base}.png"
    pdf_path = out_dir / f"{out_base}.pdf"

    panel_png.seek(0)
    png_path.write_bytes(panel_png.getvalue())
    module.write_explanation_pdf(
        pdf_path=pdf_path,
        panel_png=panel_png,
        prediction_label=prediction_label,
        prediction_prob=float(probs_after[1]),
    )

    return {
        "prediction": "Melanoma" if prediction_label == 1 else "Benign",
        "prob_melanoma": float(probs_after[1]),
        "explanation_image": str(png_path),
        "explanation_pdf": str(pdf_path),
        "artifact_dir": str(out_dir),
        "model_backend": "heatmap_grad_cam_resnet18",
        "model_checkpoint": str(checkpoint_path),
    }


def _run_model_clustering(img_path: str, image_name: str | None) -> dict[str, Any]:
    project_dir = _resolve_project_dir(
        "PHASE2_CLUSTERING_DIR",
        VENDOR_DIR / "clustering",
    )

    artifact_path = Path(
        os.environ.get(
            "PHASE2_CLUSTERING_MODEL_ARTIFACT",
            str(project_dir / "artifacts" / "melanoma_cluster_model.joblib"),
        )
    )
    if not artifact_path.exists():
        raise FileNotFoundError(f"Clustering model artifact not found: {artifact_path}")

    data_path = Path(
        os.environ.get(
            "PHASE2_CLUSTERING_DATA_PATH",
            str(_default_ph2_xlsx_path()),
        )
    )
    sheet_raw = os.environ.get("PHASE2_CLUSTERING_SHEET", "Sheet1")

    runtime = _load_clustering_runtime(
        project_dir_str=str(project_dir.resolve()),
        artifact_path_str=str(artifact_path.resolve()),
        data_path_str=str(data_path.resolve()),
        sheet_name_raw=sheet_raw,
    )
    module = runtime["module"]
    artifact = runtime["artifact"]
    bundle = runtime["bundle"]

    source_name = img_path
    out_dir, out_base = _make_phase2_output_base(source_name, "clustering")
    pdf_path = out_dir / f"{out_base}.pdf"

    images_dir = Path(
        os.environ.get(
            "PHASE2_CLUSTERING_IMAGES_DIR",
            str(_default_ph2_images_dir()),
        )
    )
    images_dir = images_dir if images_dir.exists() else None
    image_id, id_source = _resolve_clustering_image_id(
        img_path=img_path,
        image_name=image_name,
        images_dir=images_dir,
    )
    if image_id is None:
        source_name = image_name or Path(img_path).name
    artifact_path = Path(
        os.environ.get(
            "PHASE2_CLUSTERING_MODEL_ARTIFACT",
            str(project_dir / "artifacts" / "melanoma_cluster_model.joblib"),
        )
    )
    if not artifact_path.exists():
        raise FileNotFoundError(f"Clustering model artifact not found: {artifact_path}")

    data_path = Path(
        os.environ.get(
            "PHASE2_CLUSTERING_DATA_PATH",
            str(_default_ph2_xlsx_path()),
        )
    )
    sheet_raw = os.environ.get("PHASE2_CLUSTERING_SHEET", "Sheet1")

    runtime = _load_clustering_runtime(
        project_dir_str=str(project_dir.resolve()),
        artifact_path_str=str(artifact_path.resolve()),
        data_path_str=str(data_path.resolve()),
        sheet_name_raw=sheet_raw,
    )
    module = runtime["module"]
    artifact = runtime["artifact"]
    bundle = runtime["bundle"]

    source_name = img_path
    out_dir, out_base = _make_phase2_output_base(source_name, "clustering")
    pdf_path = out_dir / f"{out_base}.pdf"
    global_png_path = out_dir / f"{out_base}_global.png"

    images_dir = Path(
        os.environ.get(
            "PHASE2_CLUSTERING_IMAGES_DIR",
            str(_default_ph2_images_dir()),
        )
    )
    images_dir = images_dir if images_dir.exists() else None
    image_id, id_source = _resolve_clustering_image_id(
        img_path=img_path,
        image_name=image_name,
        images_dir=images_dir,
    )
    if image_id is None:
        source_name = image_name or Path(img_path).name
        raise ValueError(
            "Could not map the uploaded file to an image ID for clustering inference.\n"
            f"Uploaded file: {source_name}\n"
            f"Resolution attempt: {id_source}\n"
            "This clustering model explains tabular features linked to image IDs.\n"
            "Use an image filename (e.g., IMD033.jpg) or a renamed/reformatted copy of an original image."
        )

    info = module.generate_explanation_pdf(
        bundle=bundle,
        model=artifact["model"],
        image_input=image_id,
        output_pdf_path=pdf_path,
        images_dir=images_dir,
    )

    nearest_latent_cases: list[dict[str, Any]] = []
    for case in info.get("closest_cases", []):
        if not isinstance(case, dict):
            continue
        nearest_latent_cases.append(
            {
                "image_key": str(case.get("image_key", "")),
                "distance": float(case.get("distance", float("nan"))),
                "true_label": int(case.get("true_label", 0)),
                "predicted_label": int(case.get("predicted_label", 0)),
                "image_path": case.get("image_path"),
            }
        )

    preview_source = None
    clustering_preview_scale = float(
        os.environ.get("PHASE2_CLUSTERING_PREVIEW_SCALE", "1.2")
    )
    try:
        _render_pdf_preview_png(
            pdf_path,
            global_png_path,
            page_1based=99,
            scale=clustering_preview_scale,
        )
        preview_source = "pdf"
    except Exception:
        preview_source = None

    predicted_label = int(info.get("predicted_label", 0))
    cluster_rate = info.get("cluster_melanoma_rate")
    prob_melanoma = float(cluster_rate) if isinstance(cluster_rate, (int, float)) else None

    if id_source == "filename":
        explanation_note = (
            "Clustering explanation is based on tabular features linked to this image ID."
        )
    elif id_source == "hash_match":
        explanation_note = (
            f"Uploaded image was matched to image ID {image_id} by exact file content, "
            "then explained with tabular features."
        )
    else:
        explanation_note = (
            f"Uploaded image was matched to image ID {image_id} by visual similarity, "
            "then explained with tabular features."
        )

    return {
        "prediction": "Melanoma" if predicted_label == 1 else "Benign",
        "prob_melanoma": prob_melanoma,
        "explanation_image": str(global_png_path) if global_png_path.exists() else None,
        "explanation_image_global": str(global_png_path) if global_png_path.exists() else None,
        "global_preview_label": "latent space position",
        "explanation_pdf": str(pdf_path),
        "artifact_dir": str(out_dir),
        "explanation_note": explanation_note,
        "show_pdf_inline": False,
        "top_attribute": "Assigned cluster",
        "top_attribute_label": str(info.get("cluster_id", "")),
        "resolved_image_id": image_id,
        "resolved_image_id_source": id_source,
        "nearest_latent_cases": nearest_latent_cases,
        "model_backend": "clustering_cluster.py",
        "model_checkpoint": str(artifact_path),
        "preview_source": preview_source,
    }


def _parse_prototree_prediction(dot_path: Path) -> str | None:
    if not dot_path.exists():
        return None
    text = dot_path.read_text(encoding="utf-8", errors="ignore")
    labels = re.findall(r'label="(melanoma|benign)"', text, flags=re.IGNORECASE)
    if not labels:
        return None
    return "Melanoma" if labels[-1].lower() == "melanoma" else "Benign"


def _run_model_prototree(img_path: str, image_name: str | None) -> dict[str, Any]:
    project_dir = _resolve_project_dir(
        "PHASE2_PROTOTREE_DIR",
        VENDOR_DIR / "ProtoTree",
    )
    run_dir = Path(
        os.environ.get(
            "PHASE2_PROTOTREE_RUN_DIR",
            str(project_dir / "runs" / "prototree_ph2_depth3"),
        )
    )
    results_root = Path(
        os.environ.get(
            "PHASE2_PROTOTREE_RESULTS_DIR",
            str(_make_runtime_output_dir("prototree")),
        )
    )
    results_root.mkdir(parents=True, exist_ok=True)

    dataset_root = None
    dataset_root_raw = os.environ.get("PHASE2_PROTOTREE_DATASET_ROOT", "").strip()
    if dataset_root_raw:
        candidate = Path(dataset_root_raw)
        if candidate.exists():
            dataset_root = candidate
    else:
        local_split_root = LOCAL_PH2_ROOT / "split_data_40"
        legacy_split_root = Path(r"E:\datasets\Melanoma\PH2_dataset\split_data_40")
        for candidate in (local_split_root, legacy_split_root):
            if candidate.exists():
                dataset_root = candidate
                break

    class_names_raw = os.environ.get(
        "PHASE2_PROTOTREE_CLASS_NAMES",
        "benign,melanoma",
    )
    class_names = [
        part.strip()
        for part in re.split(r"[,;|]", class_names_raw)
        if part.strip()
    ]
    if len(class_names) < 2:
        raise ValueError(
            "PHASE2_PROTOTREE_CLASS_NAMES must contain at least two class names."
        )

    merged_name = f"{_safe_stem(img_path)}_{uuid.uuid4().hex[:8]}_global_plus_local.pdf"
    command = [
        sys.executable,
        str(project_dir / "single_infer.py"),
        "--run_dir",
        str(run_dir),
        "--sample_path",
        str(Path(img_path).resolve()),
        "--results_dir",
        str(results_root),
        "--merged_name",
        merged_name,
        "--image_size",
        os.environ.get("PHASE2_PROTOTREE_IMAGE_SIZE", "224"),
        "--upsample_threshold",
        os.environ.get("PHASE2_PROTOTREE_UPSAMPLE_THRESHOLD", "0.98"),
        "--class_names",
        *class_names,
    ]
    if dataset_root is not None:
        command.extend(["--dataset_root", str(dataset_root)])
    if _env_flag("PHASE2_PROTOTREE_DISABLE_CUDA", default=False):
        command.append("--disable_cuda")

    proc = subprocess.run(
        command,
        cwd=str(project_dir),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            "ProtoTree inference failed.\n"
            f"Command: {' '.join(command)}\n"
            f"STDOUT:\n{proc.stdout}\n"
            f"STDERR:\n{proc.stderr}"
        )

    sample_stem = Path(img_path).stem
    pdf_path = results_root / sample_stem / merged_name
    if not pdf_path.exists():
        for line in proc.stdout.splitlines():
            if line.startswith("Merged PDF:"):
                candidate = Path(line.split(":", 1)[1].strip())
                if candidate.exists():
                    pdf_path = candidate
                    break
    if not pdf_path.exists():
        raise FileNotFoundError(
            f"ProtoTree merged PDF was not created.\nExpected: {pdf_path}\nSTDOUT:\n{proc.stdout}"
        )

    global_png_path = pdf_path.with_name(f"{pdf_path.stem}_global_preview.png")
    local_png_path = pdf_path.with_name(f"{pdf_path.stem}_local_preview.png")
    preview_source = None
    prototree_preview_scale = float(
        os.environ.get("PHASE2_PROTOTREE_PREVIEW_SCALE", "1.2")
    )
    try:
        _render_pdf_preview_png(
            pdf_path,
            global_png_path,
            page_1based=1,
            scale=prototree_preview_scale,
        )
        _render_pdf_preview_png(
            pdf_path,
            local_png_path,
            page_1based=2,
            scale=prototree_preview_scale,
        )
        preview_source = "pdf"
    except Exception:
        preview_source = None

    predvis_dot = pdf_path.parent / "predvis.dot"
    prediction = _parse_prototree_prediction(predvis_dot)

    return {
        "prediction": prediction,
        "prob_melanoma": None,
        "explanation_image": str(local_png_path) if local_png_path.exists() else None,
        "explanation_image_global": str(global_png_path) if global_png_path.exists() else None,
        "explanation_image_local": str(local_png_path) if local_png_path.exists() else None,
        "explanation_pdf": str(pdf_path),
        "artifact_dir": str(results_root),
        "model_backend": "prototree_single_infer.py",
        "model_checkpoint": str(run_dir / "checkpoints" / "pruned_and_projected"),
        "preview_source": preview_source,
    }


def run_model(
    img_path: str,
    explanation_kind: str | None = None,
    image_name: str | None = None,
) -> dict[str, Any]:
    """Run inference for one explanation backend and return unified output fields."""
    kind = _normalize_explanation_kind(explanation_kind)

    # Deployed hosts serve the cache built by precompute.py; the live model paths
    # below need torch, Graphviz and the vendor/ tree, none of which ship to prod.
    if precomputed_backend.available():
        return precomputed_backend.load(kind, img_path)

    if kind == "weakly_supervised":
        return _run_model_weakly_supervised(img_path)
    if kind == "clustering":
        return _run_model_clustering(img_path, image_name=image_name)
    if kind == "feature_importance":
        return _run_model_feature_importance(img_path, image_name=image_name)
    if kind == "heatmap":
        return _run_model_heatmap(img_path, image_name=image_name)
    if kind == "prototree":
        return _run_model_prototree(img_path, image_name=image_name)
    raise RuntimeError(f"Unexpected explanation kind: {kind}")


def save_uploaded_image(uploaded_file) -> str:
    """Save a Streamlit uploaded file to disk and return the file path."""
    suffix = Path(uploaded_file.name).suffix or ".png"
    with tempfile.NamedTemporaryFile(
        delete=False,
        suffix=suffix,
        prefix="mel_app_upload_",
        ) as f:
        f.write(uploaded_file.getbuffer())
        return f.name


def delete_temp_file(path: str | Path | None) -> None:
    if not path:
        return
    try:
        target = Path(path)
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
    except OSError:
        return


def cleanup_result_artifacts(result: dict[str, Any] | None) -> None:
    if not isinstance(result, dict):
        return

    artifact_dir = result.get("artifact_dir")
    if artifact_dir:
        delete_temp_file(artifact_dir)
        result["artifact_dir"] = None

    for key in (
        "explanation_image",
        "explanation_image_global",
        "explanation_image_local",
        "explanation_pdf",
        "explanation_json",
    ):
        path = result.get(key)
        if path:
            delete_temp_file(path)
            result[key] = None


def cleanup_result_cache(results: Any) -> None:
    if isinstance(results, dict):
        if "prediction" in results or "artifact_dir" in results:
            cleanup_result_artifacts(results)
            return
        for value in results.values():
            cleanup_result_cache(value)


def render_phase2_explanation_ratings(key_prefix: str) -> dict[str, int]:
    """Render five explainability ratings (1-10 stars each) and return values."""
    st.markdown("### Đánh giá phần giải thích")
    st.caption("Chấm mỗi tiêu chí từ 1 đến 10 sao (10 = cao nhất).")

    ratings: dict[str, int] = {}
    for metric_key, metric_label, metric_prompt in PHASE2_EXPLANATION_METRICS:
        ratings[metric_key] = st.slider(
            f"{metric_label} (1-10 sao)",
            min_value=1,
            max_value=10,
            value=5,
            step=1,
            help=metric_prompt,
            key=f"{key_prefix}_{metric_key}_stars",
        )
    return ratings


def phase2_explanation_rating_headers() -> list[str]:
    return [f"{label}_Stars" for _, label, _ in PHASE2_EXPLANATION_METRICS]


def phase2_explanation_rating_values(ratings: dict[str, int]) -> list[int | None]:
    return [ratings.get(metric_key) for metric_key, _, _ in PHASE2_EXPLANATION_METRICS]


def render_pdf_in_ui(pdf_path: str | Path, height: int = 900) -> None:
    """Embed a PDF in Streamlit as an iframe."""
    p = Path(pdf_path)
    if not p.exists():
        st.warning(f"Không tìm thấy tệp PDF: {p}")
        return
    b64 = base64.b64encode(p.read_bytes()).decode("utf-8")
    html(
        f'<iframe src="data:application/pdf;base64,{b64}" width="100%" height="{height}" type="application/pdf"></iframe>',
        height=height + 16,
        scrolling=True,
    )


### -------------------------
### Save to CSV
### -------------------------
def save_to_csv(filename, row, headers=None):
    """Append a row to a CSV file. Create file with headers if it doesn't exist."""
    filename = Path(filename)
    filename.parent.mkdir(parents=True, exist_ok=True)
    file_exists = filename.is_file() and filename.stat().st_size > 0

    # Write a UTF-8 BOM when creating the file, so Excel reads non-ASCII
    # responses (Vietnamese diacritics, for instance) correctly instead of as
    # mojibake. Only on creation: utf-8-sig in append mode would insert a BOM
    # partway through the file and corrupt the row.
    encoding = "utf-8-sig" if not file_exists else "utf-8"

    with filename.open("a", newline="", encoding=encoding) as f:
        writer = csv.writer(f)
        if not file_exists and headers:
            writer.writerow(headers)
        writer.writerow(row)

    # The local CSV is wiped on every restart of a hosted app; Sheets is what
    # actually persists. Tab name mirrors the CSV filename.
    append_to_sheet(row, worksheet_name=Path(filename).stem, headers=headers)


### -------------------------
### Save to Google Sheets
### -------------------------
SHEET_NAME = os.environ.get("SURVEY_SHEET_NAME", "Melanoma_Survey_Results")
SCOPE = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]


def sheets_configured() -> bool:
    """True when Google Sheets credentials are present in either location."""
    try:
        if "gcp_service_account" in st.secrets:
            return True
    except Exception:
        pass
    return (APP_DIR / "service_account.json").is_file()


@st.cache_resource(show_spinner=False)
def _sheet_client():
    """Authorize once per server process. Prefers st.secrets, which is how
    credentials reach a deployed host -- service_account.json must never be
    committed to the repo."""
    import gspread  # type: ignore[import-not-found]
    from oauth2client.service_account import ServiceAccountCredentials  # type: ignore[import-not-found]

    try:
        secret = st.secrets["gcp_service_account"]
    except Exception:
        secret = None

    if secret is not None:
        creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(secret), SCOPE)
    else:
        creds_path = APP_DIR / "service_account.json"
        if not creds_path.is_file():
            raise FileNotFoundError(
                "No Google Sheets credentials: add [gcp_service_account] to "
                "Streamlit secrets, or place service_account.json beside utils.py."
            )
        creds = ServiceAccountCredentials.from_json_keyfile_name(str(creds_path), SCOPE)

    return gspread.authorize(creds)


def _worksheet(name: str, headers: list[str] | None):
    """Fetch a tab by name, creating it (with a header row) if absent.

    Also restores a header row that has gone missing. Tools read these tabs with
    get_all_records(), which treats row 1 as the column names -- so a tab whose
    header was deleted silently consumes the first response as its header and
    mislabels every column after it.
    """
    spreadsheet = _sheet_client().open(SHEET_NAME)
    try:
        worksheet = spreadsheet.worksheet(name)
    except Exception:
        worksheet = spreadsheet.add_worksheet(
            title=name, rows=1000, cols=max(len(headers or []), 12)
        )
        if headers:
            worksheet.append_row(list(headers))
        return worksheet

    if headers:
        try:
            first = worksheet.row_values(1)
        except Exception:
            first = []
        # Every header this app writes begins with Timestamp, so a first cell
        # that does not is either empty or a data row that has drifted up.
        if not first or (first[0] or "").strip() != "Timestamp":
            worksheet.insert_row(list(headers), index=1)
    return worksheet


@st.cache_data(ttl=60, show_spinner=False)
def sheets_status() -> tuple[bool, str]:
    """Actually try to reach the spreadsheet and report precisely what is wrong.

    'Nothing is being saved' has several distinct causes that need different
    fixes, so this distinguishes them rather than reporting a generic failure.
    Cached briefly so it is not re-run on every rerun.
    """
    if not sheets_configured():
        return False, (
            "No credentials found. Add the [gcp_service_account] block to this "
            "app's Secrets (Manage app -> Settings -> Secrets). Creating the "
            "Google Sheet alone is not enough -- the app also needs a service "
            "account key to write to it."
        )
    try:
        client = _sheet_client()
    except Exception as exc:
        return False, (
            f"Credentials present but rejected by Google: {exc}. The key is "
            "usually malformed -- regenerate the Secrets block with "
            "make_secrets.py rather than editing private_key by hand."
        )
    try:
        client.open(SHEET_NAME)
    except Exception as exc:
        name = type(exc).__name__
        if "SpreadsheetNotFound" in name:
            try:
                who = dict(st.secrets["gcp_service_account"]).get("client_email", "the service account")
            except Exception:
                who = "the service account"
            return False, (
                f"Signed in to Google, but no spreadsheet named '{SHEET_NAME}' is "
                f"visible. Either the name differs (it must match exactly), or the "
                f"Sheet has not been shared with {who} as an Editor."
            )
        if "APIError" in name and "403" in str(exc):
            return False, (
                f"Google refused access ({exc}). Enable both the Google Sheets API "
                "and the Google Drive API for this project in the Cloud Console."
            )
        return False, f"Could not open '{SHEET_NAME}': {exc}"
    return True, f"Connected to '{SHEET_NAME}'."


def append_to_sheet(row, worksheet_name: str = "participants", headers=None) -> bool:
    """Append one row to a tab of the survey spreadsheet.

    Returns True on success. A deployed host has an ephemeral filesystem, so
    Sheets is the only durable store -- a failure here means the response is
    LOST and must be surfaced to the participant, never swallowed.
    """
    if not sheets_configured():
        # Silently returning here would let the app report "saved" while the
        # row goes only to a disk that is wiped on the next restart.
        st.error(
            "Câu trả lời này KHÔNG được lưu vào bộ nhớ vĩnh viễn: khảo sát chưa "
            "được cấu hình thông tin đăng nhập Google Sheets. Vui lòng báo cho "
            "nhóm nghiên cứu trước khi tiếp tục, nếu không các câu trả lời sẽ bị mất."
        )
        return False
    try:
        _worksheet(worksheet_name, headers).append_row(
            ["" if value is None else str(value) for value in row]
        )
        return True
    except Exception as exc:
        st.error(
            f"Không thể lưu câu trả lời của Quý bác sĩ vào bảng kết quả: {exc}. "
            "Vui lòng chụp màn hình thông báo này và liên hệ nhóm nghiên cứu "
            "trước khi tiếp tục."
        )
        return False


### -------------------------
### Save participant registration
### -------------------------
def save_participant(name, email):
    """Save participant name and email to both CSV and Google Sheets."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    row = [timestamp, name, email]

    headers = ["Timestamp", "Name", "Email"]
    save_to_csv(DATA_DIR / "participants.csv", row, headers)
