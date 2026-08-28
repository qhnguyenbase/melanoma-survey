"""Serve explanations from the `precomputed/` cache instead of running the models.

Deployed hosts get no GPU and about 1-2 GB of RAM, while a single live Phase 4
question peaks at 1.67 GB and takes ~15 s of CPU. Every survey image is a fixed
file and inference is deterministic, so the results are generated once by
`precompute.py` and simply replayed here.

Importing this module must never pull in torch: that is the whole point.
"""

from __future__ import annotations

import hashlib
import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
PRECOMPUTED_DIR = APP_DIR / "precomputed"
MANIFEST_PATH = PRECOMPUTED_DIR / "manifest.json"

# Fields whose values are paths relative to PRECOMPUTED_DIR.
FILE_FIELDS = (
    "explanation_image",
    "explanation_image_global",
    "explanation_image_local",
    "explanation_pdf",
)


class PrecomputedMiss(KeyError):
    """No cached result for this image and backend."""


@lru_cache(maxsize=1)
def _manifest() -> dict[str, Any]:
    if not MANIFEST_PATH.is_file():
        return {}
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=512)
def _image_key(path_str: str) -> str:
    """Content hash, matching precompute.py. Phase 2 and Phase 3 reuse filenames
    for different images, so the name alone is not a safe key."""
    return hashlib.sha256(Path(path_str).read_bytes()).hexdigest()[:16]


def available() -> bool:
    """True when the cache should be used. Set SURVEY_LIVE_INFERENCE=1 to force
    the real models locally (needs torch and the vendor/ tree)."""
    if os.environ.get("SURVEY_LIVE_INFERENCE") == "1":
        return False
    return bool(_manifest())


def load(kind: str, img_path: str) -> dict[str, Any]:
    """Return the cached result for one image and backend, with every path
    resolved back to an absolute location on this machine."""
    manifest = _manifest()
    if not manifest:
        raise PrecomputedMiss(
            f"No precomputed cache at {MANIFEST_PATH}. "
            "Run `python precompute.py` locally and commit precomputed/."
        )

    key = f"{kind}|{_image_key(img_path)}"
    entry = manifest.get(key)
    if entry is None:
        raise PrecomputedMiss(
            f"No precomputed result for {Path(img_path).name} ({kind}). "
            "Regenerate the cache with `python precompute.py`."
        )

    result = dict(entry)

    def absolute(value: Any) -> str | None:
        if not value:
            return None
        resolved = PRECOMPUTED_DIR / str(value)
        return str(resolved) if resolved.exists() else None

    for field in FILE_FIELDS:
        result[field] = absolute(result.get(field))

    cases = result.get("nearest_latent_cases")
    if isinstance(cases, list):
        rebuilt = []
        for case in cases:
            if not isinstance(case, dict):
                continue
            case = dict(case)
            case["image_path"] = absolute(case.get("image_path"))
            rebuilt.append(case)
        result["nearest_latent_cases"] = rebuilt

    result["artifact_dir"] = str(PRECOMPUTED_DIR / str(result.get("artifact_dir", "")))
    result["image_path"] = img_path
    return result


def coverage() -> dict[str, int]:
    """Entries per backend; used by the deployment self-check."""
    counts: dict[str, int] = {}
    for key in _manifest():
        kind = key.split("|", 1)[0]
        counts[kind] = counts.get(kind, 0) + 1
    return counts
