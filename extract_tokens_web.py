"""Extract Zepp app_token from browser cookies (no mobile logout!).

Log into https://watchface.zepp.com/ in your browser, run the JS snippet
below in the browser console (F12), then paste the output here.

The browser session is separate from the mobile app session — this method
does NOT invalidate your phone's Zepp login.

Writes tokens to data/auth_state.json (temporary) — .env keeps only
permanent config (user_id, country_code, paths).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

AUTH_STATE_PATH = Path(__file__).resolve().parent / "data" / "auth_state.json"

JS_SNIPPET = """\
// Paste this into the browser console at https://watchface.zepp.com/
(() => {
  const c = document.cookie;
  const match = c.match("hm-user-login-info=(.*?);");
  if (!match) {
    alert("Not logged in. Please log into https://watchface.zepp.com/ first.");
    return;
  }
  const info = JSON.parse(decodeURIComponent(match[1].replaceAll("%2C", ",")));
  const { app_token, user_id, login_token } = info.token_info || info;
  const result = JSON.stringify({ app_token, user_id, login_token });
  console.log("Copy the line below and paste into the script:");
  console.log(result);
  prompt("Tokens (Ctrl+C to copy):", result);
})();
"""


def update_auth_state(app_token: str, user_id: str) -> None:
    """Write fresh app_token and user_id to auth_state.json, preserving other keys."""
    existing: dict = {}
    if AUTH_STATE_PATH.exists():
        try:
            existing = json.loads(AUTH_STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    existing["app_token"] = app_token
    existing["user_id"] = user_id
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    AUTH_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUTH_STATE_PATH.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Updated {AUTH_STATE_PATH}")


def parse_input(text: str) -> dict[str, str] | None:
    """Parse JSON token payload from user input."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    app_token = data.get("app_token")
    user_id = data.get("user_id")
    if not app_token or not user_id:
        print("ERROR: JSON must contain app_token and user_id keys.")
        return None

    return {"app_token": str(app_token), "user_id": str(user_id)}


def main() -> None:
    print("=" * 60)
    print("Zepp Token Extractor (no mobile logout)")
    print("=" * 60)
    print()
    print("1. Open https://watchface.zepp.com/ in your browser")
    print("2. Log in with your Zepp account (if not already)")
    print("3. Press F12, go to the Console tab")
    print("4. Paste the JS snippet below and press Enter")
    print()
    print(JS_SNIPPET)
    print()
    print("5. Copy the JSON output and paste it below:")
    print()

    try:
        raw = input("Tokens JSON: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nCancelled.")
        sys.exit(0)

    tokens = parse_input(raw)
    if tokens is None:
        print("ERROR: Could not parse input. Expected JSON with app_token and user_id.")
        print(f"Received: {raw[:200]}")
        sys.exit(1)

    update_auth_state(tokens["app_token"], tokens["user_id"])

    print()
    print("Done! Run: python main.py sync")


if __name__ == "__main__":
    main()
