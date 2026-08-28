"""Reconcile the two Phase 4 response files into one authoritative set.

`phase4_responses.json` and `phase4_responses_flat.csv` are written by separate
code paths and had drifted: 7 records in the CSV, 6 in the JSON, 5 in common.
This merges them, resolves the conflicts against corroborating evidence in
participants.csv and the Phase 1-3 responses, and rewrites both files in sync.

Originals are copied to *.bak first, and every decision is written to
data/reconciliation_report.md. Nothing is discarded silently.

    python reconcile_phase4.py            # apply
    python reconcile_phase4.py --dry-run  # report only, write nothing
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))
DATA_DIR = APP_DIR / "data"

MODELS = ["Grad-CAM", "ProtoTree", "Clustering", "Concept-Based"]
METRICS = ["Fidelity", "Comprehensibility", "Effectiveness", "Usefulness", "Stability"]


def score_signature(scores: dict) -> tuple:
    """The 20 metric values, independent of dict ordering."""
    return tuple(scores.get(m, {}).get(k) for m in MODELS for k in METRICS)


def load_participants() -> dict[str, dict[str, str]]:
    """email(lower) -> {name, email, registered}.

    Email is the stable key: names carry stray whitespace and inconsistent
    casing across files, emails do not.
    """
    out: dict[str, dict[str, str]] = {}
    path = DATA_DIR / "participants.csv"
    if not path.is_file():
        return out
    with path.open(newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            email = (row.get("Email") or "").strip()
            if not email:
                continue
            key = email.lower()
            stamp = (row.get("Timestamp") or "").strip()
            # Keep the earliest registration for anyone who registered twice.
            if key not in out or stamp < out[key]["registered"]:
                out[key] = {
                    "name": (row.get("Name") or "").strip(),
                    "email": email,
                    "registered": stamp,
                }
    return out


def emails_in_earlier_phases() -> set[str]:
    """Everyone who submitted anything in Phases 1-3."""
    found: set[str] = set()
    for phase in ("phase1", "phase2", "phase3"):
        path = DATA_DIR / f"{phase}_responses.csv"
        if not path.is_file():
            continue
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                email = (row.get("Email") or "").strip().lower()
                if email:
                    found.add(email)
    return found


def load_flat() -> list[dict]:
    from fetch_responses import rebuild_phase4_json

    path = DATA_DIR / "phase4_responses_flat.csv"
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8-sig") as f:
        return rebuild_phase4_json([dict(r) for r in csv.DictReader(f)])


def load_json() -> list[dict]:
    path = DATA_DIR / "phase4_responses.json"
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [r for r in data if isinstance(r, dict)]


def write_flat(path: Path, records: list[dict]) -> None:
    headers = ["Timestamp", "Name", "Email"]
    headers += [f"{m}_{k}" for m in MODELS for k in METRICS]
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        for rec in records:
            row = {
                "Timestamp": rec["Timestamp"],
                "Name": rec["Name"],
                "Email": rec["Email"],
            }
            scores = rec["InterpretabilityScores"]
            for model in MODELS:
                for metric in METRICS:
                    row[f"{model}_{metric}"] = scores.get(model, {}).get(metric)
            writer.writerow(row)


def reconcile() -> tuple[list[dict], list[tuple[dict, str]], list[str], int, int]:
    participants = load_participants()
    earlier = emails_in_earlier_phases()
    flat, nested = load_flat(), load_json()

    # Group records from both files by (email, scores). The same submission
    # written to both files lands in one group even when its timestamp or name
    # spelling disagrees between them.
    groups: dict[tuple, list[tuple[str, dict]]] = {}
    for source, records in (("flat_csv", flat), ("json", nested)):
        for rec in records:
            key = (
                (rec.get("Email") or "").strip().lower(),
                score_signature(rec.get("InterpretabilityScores", {})),
            )
            groups.setdefault(key, []).append((source, rec))

    log: list[str] = []
    kept: list[dict] = []
    excluded: list[tuple[dict, str]] = []

    for (email, signature), entries in groups.items():
        record = dict(entries[0][1])
        sources = sorted({s for s, _ in entries})
        person = participants.get(email)

        # Unverified: never registered AND absent from every earlier phase.
        if person is None and email not in earlier:
            reasons = ["not in participants.csv", "no Phase 1-3 responses"]
            if len(sources) == 1:
                reasons.append(f"present only in {sources[0]}")
            twins = [
                participants[other]["name"]
                for other, _sig in groups
                if _sig == signature and other != email and other in participants
            ]
            if twins:
                reasons.append(f"scores identical to {', '.join(sorted(set(twins)))}")
            excluded.append((record, "; ".join(reasons)))
            continue

        # Timestamp conflict: prefer one consistent with the registration time.
        stamps = sorted({(r.get("Timestamp") or "").strip() for _, r in entries})
        if len(stamps) > 1:
            registered = person["registered"] if person else ""
            plausible = [s for s in stamps if not registered or s >= registered]
            chosen = min(plausible) if plausible else max(stamps)
            dropped = [s for s in stamps if s != chosen]
            record["Timestamp"] = chosen
            if registered and plausible:
                log.append(
                    f"- **{record.get('Name')}** timestamp conflict {stamps} -> kept "
                    f"`{chosen}`. Registered `{registered}`, so {dropped} predate "
                    "registration and are impossible."
                )
            else:
                log.append(
                    f"- **{record.get('Name')}** timestamp conflict {stamps} -> kept "
                    f"`{chosen}` (no usable registration time; took the later stamp)."
                )

        # Canonical name and email come from the registration record.
        if person:
            if record.get("Name") != person["name"]:
                log.append(
                    f"- Name normalised {record.get('Name')!r} -> {person['name']!r} "
                    "(from participants.csv)"
                )
            record["Name"] = person["name"]
            record["Email"] = person["email"]
        else:
            record["Name"] = (record.get("Name") or "").strip()
            record["Email"] = (record.get("Email") or "").strip()

        if len(sources) == 1:
            log.append(
                f"- **{record['Name']}** existed only in `{sources[0]}`; "
                "now written to both files."
            )
        kept.append(record)

    kept.sort(key=lambda r: r["Timestamp"])
    return kept, excluded, log, len(flat), len(nested)


def build_report(kept, excluded, log, n_flat, n_json) -> str:
    lines = [
        "# Phase 4 reconciliation",
        "",
        f"Sources: `phase4_responses_flat.csv` ({n_flat} records), "
        f"`phase4_responses.json` ({n_json} records).",
        "",
        f"**Result: {len(kept)} authoritative records.**",
        "",
        "## Decisions",
        "",
    ]
    lines += log or ["- No conflicts found."]
    lines += ["", "## Excluded", ""]
    if excluded:
        for rec, why in excluded:
            lines.append(
                f"- **{rec.get('Name')}** (`{rec.get('Email')}`, "
                f"`{rec.get('Timestamp')}`) — {why}."
            )
        lines += [
            "",
            "Excluded records remain in the `.bak` files. To restore one, copy its "
            "row back into both reconciled files.",
        ]
    else:
        lines.append("- None.")
    lines += ["", "## Final set", ""]
    for rec in kept:
        lines.append(f"- `{rec['Timestamp']}` {rec['Name']} <{rec['Email']}>")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    kept, excluded, log, n_flat, n_json = reconcile()
    report = build_report(kept, excluded, log, n_flat, n_json)

    print(f"flat_csv {n_flat} + json {n_json} -> {len(kept)} reconciled, "
          f"{len(excluded)} excluded")
    for line in log:
        print("  " + line.replace("**", "").replace("`", ""))
    for rec, why in excluded:
        print(f"  EXCLUDED {rec.get('Name')}: {why}")

    if args.dry_run:
        print("\n--dry-run: nothing written")
        return 0

    # Back up once, on the first run only. Re-running would otherwise copy the
    # already-reconciled files over the backups and destroy the pre-merge
    # originals -- including any record this script excluded.
    for name in ("phase4_responses.json", "phase4_responses_flat.csv"):
        src = DATA_DIR / name
        backup = src.with_suffix(src.suffix + ".bak")
        if src.is_file() and not backup.exists():
            shutil.copy2(src, backup)
            print(f"  backed up {name} -> {backup.name}")
        elif backup.exists():
            print(f"  {backup.name} already exists, left untouched")

    (DATA_DIR / "phase4_responses.json").write_text(
        json.dumps(kept, indent=2), encoding="utf-8"
    )
    write_flat(DATA_DIR / "phase4_responses_flat.csv", kept)
    (DATA_DIR / "reconciliation_report.md").write_text(report, encoding="utf-8")

    print(f"\nWrote {len(kept)} records to both files (originals kept as *.bak)")
    print("Report: data/reconciliation_report.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
