"""Vietnamese display strings for values that come out of the model cache.

The survey is administered to Vietnamese clinicians, so every string a
participant sees is Vietnamese -- but everything written to the results
spreadsheet stays in English, so fetch_responses.py, reconcile_phase4.py and
dedupe_responses.py keep matching the same column names and values, and the
precomputed manifest never has to be regenerated. This module is that boundary:
it is only ever called on the display path, never on the write path.
"""

from __future__ import annotations

from typing import Any

# Model prediction / ground-truth labels. The English keys are what the manifest
# holds and what the survey saves; only the values reach the screen.
DIAGNOSIS: dict[str, str] = {
    "benign": "Lành tính",
    "melanoma": "U hắc tố ác tính (Melanoma)",
    "non-melanoma": "Không phải u hắc tố ác tính",
    "unavailable": "Không có kết quả",
}

# 7-point checklist attributes. The English term is kept in brackets: it is the
# form Vietnamese dermatologists see in the dermoscopy literature, and dropping
# it would make the ratings harder to compare with the English-language run.
ATTRIBUTES: dict[str, str] = {
    "pigment network": "Mạng lưới sắc tố (pigment network)",
    "streaks": "Vệt sắc tố (streaks)",
    "pigmentation": "Vùng tăng sắc tố (pigmentation)",
    "regression structures": "Cấu trúc thoái triển (regression structures)",
    "dots and globules": "Chấm và cầu sắc tố (dots and globules)",
    "blue whitish veil": "Màn xanh trắng (blue whitish veil)",
    "vascular structures": "Cấu trúc mạch máu (vascular structures)",
    "total dermoscopic score": "Tổng điểm soi da",
    "assigned cluster": "Cụm được gán",
}

# Same attributes without the English gloss, for the generated PDFs: the table
# column there is a fixed 130pt and the clue captions are truncated at 36
# characters, so the long form would overflow or be cut mid-word.
ATTRIBUTES_SHORT: dict[str, str] = {
    "pigment network": "Mạng lưới sắc tố",
    "streaks": "Vệt sắc tố",
    "pigmentation": "Vùng tăng sắc tố",
    "regression structures": "Cấu trúc thoái triển",
    "dots and globules": "Chấm và cầu sắc tố",
    "blue whitish veil": "Màn xanh trắng",
    "vascular structures": "Cấu trúc mạch máu",
    "total dermoscopic score": "Tổng điểm soi da",
    "assigned cluster": "Cụm được gán",
}

# Attribute states as the weakly supervised model reports them.
STATES: dict[str, str] = {
    "absent": "không có",
    "present": "có",
    "typical": "điển hình",
    "atypical": "không điển hình",
    "regular": "đều",
    "irregular": "không đều",
    "diffuse irregular": "lan tỏa không đều",
    "blue areas": "vùng màu xanh",
    "combinations": "dạng phối hợp",
    "within regression": "trong vùng thoái triển",
}

# Column headers of the attribute-score table.
COLUMNS: dict[str, str] = {
    "Attribute": "Đặc điểm",
    "Prediction": "Dự đoán",
    "State": "Trạng thái",
    "Points": "Điểm",
    "Attr score": "Điểm đặc điểm",
    "Probability (%)": "Xác suất (%)",
}

# Free-text fields the manifest carries through to the page.
NOTES: dict[str, str] = {
    "clustering explanation is based on tabular features linked to this image id.":
        "Phần giải thích của mô hình phân cụm dựa trên các đặc trưng dạng bảng "
        "gắn với mã ảnh này, không dựa trên điểm ảnh gốc.",
}

PREVIEW_LABELS: dict[str, str] = {
    "latent space position": "vị trí trong không gian tiềm ẩn",
    "global explanation": "giải thích tổng thể",
    "local explanation": "giải thích cục bộ",
}

# How the cache matched this image; shown as a caption in Phase 4.
ID_SOURCES: dict[str, str] = {
    "filename": "theo tên tệp",
    "image_key": "theo mã ảnh",
}


def _lookup(table: dict[str, str], value: Any) -> str:
    """Translate `value` via `table`, falling back to the original text.

    Unknown values pass through rather than raising: a manifest regenerated with
    a new state or attribute must still render, in English, instead of taking
    the page down mid-survey.
    """
    text = "" if value is None else str(value)
    return table.get(text.strip().lower(), text)


def diagnosis(value: Any) -> str:
    return _lookup(DIAGNOSIS, value)


def attribute(value: Any) -> str:
    return _lookup(ATTRIBUTES, value)


def attribute_short(value: Any) -> str:
    """Vietnamese attribute name without the English gloss, for tight layouts."""
    return _lookup(ATTRIBUTES_SHORT, value)


def state(value: Any) -> str:
    return _lookup(STATES, value)


def note(value: Any) -> str:
    return _lookup(NOTES, value)


def preview_label(value: Any) -> str:
    return _lookup(PREVIEW_LABELS, value)


def id_source(value: Any) -> str:
    return _lookup(ID_SOURCES, value)


def term(value: Any) -> str:
    """Translate a cell that may be an attribute name, a state or a diagnosis."""
    text = "" if value is None else str(value)
    key = text.strip().lower()
    for table in (ATTRIBUTES, STATES, DIAGNOSIS):
        if key in table:
            return table[key]
    return text


def pdf_table(table_data: list[list[Any]]) -> list[list[Any]]:
    """Localize a header-row-plus-body table for a generated PDF.

    Row 0 is translated as column headers, the rest as attribute names and
    states, using the short attribute form so the fixed column widths hold.
    """
    if not table_data:
        return table_data

    header = [COLUMNS.get(str(cell), str(cell)) for cell in table_data[0]]
    body = [
        [attribute_short(cell) if index == 0 else state(cell) for index, cell in enumerate(row)]
        for row in table_data[1:]
    ]
    return [header, *body]


def checklist_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Localize the attribute-score table for display.

    Both the header keys and the text cells are translated; numeric cells
    (Points, Probability) are left exactly as the model produced them.
    """
    localized: list[dict[str, Any]] = []
    for row in rows:
        new_row: dict[str, Any] = {}
        for column, value in row.items():
            header = COLUMNS.get(str(column), str(column))
            if column in ("Attribute", "Prediction", "State"):
                new_row[header] = term(value)
            else:
                new_row[header] = value
        localized.append(new_row)
    return localized
