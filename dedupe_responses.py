"""Remove accidental double-submits from the Phase 1-3 responses and comments.

Some questions carry two rows for the same participant. They are of two kinds:

  Phantom submit  the button fired twice; the second row repeats the answer and
                  confidence exactly, and ResponseTimeSeconds collapses to ~0
                  because the timer had just been reset. No deliberation
                  happened, so the row is noise.

  Genuine revisit the participant went back and reconsidered. The answer or
                  confidence changed, or real time elapsed. This is data.

Dropping a row needs BOTH signals: a near-zero response time AND an answer and
confidence identical to another row in the group. Time alone is not enough --
Mihiri corrected Q8 from Benign to Melanoma in 0.81s, which is a real answer.

Whatever survives, the latest row wins, so a revisit keeps the settled answer.

    python dedupe_responses.py --dry-run   # report only, write nothing
    python dedupe_responses.py             # apply, with .bak backups
"""

from __future__ import annotations

import argparse
import csv
import shutil
from collections import defaultdict
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"

# A response time below this is not a human reaction: it means the timer was
# reset and the submit fired again in the same instant.
PHANTOM_SECONDS = 0.1

PHASE_FILES = ("phase1_responses.csv", "phase2_responses.csv", "phase3_responses.csv")


def as_seconds(value: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return float("inf")  # unparseable: never treat as a phantom


def dedupe_phase(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Collapse duplicate (email, question) groups. Returns kept rows in the
    original file order, plus a log line per row removed."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        key = ((row.get("Email") or "").strip().lower(), (row.get("Question") or "").strip())
        groups[key].append(row)

    removed: set[int] = set()
    log: list[str] = []

    for (_email, question), entries in groups.items():
        if len(entries) < 2:
            continue

        ordered = sorted(entries, key=lambda r: str(r.get("Timestamp", "")))
        answers = [(str(r.get("Answer", "")), str(r.get("Confidence", ""))) for r in ordered]

        survivors = []
        for index, row in enumerate(ordered):
            identical_twin = answers.count(answers[index]) > 1
            phantom = as_seconds(row.get("ResponseTimeSeconds", "")) < PHANTOM_SECONDS
            if phantom and identical_twin:
                removed.add(id(row))
                log.append(
                    f"  {row.get('Name')} {question}: dropped phantom submit at "
                    f"{row.get('Timestamp')} (t={row.get('ResponseTimeSeconds')}s, "
                    f"answer {answers[index][0]}/{answers[index][1]} repeated)"
                )
            else:
                survivors.append(row)

        # Never leave a question unanswered: if every row looked like a phantom,
        # put the last one back.
        if not survivors:
            restored = ordered[-1]
            removed.discard(id(restored))
            log.append(f"  {restored.get('Name')} {question}: all rows looked like "
                       "phantoms; kept the last one rather than lose the answer")
            survivors = [restored]

        # A genuine revisit leaves more than one survivor: the settled answer is
        # the latest.
        if len(survivors) > 1:
            for row in survivors[:-1]:
                removed.add(id(row))
            final = survivors[-1]
            log.append(
                f"  {final.get('Name')} {question}: revisit, kept latest "
                f"{final.get('Timestamp')} (answer {final.get('Answer')}/"
                f"{final.get('Confidence')}, t={final.get('ResponseTimeSeconds')}s); "
                f"superseded {len(survivors) - 1} earlier row(s)"
            )

    kept = [r for r in rows if id(r) not in removed]
    return kept, log


def dedupe_comments(rows: list[dict]) -> tuple[list[dict], list[str]]:
    """Drop repeated identical comments from the same person."""
    seen: set[tuple[str, str]] = set()
    kept, log = [], []
    for row in rows:
        key = ((row.get("Email") or "").strip().lower(), (row.get("Comment") or "").strip())
        if key in seen:
            log.append(f"  {row.get('Name')}: dropped duplicate comment at "
                       f"{row.get('Timestamp')} (identical text already recorded)")
            continue
        seen.add(key)
        kept.append(row)
    return kept, log


def read_csv(path: Path) -> tuple[list[str], list[dict]]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), [dict(r) for r in reader]


def write_csv(path: Path, headers: list[str], rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    report = ["# Phase 1-3 duplicate removal", "",
              f"A row is removed only when its response time is below "
              f"{PHANTOM_SECONDS}s *and* its answer and confidence repeat another "
              "row in the same question group. Where a real revisit leaves several "
              "rows, the latest is kept.", ""]
    total_removed = 0
    plan: list[tuple[Path, list[str], list[dict]]] = []

    for name in PHASE_FILES + ("comments.csv",):
        path = DATA_DIR / name
        if not path.is_file():
            print(f"{name}: not found, skipped")
            continue

        headers, rows = read_csv(path)
        if name == "comments.csv":
            kept, log = dedupe_comments(rows)
        else:
            kept, log = dedupe_phase(rows)

        removed = len(rows) - len(kept)
        total_removed += removed
        print(f"{name}: {len(rows)} -> {len(kept)} rows ({removed} removed)")
        for line in log:
            print(line)

        report += [f"## {name}", "", f"{len(rows)} rows -> {len(kept)} ({removed} removed)", ""]
        report += [f"- {l.strip()}" for l in log] or ["- No duplicates."]
        report.append("")
        plan.append((path, headers, kept))

    print(f"\ntotal rows removed: {total_removed}")

    if args.dry_run:
        print("--dry-run: nothing written")
        return 0

    for path, headers, kept in plan:
        backup = path.with_suffix(path.suffix + ".bak")
        # Back up once only: re-running must never copy deduped data over the
        # original, which would destroy the removed rows for good.
        if not backup.exists():
            shutil.copy2(path, backup)
            print(f"  backed up {path.name} -> {backup.name}")
        else:
            print(f"  {backup.name} already exists, left untouched")
        write_csv(path, headers, kept)

    (DATA_DIR / "dedupe_report.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\nReport: data/dedupe_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
