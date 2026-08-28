"""Convert a Google service-account JSON key into the TOML block Streamlit wants.

Pasting the key by hand is the most common cause of a failed deploy: the
`private_key` value contains literal \\n sequences that must survive intact, and
hand-editing usually breaks them. This does the conversion for you.

    python make_secrets.py path\\to\\service_account.json

Prints the block to paste into Streamlit Cloud's Advanced settings -> Secrets.
Add --write to also create .streamlit/secrets.toml for local use (git-ignored).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent

REQUIRED = [
    "type", "project_id", "private_key_id", "private_key",
    "client_email", "client_id", "auth_uri", "token_uri",
    "auth_provider_x509_cert_url", "client_x509_cert_url",
]


def toml_escape(value: str) -> str:
    """Escape for a TOML basic string, keeping newlines as literal \\n."""
    return (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "")
        .replace("\t", "\\t")
    )


def build_block(data: dict) -> str:
    lines = ["[gcp_service_account]"]
    for key in REQUIRED:
        if key in data:
            lines.append(f'{key} = "{toml_escape(str(data[key]))}"')
    # Preserve anything else the key file carries (e.g. universe_domain).
    for key, value in data.items():
        if key not in REQUIRED:
            lines.append(f'{key} = "{toml_escape(str(value))}"')
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_path", help="the service-account JSON you downloaded")
    parser.add_argument("--write", action="store_true",
                        help="also write .streamlit/secrets.toml for local use")
    args = parser.parse_args()

    path = Path(args.json_path).expanduser()
    if not path.is_file():
        print(f"Not found: {path}")
        return 1

    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [k for k in REQUIRED if k not in data]
    if missing:
        print(f"WARNING: key file is missing {', '.join(missing)} -- "
              "is this really a service-account key?")

    block = build_block(data)

    email = data.get("client_email", "")
    print("=" * 68)
    print(block, end="")
    print("=" * 68)
    print()
    print("1. Copy everything between the lines into Streamlit's Secrets box.")
    if email:
        print(f"2. Share your 'Melanoma_Survey_Results' Sheet with:\n     {email}")
        print("   as an Editor, or the app cannot write to it.")

    if args.write:
        target = APP_DIR / ".streamlit" / "secrets.toml"
        target.parent.mkdir(exist_ok=True)
        target.write_text(block, encoding="utf-8")
        print(f"\nAlso wrote {target}")
        print("This file is git-ignored. Never commit it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
