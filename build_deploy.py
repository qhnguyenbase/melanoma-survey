"""Assemble a deploy-ready copy of the survey in ../survey_deploy.

The working repo carries ~6 GB of vendored model code, training checkpoints and
datasets that the deployed app never touches. This copies across only what the
survey needs to run from the precomputed cache, and initialises a fresh git
repo so none of that 6 GB is in the history.

    python build_deploy.py            # build ../survey_deploy
    python build_deploy.py --dest X   # build somewhere else
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

# Files the running survey imports.
MODULES = [
    "Home.py", "intro_page.py", "utils.py", "precomputed_backend.py",
    "i18n.py", "pdf_fonts.py",
    "phase1_pages.py", "phase2_pages.py", "phase3_pages.py", "phase4_pages.py",
    "thank_you_page.py", "precompute.py", "build_deploy.py", "fetch_responses.py", "reconcile_phase4.py", "dedupe_responses.py", "make_secrets.py",
    "requirements.txt", "requirements-dev.txt",
]

GITIGNORE = """\
# Never commit credentials: they go in Streamlit secrets instead.
service_account.json
.streamlit/secrets.toml

# Participant data must never be committed: this repo may be public, and the
# rows carry names and email addresses. Google Sheets is the durable copy.
data/*.csv
data/*.json
data/*.bak
data/*.md

__pycache__/
*.pyc
.venv/
"""

# Without this, git on Windows normalises line endings inside the cached PDFs
# and PNGs, corrupting them on checkout. The survey would then serve broken files.
# Python sources are pinned to LF as well: the repo previously held a mix of
# endings, so an edit made on Windows rewrote whole files as line-ending churn
# and buried the real diff.
GITATTRIBUTES = """\
* -text
*.py text eol=lf
*.md text eol=lf
*.txt text eol=lf
*.pdf binary
*.png binary
*.bmp binary
*.jpg binary
"""

CONFIG_TOML = """\
[server]
headless = true
# Survey images are a few MB; no large uploads happen.
maxUploadSize = 10

[browser]
gatherUsageStats = false

[theme]
base = "light"
"""


def copy_survey_images(dest: Path) -> None:
    """Phases 1-3 ship whole; Phase 4 ships only the seeded stimulus set.

    With exactly PHASE4_IMAGES_PER_LABEL images present per label the sampler
    returns all of them, so the survey shows the same 20 images either way --
    but the repo drops from 203 MB to ~25 MB.
    """
    from phase4_pages import PHASE4_IMAGES_PER_LABEL, select_phase4_images
    from utils import get_phase4_labeled_images

    for phase in ("phase_1", "phase_2", "phase_3"):
        src = APP_DIR / "images" / phase
        if src.is_dir():
            shutil.copytree(src, dest / "images" / phase, dirs_exist_ok=True)

    for item in select_phase4_images(get_phase4_labeled_images(), PHASE4_IMAGES_PER_LABEL):
        src = Path(item["path"])
        label = str(item.get("label", "")).strip().lower()
        target = dest / "images" / "phase_4" / label
        target.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target / src.name)


def force_rmtree(path: Path) -> None:
    """Remove a tree even when it contains a .git directory: git marks objects
    read-only, which makes a plain rmtree fail on Windows."""
    import os
    import stat

    def on_error(func, target, _exc):
        os.chmod(target, stat.S_IWRITE)
        func(target)

    shutil.rmtree(path, onexc=on_error)


def dir_size_mb(path: Path) -> float:
    if not path.exists():
        return 0.0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1024**2


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=str(APP_DIR.parent / "survey_deploy"))
    parser.add_argument("--no-git", action="store_true", help="skip git init/commit")
    parser.add_argument("--message", "-m",
                        default="Melanoma explanation survey, precomputed build",
                        help="commit message for this build")
    args = parser.parse_args()

    dest = Path(args.dest).resolve()
    if dest == APP_DIR:
        print("Refusing to build into the source directory.")
        return 1

    manifest = APP_DIR / "precomputed" / "manifest.json"
    if not manifest.is_file():
        print("No precomputed/manifest.json -- run `python precompute.py` first.")
        return 1

    # Preserve an existing .git: once the repo has been pushed, wiping it would
    # discard the origin remote and the history, turning every later update into
    # a force-push. Clear only the working tree.
    had_repo = (dest / ".git").is_dir()
    if dest.exists():
        for entry in dest.iterdir():
            if entry.name == ".git":
                continue
            force_rmtree(entry) if entry.is_dir() else entry.unlink()
    else:
        dest.mkdir(parents=True)

    for name in MODULES:
        src = APP_DIR / name
        if src.is_file():
            shutil.copy2(src, dest / name)

    shutil.copytree(APP_DIR / "pages", dest / "pages",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copytree(APP_DIR / "precomputed", dest / "precomputed")
    copy_survey_images(dest)

    (dest / "data").mkdir(exist_ok=True)
    (dest / "data" / ".gitkeep").write_text("", encoding="utf-8")
    (dest / ".streamlit").mkdir(exist_ok=True)
    (dest / ".streamlit" / "config.toml").write_text(CONFIG_TOML, encoding="utf-8")
    (dest / ".gitignore").write_text(GITIGNORE, encoding="utf-8")
    (dest / ".gitattributes").write_text(GITATTRIBUTES, encoding="utf-8")

    for doc in ("DEPLOY.md", "README.md"):
        src = APP_DIR / doc
        if src.is_file():
            shutil.copy2(src, dest / doc)

    print(f"Built {dest}")
    print(f"  total       {dir_size_mb(dest):7.0f} MB")
    print(f"  precomputed {dir_size_mb(dest / 'precomputed'):7.0f} MB")
    print(f"  images      {dir_size_mb(dest / 'images'):7.0f} MB")

    if not args.no_git:
        try:
            if not had_repo:
                subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
            subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
            status = subprocess.run(["git", "status", "--porcelain"], cwd=dest,
                                    capture_output=True, text=True).stdout.strip()
            if not status:
                print("  no changes to commit")
            else:
                subprocess.run(
                    ["git", "commit", "-q", "-m", args.message], cwd=dest, check=True,
                )
                changed = len(status.splitlines())
                print(f"  committed {changed} changed file(s)"
                      + ("" if had_repo else " into a new repo"))
        except (subprocess.CalledProcessError, FileNotFoundError) as exc:
            print(f"  git step skipped: {exc}")

    # GitHub's 100 MB cap applies to tracked files, not to git's own packfiles.
    oversize = [
        f for f in dest.rglob("*")
        if f.is_file() and ".git" not in f.relative_to(dest).parts
        and f.stat().st_size > 100 * 1024**2
    ]
    if oversize:
        print("\nWARNING: files over GitHub's 100 MB limit:")
        for f in oversize:
            print(f"  {f.stat().st_size / 1024**2:.0f} MB  {f.relative_to(dest)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
