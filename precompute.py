"""Pre-generate every explanation the survey can display.

Run once locally (GPU is fine and faster); commit `precomputed/`. The deployed
app then serves these artifacts and needs no torch, ProtoTree or Graphviz.

    python precompute.py                 # phases 2, 3 and 4
    python precompute.py --limit4 10     # cap Phase 4 to the first 10 per class
    python precompute.py --kinds heatmap # redo one backend only

Safe to re-run: finished jobs are skipped unless --force is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

# This script is the thing that BUILDS the cache, so it must always hit the real
# models -- otherwise run_model() would replay an existing manifest back at us.
import os
os.environ["SURVEY_LIVE_INFERENCE"] = "1"

OUT_DIR = APP_DIR / "precomputed"
MANIFEST_PATH = OUT_DIR / "manifest.json"

IMAGE_EXTS = {".bmp", ".jpg", ".jpeg", ".png"}
PHASE4_KINDS = ("heatmap", "prototree", "clustering", "weakly_supervised")

# Result fields holding a path to a generated artifact.
FILE_FIELDS = (
    "explanation_image",
    "explanation_image_global",
    "explanation_image_local",
    "explanation_pdf",
)


def image_key(path: Path) -> str:
    """Content hash. Phase 2 and Phase 3 reuse filenames for different images,
    so the name alone is not a safe cache key."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest[:16]


def cache_key(kind: str, path: Path) -> str:
    return f"{kind}|{image_key(path)}"


def iter_images(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(p for p in directory.iterdir() if p.suffix.lower() in IMAGE_EXTS)


def build_jobs(limit4: int | None, kinds: tuple[str, ...]) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    images = APP_DIR / "images"

    # Phases 2 and 3 both call run_model() with the default backend.
    for phase in ("phase_2", "phase_3"):
        for img in iter_images(images / phase):
            if "weakly_supervised" in kinds:
                jobs.append({"phase": phase, "path": img, "kind": "weakly_supervised"})

    # Ask the app itself which Phase 4 images it will show, rather than guessing.
    # A mismatch here means a participant hits an image with no cached result.
    from phase4_pages import PHASE4_IMAGES_PER_LABEL, select_phase4_images
    from utils import get_phase4_labeled_images

    per_label = limit4 if limit4 is not None else PHASE4_IMAGES_PER_LABEL
    for item in select_phase4_images(get_phase4_labeled_images(), per_label):
        img = Path(item["path"])
        for kind in kinds:
            jobs.append({"phase": "phase_4", "path": img, "kind": kind})

    # Deduplicate: identical image content under the same backend is one job.
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for job in jobs:
        key = cache_key(job["kind"], job["path"])
        if key in seen:
            continue
        seen.add(key)
        job["key"] = key
        unique.append(job)
    return unique


def apply_defaults(kind: str) -> None:
    import utils

    if kind == "weakly_supervised":
        utils.use_phase2_weakly_supervised_defaults()
    elif kind == "heatmap":
        utils.use_phase2_heatmap_defaults()
    elif kind == "prototree":
        utils.use_phase2_prototree_defaults()
    elif kind == "feature_importance":
        utils.use_phase2_feature_importance_defaults()
    elif kind == "clustering":
        pass  # clustering reads its own vendored defaults
    else:
        raise ValueError(f"Unsupported backend: {kind}")


def stash(src_value: Any, dest_dir: Path) -> str | None:
    """Copy one generated artifact into dest_dir; return its path relative to OUT_DIR."""
    if not src_value:
        return None
    src = Path(str(src_value))
    if not src.is_file():
        return None
    dest = dest_dir / src.name
    if src.resolve() != dest.resolve():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
    return dest.relative_to(OUT_DIR).as_posix()


def localize(result: dict[str, Any], dest_dir: Path) -> dict[str, Any]:
    """Copy every artifact the result points at and rewrite paths to be relative,
    so the manifest stays portable across machines and hosts."""
    out = dict(result)

    for field in FILE_FIELDS:
        out[field] = stash(out.get(field), dest_dir)

    cases = out.get("nearest_latent_cases")
    if isinstance(cases, list):
        rebuilt = []
        for case in cases:
            if not isinstance(case, dict):
                continue
            case = dict(case)
            case["image_path"] = stash(case.get("image_path"), dest_dir / "cases")
            rebuilt.append(case)
        out["nearest_latent_cases"] = rebuilt

    # Absolute paths from the generating machine must not leak into the manifest.
    out["artifact_dir"] = dest_dir.relative_to(OUT_DIR).as_posix()
    out.pop("image_path", None)

    # Provenance fields keep their identity but not the generating machine's layout.
    for field in ("model_checkpoint", "model_backend"):
        value = out.get(field)
        if isinstance(value, str) and value:
            try:
                out[field] = Path(value).relative_to(APP_DIR).as_posix()
            except ValueError:
                out[field] = Path(value).name
    return out


def dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
    return total / 1024**2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit4", type=int, default=None,
                        help="override Phase 4 images per class; default follows the app")
    parser.add_argument("--kinds", nargs="+", default=list(PHASE4_KINDS),
                        choices=list(PHASE4_KINDS) + ["feature_importance"])
    parser.add_argument("--force", action="store_true", help="regenerate existing entries")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {}
    if MANIFEST_PATH.exists() and not args.force:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

    jobs = build_jobs(args.limit4, tuple(args.kinds))
    todo = [j for j in jobs if args.force or j["key"] not in manifest]
    print(f"{len(jobs)} jobs total, {len(todo)} to run "
          f"({len(jobs) - len(todo)} already cached)\n", flush=True)

    from utils import run_model

    failures: list[tuple[str, str]] = []
    started = time.time()

    for index, job in enumerate(todo, start=1):
        kind, img, key = job["kind"], job["path"], job["key"]
        label = f"[{index}/{len(todo)}] {kind:18s} {img.name}"
        tick = time.time()
        try:
            apply_defaults(kind)
            result = run_model(img_path=str(img), explanation_kind=kind, image_name=img.name)
            dest = OUT_DIR / kind / image_key(img)
            # Some backends tag output filenames with a per-run token, so a rerun
            # would leave the previous run's files behind. Start from empty.
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True, exist_ok=True)
            entry = localize(result, dest)
            entry["_source_image"] = f"{job['phase']}/{img.name}"
            manifest[key] = entry
            MANIFEST_PATH.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
            print(f"{label}  {time.time() - tick:6.1f}s  ok", flush=True)
        except Exception as exc:  # keep going; report at the end
            failures.append((label, f"{type(exc).__name__}: {exc}"))
            print(f"{label}  {time.time() - tick:6.1f}s  FAILED  {type(exc).__name__}: {exc}",
                  flush=True)
            traceback.print_exc(limit=3)

    print(f"\nDone in {(time.time() - started) / 60:.1f} min")
    print(f"Cached entries : {len(manifest)}")
    print(f"precomputed/   : {dir_size_mb(OUT_DIR):.0f} MB")
    for kind in sorted({k.split('|')[0] for k in manifest}):
        print(f"  {kind:18s} {dir_size_mb(OUT_DIR / kind):7.0f} MB")

    if failures:
        print(f"\n{len(failures)} FAILED:")
        for label, err in failures:
            print(f"  {label}  {err}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
