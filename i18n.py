"""English display strings for values that come out of the model cache.

Everything written to the results spreadsheet stays in the raw form the model
produces, so fetch_responses.py, reconcile_phase4.py and dedupe_responses.py
keep matching the same column names and values, and the precomputed manifest
never has to be regenerated. This module is that boundary: it is only ever
called on the display path, never on the write path.

Its job is presentation, not translation -- the cache already holds English, but
it holds it in the model's own casing and shorthand ("non-melanoma", "pigment
network", "atypical"). These tables turn that into the wording a clinician
reads on screen and in the generated reports.
"""

from __future__ import annotations

from typing import Any

# Model prediction / ground-truth labels. The keys are what the manifest holds
# and what the survey saves; only the values reach the screen.
DIAGNOSIS: dict[str, str] = {
    "benign": "Benign",
    "melanoma": "Melanoma",
    "non-melanoma": "Non-melanoma",
    "unavailable": "Unavailable",
}

# 7-point checklist attributes, as they appear in the dermoscopy literature.
ATTRIBUTES: dict[str, str] = {
    "pigment network": "Pigment network",
    "streaks": "Streaks",
    "pigmentation": "Pigmentation",
    "regression structures": "Regression structures",
    "dots and globules": "Dots and globules",
    "blue whitish veil": "Blue whitish veil",
    "vascular structures": "Vascular structures",
    "total dermoscopic score": "Total dermoscopic score",
    "assigned cluster": "Assigned cluster",
}

# The form used in the generated PDFs, where the table column is a fixed 130pt
# and the clue captions are truncated at 36 characters. Every English name fits
# inside both limits, so this matches ATTRIBUTES; it stays a separate table
# because the two are free to diverge if a longer attribute name is added.
ATTRIBUTES_SHORT: dict[str, str] = {
    "pigment network": "Pigment network",
    "streaks": "Streaks",
    "pigmentation": "Pigmentation",
    "regression structures": "Regression structures",
    "dots and globules": "Dots and globules",
    "blue whitish veil": "Blue whitish veil",
    "vascular structures": "Vascular structures",
    "total dermoscopic score": "Total dermoscopic score",
    "assigned cluster": "Assigned cluster",
}

# Attribute states as the weakly supervised model reports them.
STATES: dict[str, str] = {
    "absent": "Absent",
    "present": "Present",
    "typical": "Typical",
    "atypical": "Atypical",
    "regular": "Regular",
    "irregular": "Irregular",
    "diffuse irregular": "Diffuse irregular",
    "blue areas": "Blue areas",
    "combinations": "Combinations",
    "within regression": "Within regression",
}

# Column headers of the attribute-score table.
COLUMNS: dict[str, str] = {
    "Attribute": "Attribute",
    "Prediction": "Prediction",
    "State": "State",
    "Points": "Points",
    "Attr score": "Attribute score",
    "Probability (%)": "Probability (%)",
}

# Free-text fields the manifest carries through to the page.
NOTES: dict[str, str] = {
    "clustering explanation is based on tabular features linked to this image id.":
        "The clustering explanation is based on tabular features linked to this "
        "image ID, not on the raw pixels.",
}

PREVIEW_LABELS: dict[str, str] = {
    "latent space position": "latent space position",
    "global explanation": "global explanation",
    "local explanation": "local explanation",
}

# How the cache matched this image; shown as a caption in Phase 4.
ID_SOURCES: dict[str, str] = {
    "filename": "by filename",
    "image_key": "by image key",
}


def _lookup(table: dict[str, str], value: Any) -> str:
    """Format `value` via `table`, falling back to the original text.

    Unknown values pass through rather than raising: a manifest regenerated with
    a new state or attribute must still render, in its raw form, instead of
    taking the page down mid-survey.
    """
    text = "" if value is None else str(value)
    return table.get(text.strip().lower(), text)


def diagnosis(value: Any) -> str:
    return _lookup(DIAGNOSIS, value)


def attribute(value: Any) -> str:
    return _lookup(ATTRIBUTES, value)


def attribute_short(value: Any) -> str:
    """Shortest attribute form, for tight layouts."""
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
    """Format a cell that may be an attribute name, a state or a diagnosis."""
    text = "" if value is None else str(value)
    key = text.strip().lower()
    for table in (ATTRIBUTES, STATES, DIAGNOSIS):
        if key in table:
            return table[key]
    return text


def pdf_table(table_data: list[list[Any]]) -> list[list[Any]]:
    """Format a header-row-plus-body table for a generated PDF.

    Row 0 is treated as column headers, the rest as attribute names and states,
    using the short attribute form so the fixed column widths hold.
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
    """Format the attribute-score table for display.

    Both the header keys and the text cells are formatted; numeric cells
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
