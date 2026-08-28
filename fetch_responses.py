"""Download every survey response from Google Sheets into `data/`.

The deployed app writes to Google Sheets because a hosted filesystem is wiped on
each restart. This pulls that data back down into the same filenames and formats
the app uses locally, so analysis scripts see one consistent layout:

    data/participants.csv
    data/phase1_responses.csv
    data/phase2_responses.csv
    data/phase3_responses.csv
    data/phase4_responses_flat.csv
    data/phase4_responses.json     (rebuilt from the flat scores)
    data/comments.csv

Usage:
    python fetch_responses.py                 # write into data/
    python fetch_responses.py --dest exports  # somewhere else
    python fetch_responses.py --merge         # keep local rows not in Sheets

Credentials come from st.secrets or service_account.json, same as the app.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

# Tab name -> local filename. Tabs are named after the CSV stem by save_to_csv.
KNOWN_TABS = {
    "participants": "participants.csv",
    "phase1_responses": "phase1_responses.csv",
    "phase2_responses": "phase2_responses.csv",
    "phase3_responses": "phase3_responses.csv",
    "phase4_responses_flat": "phase4_responses_flat.csv",
    "comments": "comments.csv",
}

IDENTITY_COLUMNS = ("Timestamp", "Name", "Email")


def rebuild_phase4_json(rows: list[dict[str, str]]) -> list[dict]:
    """Reconstruct the nested phase4_responses.json from the flat score columns.

    Flat headers look like `Grad-CAM_Fidelity`; the JSON nests them under
    InterpretabilityScores[model][metric]. Model labels may contain a hyphen,
    so split on the LAST underscore.
    """
    records = []
    for row in rows:
        scores: dict[str, dict[str, int | None]] = {}
        for header, value in row.items():
            if header in IDENTITY_COLUMNS or "_" not in header:
                continue
            model, _, metric = header.rpartition("_")
            text = str(value).strip()
            try:
                parsed: int | None = int(float(text)) if text else None
            except ValueError:
                parsed = None
            scores.setdefault(model, {})[metric] = parsed
        records.append({
            "Timestamp": row.get("Timestamp", ""),
            "Name": row.get("Name", ""),
            "Email": row.get("Email", ""),
            "InterpretabilityScores": scores,
        })
    return records


def read_local(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.is_file() or path.stat().st_size == 0:
        return [], []
    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader.fieldnames or []), [dict(r) for r in reader]


def merge_rows(local: list[dict[str, str]], remote: list[dict[str, str]]) -> list[dict[str, str]]:
    """Union of local and remote, de-duplicated on the identity columns and
    ordered by timestamp. Lets you keep rows captured before Sheets was wired up."""
    combined: dict[tuple, dict[str, str]] = {}
    for row in list(local) + list(remote):
        key = tuple(str(row.get(c, "")).strip() for c in IDENTITY_COLUMNS)
        combined[key] = row
    return sorted(combined.values(), key=lambda r: str(r.get("Timestamp", "")))


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=str(APP_DIR / "data"))
    parser.add_argument("--merge", action="store_true",
                        help="keep existing local rows that are absent from Sheets")
    args = parser.parse_args()

    import utils

    if not utils.sheets_configured():
        print("No Google Sheets credentials found.")
        print("Add [gcp_service_account] to .streamlit/secrets.toml, or put")
        print("service_account.json beside utils.py. See DEPLOY.md step 1.")
        return 1

    dest = Path(args.dest).resolve()
    spreadsheet = utils._sheet_client().open(utils.SHEET_NAME)

    total = 0
    seen_tabs = []
    phase4_rows: list[dict[str, str]] = []

    for worksheet in spreadsheet.worksheets():
        tab = worksheet.title
        filename = KNOWN_TABS.get(tab, f"{tab}.csv")
        records = worksheet.get_all_records()  # first row is the header
        seen_tabs.append(tab)

        if not records:
            print(f"  {tab:24s} empty")
            continue

        headers = list(records[0].keys())
        rows = [{k: ("" if v is None else str(v)) for k, v in r.items()} for r in records]

        if args.merge:
            local_headers, local_rows = read_local(dest / filename)
            if local_rows:
                before = len(rows)
                rows = merge_rows(local_rows, rows)
                headers = local_headers or headers
                print(f"  {tab:24s} {before} from Sheets + "
                      f"{len(rows) - before} local-only = {len(rows)}")

        write_csv(dest / filename, headers, rows)
        total += len(rows)
        if tab == "phase4_responses_flat":
            phase4_rows = rows
        if not args.merge:
            print(f"  {tab:24s} {len(rows):4d} rows -> data/{filename}")

    if phase4_rows:
        records = rebuild_phase4_json(phase4_rows)
        (dest / "phase4_responses.json").write_text(
            json.dumps(records, indent=2), encoding="utf-8"
        )
        print(f"  {'phase4_responses.json':24s} {len(records):4d} records (rebuilt from flat)")

    missing = [t for t in KNOWN_TABS if t not in seen_tabs]
    print(f"\n{total} rows written to {dest}")
    if missing:
        print(f"No tab yet for: {', '.join(missing)} (nobody has submitted that section)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
