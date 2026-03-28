from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class AuthStateError(RuntimeError):
    """Raised when the local auth state file cannot be parsed."""


class AuthStateStore:
    """Read and persist local authentication state."""

    def __init__(self, path: Path) -> None:
        self.path = path

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise AuthStateError(
                f"Failed to read auth state from {self.path.as_posix()}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise AuthStateError(
                f"Auth state at {self.path.as_posix()} must be a JSON object."
            )
        return payload

    def update(self, **values: Any) -> dict[str, Any]:
        state = self.load()
        changed = False
        for key, value in values.items():
            if value in (None, ""):
                continue
            if state.get(key) == value:
                continue
            state[key] = value
            changed = True
        if not changed:
            return state

        state["updated_at"] = _utc_now()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        return state


def load_auth_state(path: Path) -> dict[str, Any]:
    """Load the local auth state if present."""
    return AuthStateStore(path).load()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
