"""Refresh Amazfit tokens via huami-token (logs out mobile app).

WARNING: This method creates a new Zepp session, which WILL log you out
         of the Zepp mobile app. Use `extract_tokens_web.py` instead
         to avoid this.

Writes tokens to data/auth_state.json — .env keeps only permanent config.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

AMAZFIT_SYNC_DIR = Path(__file__).resolve().parent
HUAMI_TOKEN_DIR = AMAZFIT_SYNC_DIR.parent / "huami-token"
AUTH_STATE_PATH = AMAZFIT_SYNC_DIR / "data" / "auth_state.json"

EMAIL = os.getenv("AMAZFIT_EMAIL", "")
PASSWORD = os.getenv("AMAZFIT_PASSWORD", "")


def run_huami_token(email: str, password: str) -> dict[str, str]:
    """Run huami-token with --no_logout and parse token output."""
    result = subprocess.run(
        [
            "uv", "run", "main.py",
            "--method", "amazfit",
            "--email", email,
            "--password", password,
            "--no_logout",
        ],
        cwd=str(HUAMI_TOKEN_DIR),
        capture_output=True,
        text=True,
        timeout=60,
    )

    stderr = result.stderr.strip()
    stdout = result.stdout.strip()

    if result.returncode != 0:
        print(f"huami-token failed (exit code {result.returncode})")
        if stderr:
            print(stderr)
        if "Error:" in stderr or "Error:" in stdout:
            sys.exit(1)

    tokens: dict[str, str] = {}
    for line in stdout.splitlines():
        for key in ("access_token", "refresh_token", "app_token", "login_token", "user_id"):
            m = re.match(rf"^{key}=(.*)", line.strip())
            if m:
                tokens[key] = m.group(1)

    if "access_token" not in tokens or "refresh_token" not in tokens:
        print("ERROR: Could not parse access_token/refresh_token from huami-token output.")
        print("stdout:")
        print(stdout)
        if stderr:
            print("stderr:")
            print(stderr)
        sys.exit(1)

    return tokens


def update_auth_state(tokens: dict[str, str]) -> None:
    """Write fresh tokens to auth_state.json, preserving device_id."""
    existing: dict = {}
    if AUTH_STATE_PATH.exists():
        try:
            existing = json.loads(AUTH_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    for token_key in ("access_token", "refresh_token", "app_token", "user_id"):
        if token_key in tokens:
            existing[token_key] = tokens[token_key]

    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_STATE_PATH.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Updated {AUTH_STATE_PATH}")


def main() -> None:
    print("Running huami-token to get fresh tokens...")
    print("WARNING: This will log you out of the Zepp mobile app.")
    print("For a non-destructive method, use: python extract_tokens_web.py")
    print()

    tokens = run_huami_token(EMAIL, PASSWORD)
    update_auth_state(tokens)

    print()
    print("Done! Tokens refreshed. You can now run:")
    print("  python main.py sync")


if __name__ == "__main__":
    main()
